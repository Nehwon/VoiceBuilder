"""Pipeline multi-voix : parse -> regrouper -> blocs adaptatifs vérifiés -> montage."""
from __future__ import annotations

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
    load_vllm: bool = False,
    load_trt: bool = False,
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
    ``{duree: ..., blocs: [...]}`` (utile au GUI serveur).
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
    for i, (pers, voix_nom, voice, t, block_chars, block_speed) in enumerate(sous_blocs, 1):
        audio = _synthesize_for(t, model, sr, voice, block_chars, block_speed, verify)
        # Pause uniquement au changement de personnage : les sous-blocs d'un même
        # locuteur s'enchaînent sans coupure dans le montage final.
        if pers_precedent is not None and pers != pers_precedent:
            parts.append(np.zeros(pause_n, dtype=np.float32))
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

    final = np.concatenate(parts)
    res = {
        "audio": final,
        "sample_rate": sr,
        "duration": round(len(final) / sr, 2),
        "blocs": blocs_report,
        "out": out,
    }
    if out:
        cosyvoice_engine.save(final, sr, out)
        if verbose:
            print(f"\nEnregistré : {out} ({res['duration']} s)")
    if progress:
        progress({"duree": res["duration"], "blocs": len(blocs_report)})
    return res