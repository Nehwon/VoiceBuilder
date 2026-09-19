"""Pipeline multi-voix : parse -> regrouper -> blocs adaptatifs vérifiés -> montage."""
from __future__ import annotations

import queue
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from . import adaptive, config, cosyvoice_engine
from .tagging import parse_texte, regrouper
from .voix import Voices


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _synthesize_for(
    text: str, model, sr, voice, block_chars, speed, verify
) -> np.ndarray:
    """Synthetise un bloc pour une voix donnée (avec découpage adaptatif vérifié)."""
    def synth(t: str, _pw="", _pt=""):
        return cosyvoice_engine.synthesize(t, str(voice.wav), voice.system_prompt,
                                            model, sr, speed=speed)
    return adaptive.synthesize_verified(
        text, str(voice.wav), voice.system_prompt, synth, sr,
        max_chars=block_chars, verify=verify,
    )


def load(device: Optional[str] = None, fp16: Optional[bool] = None,
         load_vllm: bool = False, load_trt: bool = False):
    """Ré-export du chargement (une seule fois) du modèle CosyVoice3."""
    return cosyvoice_engine.load(device=device, fp16=fp16,
                                 load_vllm=load_vllm, load_trt=load_trt)


def synth_bloc(
    voice, text: str, model, sample_rate, block_chars=None, speed=None, verify=None,
) -> np.ndarray:
    """Synthetise un seul bloc pour une voix (réutilisable pour la régénération)."""
    block_chars = voice.max_block_chars or block_chars or config.DEFAULT_MAX_BLOCK_CHARS
    spd = voice.speed if voice.speed is not None else (speed or config.DEFAULT_SPEED)
    chk = config.VERIFY_ENABLED if verify is None else verify
    return _synthesize_for(text, model, sample_rate, voice, block_chars, spd, chk)


def generate(
    texte_path: str,
    voices: Voices,
    personnages: Optional[dict] = None,
    out: Optional[str] = None,
    max_block_chars: Optional[int] = None,
    pause: Optional[float] = None,
    speed: Optional[float] = None,
    verify: Optional[bool] = None,
    device: Optional[str] = None,
    fp16: Optional[bool] = None,
    block_dir: Optional[str] = None,
    verbose: bool = True,
    progress=None,
    stop_event=None,
    load_vllm: bool = False,
    load_trt: bool = False,
    file_regen=None,
) -> dict:
    """Génère l'audio complet pour un texte taggé et une liste de voix.

    Les balises du texte sont des **noms de personnages**. ``personnages`` est un
    mapping ``{personnage: nom_de_voix}``. S'il est absent, on suppose que chaque
    personnage porte le même nom qu'une voix (mapping identité, comportement
    historique de l'outil).

    ``out`` : chemin WAV écrit. Renvoie un dict avec ``audio``, ``sample_rate``,
    ``duration``, ``blocs`` et ``out``.

    ``progress`` : callback ``progress(dict)`` appelé à la fin de chaque bloc avec
    ``{index, total, personnage, chars, duree}`` puis, une fois concaténé, avec
    ``{duree: ..., blocs: [...]}`` (utile au GUI serveur). Un bloc régénéré via
    ``file_regen`` émet le même événement avec ``regen: True`` (même ``id``).

    ``stop_event`` : ``threading.Event`` optionnel. S'il est levé, la boucle
    abandonne à la fin du bloc en cours : le résultat (partiel) est rendu avec
    ``stopped: True`` et le WAV (si ``out``) contient les blocs déjà générés.

    ``file_regen`` : ``queue.Queue`` optionnelle d'ids de blocs à régénérer en
    cours de route. Après chaque bloc (et après le dernier), la file est
    dépilée : chaque id déjà généré est re-synthétisé aussitôt (mêmes
    paramètres) et **remplace** l'audio précédent dans le montage. Un id pas
    encore généré est ignoré (il sera synthétisé frais par la boucle). Si
    ``stop_event`` est levé, le reste de la file est abandonné.
    """
    if verbose:
        print(f"Voix disponibles : {voices.names()}")

    if personnages is None:
        personnages = {n: n for n in voices.names()}

    segments = parse_texte(_read_text(texte_path), list(personnages))
    blocs = regrouper(segments)
    inconnus = {pers for pers, _ in blocs if pers not in personnages}
    if inconnus:
        raise ValueError(f"Personnage(s) sans voix définie : {inconnus}")

    model, sr = cosyvoice_engine.load(device=device, fp16=fp16,
                                       load_vllm=load_vllm, load_trt=load_trt)
    max_chars = config.DEFAULT_MAX_BLOCK_CHARS if max_block_chars is None else max_block_chars
    pause = config.DEFAULT_PAUSE if pause is None else pause
    if verify is None:
        verify = config.VERIFY_ENABLED
    pause_n = int(pause * sr)

    parts: List[np.ndarray] = []
    blocs_report: List[dict] = []
    block_dir = Path(block_dir) if block_dir else None
    if block_dir:
        block_dir.mkdir(parents=True, exist_ok=True)

    # Chaque groupe de personnage est fendu en sous-blocs de <= ``max_chars``
    # caractères (adaptive.build_blocks) : un bloc = une unité audio de taille
    # raisonnable, écoutable individuellement dans l'onglet « Montage ».
    sous_blocs: List[tuple] = []
    for pers, block in blocs:
        voix_nom = personnages[pers]
        if voix_nom not in voices:
            raise ValueError(f"Voix introuvable pour le personnage « {pers} » : {voix_nom}")
        voice = voices.get(voix_nom)
        block_chars = voice.max_block_chars or max_chars
        block_speed = voice.speed if voice.speed is not None else (speed or config.DEFAULT_SPEED)
        for t in adaptive.build_blocks(block, block_chars):
            sous_blocs.append((pers, voix_nom, voice, t, block_chars, block_speed))

    total = len(sous_blocs)
    pers_precedent = None
    stopped = False
    positions: List[int] = []  # parts.index de l'audio de chaque bloc (remplacement ciblé)

    def _drain_regen():
        """Re-synthétise aussitôt les blocs mis en file (remplacement en place)."""
        if file_regen is None:
            return
        if stop_event is not None and stop_event.is_set():
            # arrêt demandé : la file est abandonnée avec le reste.
            try:
                while True:
                    file_regen.get_nowait()
            except queue.Empty:
                pass
            return
        while True:
            try:
                bid = file_regen.get_nowait()
            except queue.Empty:
                return
            if not 1 <= bid <= len(blocs_report):
                # pas encore généré : la boucle le synthétisera frais. Ignoré.
                continue
            pers, voix_nom, voice, t, block_chars, block_speed = sous_blocs[bid - 1]
            audio = _synthesize_for(t, model, sr, voice, block_chars, block_speed, verify)
            parts[positions[bid - 1]] = audio
            dur = len(audio) / sr
            blocs_report[bid - 1]["duree"] = round(dur, 2)
            wav_regen = None
            if block_dir:
                wav_regen = str(block_dir / f"bloc_{bid}.wav")
                cosyvoice_engine.save(audio, sr, wav_regen)
            if verbose:
                print(f"[regen {bid}/{total}] {pers} ({len(t)} chars) -> {dur:.2f} s")
            if progress:
                progress({"id": bid, "index": bid, "total": total, "personnage": pers,
                          "voix": voix_nom, "texte": t,
                          "chars": len(t), "duree": round(dur, 2),
                          "wav": wav_regen, "regen": True})

    for i, (pers, voix_nom, voice, t, block_chars, block_speed) in enumerate(sous_blocs, 1):
        # Arrêt demandé : on laisse le bloc en cours se terminer puis on abandonne.
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        audio = _synthesize_for(t, model, sr, voice, block_chars, block_speed, verify)
        # Pause uniquement au changement de personnage : les sous-blocs d'un même
        # locuteur s'enchaînent sans coupure dans le montage final.
        if pers_precedent is not None and pers != pers_precedent:
            parts.append(np.zeros(pause_n, dtype=np.float32))
        positions.append(len(parts))
        parts.append(audio)
        pers_precedent = pers
        dur = len(audio) / sr
        info = {
            "id": i, "personnage": pers, "voix": voix_nom, "texte": t,
            "chars": len(t), "duree": round(dur, 2),
        }
        if block_dir:
            wav = block_dir / f"bloc_{i}.wav"
            cosyvoice_engine.save(audio, sr, str(wav))
            info["wav"] = str(wav)
        blocs_report.append(info)
        if verbose:
            print(f"[{i}/{total}] {pers} ({len(t)} chars) -> {dur:.2f} s")
        if progress:
            progress({"id": i, "index": i, "total": total, "personnage": pers,
                      "voix": voix_nom, "texte": t,
                      "chars": len(t), "duree": round(dur, 2),
                      "wav": info.get("wav")})
        # File de régénération : le bloc en cours est terminé, on traite les
        # demandes empilées avant de continuer la génération globale.
        _drain_regen()

    # File restante (demande arrivée pendant le dernier bloc).
    _drain_regen()

    final = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    res = {
        "audio": final,
        "sample_rate": sr,
        "duration": round(len(final) / sr, 2),
        "blocs": blocs_report,
        "out": out,
    }
    if stopped:
        res["stopped"] = True
        if not parts:
            res["duration"] = 0.0
    if out and parts:
        cosyvoice_engine.save(final, sr, out)
        if verbose:
            label = "Arrêté (partiel)" if stopped else "Enregistré"
            print(f"\n{label} : {out} ({res['duration']} s)")
    if progress:
        progress({"duree": res["duration"], "blocs": len(blocs_report)})
    return res