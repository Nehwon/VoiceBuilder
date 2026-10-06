"""Pipeline multi-voix : parse -> regrouper -> blocs adaptatifs vérifiés -> montage."""
from __future__ import annotations

import queue
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from . import adaptive, config, cosyvoice_engine, omnivoice_engine, verifier
from .tagging import PAUSE, parse_texte, regrouper
from .voix import Voices, base_nom, grouper_candidats

PAUSE_LABEL = "⏸ Pause"


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _synthesize_for(
    text: str, moteurs: dict, sr_montage, voice, block_chars, speed, verify,
    should_stop=None,
) -> np.ndarray:
    """Synthetise un bloc pour une voix donnée (avec découpage adaptatif vérifié).

    ``moteurs`` : ``{nom_moteur: (modele, sample_rate)}``. Le moteur vient de
    ``voice.moteur`` (M19.1) ; un moteur manquant est chargé à la volée
    (repli, paramètres par défaut). Chaque bloc sort au ``sr_montage``
    (rééchantillonné si besoin) pour un montage homogène.
    """
    moteur = voice.moteur or config.MOTEUR_DEFAUT
    if moteur not in moteurs:
        if moteur == "omnivoice":
            moteurs[moteur] = omnivoice_engine.load()
        else:
            moteurs[moteur] = cosyvoice_engine.load()
    model, sr = moteurs[moteur]
    if moteur == "omnivoice":
        prompt = voice.prompt_text
        def synth(t: str, _pw="", _pt=""):
            return omnivoice_engine.synthesize(
                t, str(voice.wav), voice.prompt_text,
                model, sr, speed=speed, out_sr=sr_montage)
    else:
        prompt = voice.system_prompt
        def synth(t: str, _pw="", _pt=""):
            return cosyvoice_engine.synthesize(t, str(voice.wav), voice.system_prompt,
                                              model, sr, speed=speed)
    audio = adaptive.synthesize_verified(
        text, str(voice.wav), prompt, synth, sr_montage,
        max_chars=block_chars, verify=verify, should_stop=should_stop,
    )
    if sr != sr_montage and moteur != "omnivoice":
        import librosa
        audio = np.asarray(
            librosa.resample(audio, orig_sr=sr, target_sr=sr_montage),
            dtype=np.float32)
    return audio


def silence(duree: float, sample_rate: int) -> np.ndarray:
    """Génère un silence de ``duree`` secondes (bloc de pause explicite)."""
    return np.zeros(max(1, int(duree * sample_rate)), dtype=np.float32)


def load(device: Optional[str] = None, fp16: Optional[bool] = None,
         load_vllm: bool = False, load_trt: bool = False):
    """Ré-export du chargement (une seule fois) du modèle CosyVoice3."""
    return cosyvoice_engine.load(device=device, fp16=fp16,
                                 load_vllm=load_vllm, load_trt=load_trt)


def load_omnivoice(device: Optional[str] = None):
    """Ré-export du chargement (une fois) du modèle OmniVoice (M19.1)."""
    return omnivoice_engine.load(device=device)


def synth_bloc(
    voice, text: str, model, sample_rate, block_chars=None, speed=None, verify=None,
) -> np.ndarray:
    """Synthetise un seul bloc pour une voix (réutilisable pour la régénération).

    Le moteur vient de ``voice.moteur`` (M19.1) : ``model``/``sample_rate``
    (montage en cours, généralement CosyVoice) ne servent qu'au cas CosyVoice
    et comme fréquence cible du montage ; un bloc OmniVoice est synthétisé
    via le modèle OmniVoice (chargé une fois) puis rééchantillonné.
    """
    block_chars = voice.max_block_chars or block_chars or config.DEFAULT_MAX_BLOCK_CHARS
    spd = voice.speed if voice.speed is not None else (speed or config.DEFAULT_SPEED)
    chk = config.VERIFY_ENABLED if verify is None else verify
    moteur = voice.moteur or config.MOTEUR_DEFAUT
    if moteur == "omnivoice":
        omodel, _ = omnivoice_engine.load()
        def synth(t: str, _pw="", _pt=""):
            return omnivoice_engine.synthesize(
                t, str(voice.wav), voice.prompt_text,
                omodel, None, speed=spd, out_sr=sample_rate)
        return adaptive.synthesize_verified(
            text, str(voice.wav), voice.prompt_text, synth, sample_rate,
            max_chars=block_chars, verify=chk,
        )
    return _synthesize_for(text, {"cosyvoice": (model, sample_rate)},
                           sample_rate, voice, block_chars, spd, chk)


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
    multi_prompt: bool = False,
    max_prompts: int = 2,
) -> dict:
    """Génère l'audio complet pour un texte taggé et une liste de voix.

    Les balises du texte sont des **noms de personnages**. ``personnages`` est un
    mapping ``{personnage: nom_de_voix}``. S'il est absent, on suppose que chaque
    personnage porte le même nom qu'une voix (mapping identité, comportement
    historique de l'outil).

    Lignes ``[pause: Ns]`` (voir ``engine/tagging.py``) et sauts de paragraphe
    (ligne vide) : insèrent un silence dans le montage, sans appel TTS. Elles
    ne requièrent aucune voix ; les blocs correspondants portent
    ``personnage = "⏸ Pause"`` et ``pause = <durée en s>``.

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

    ``multi_prompt`` : si True, chaque bloc est synthétisé avec jusqu'à
    ``max_prompts`` segments candidats de la voix (variantes ``_2``/``_3``,
    ``_clean`` partageant la même base, M17.4) et le meilleur est gardé
    (``coverage`` Whisper maximal, égalité → voix de référence). Repli sur
    le prompt unique si 1 seul candidat. Coût ×N GPU — utile sur les voix
    faibles en attendant un fine-tune.
    """
    if verbose:
        print(f"Voix disponibles : {voices.names()}")

    if personnages is None:
        personnages = {n: n for n in voices.names()}

    segments = parse_texte(_read_text(texte_path), list(personnages))
    blocs = regrouper(segments)
    inconnus = {pers for pers, _ in blocs if pers not in personnages and pers != PAUSE}
    if inconnus:
        raise ValueError(f"Personnage(s) sans voix définie : {inconnus}")

    # Modèles chargés plus bas, selon les moteurs requis (M19.1).
    max_chars = config.DEFAULT_MAX_BLOCK_CHARS if max_block_chars is None else max_block_chars
    pause = config.DEFAULT_PAUSE if pause is None else pause
    if verify is None:
        verify = config.VERIFY_ENABLED

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
        if pers == PAUSE:
            # Bloc de silence : aucun TTS. Le slot ``block_chars`` porte la durée.
            duree_pause = float(block)
            texte_pause = f"[pause: {duree_pause:g}s]"
            sous_blocs.append((PAUSE, "—", None, texte_pause, duree_pause, 0.0))
            continue
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

    def arret_demande() -> bool:
        """Vrai si l'arrêt est demandé : la synthèse en cours finit vite
        (vérif et re-splits sautés) puis la boucle abandonne."""
        return stop_event is not None and stop_event.is_set()

    groupes_prompts = grouper_candidats(voices.names()) if multi_prompt else {}

    # Moteurs requis par les voix des sous-blocs (M19.1) : on ne charge que
    # l'utile (VRAM partagée). En multi-prompt, les candidats peuvent relever
    # d'un autre moteur que la voix du bloc : on les inclut. Le sr du montage
    # est celui de CosyVoice dès qu'il est requis (comportement historique),
    # sinon les 24 kHz natifs d'OmniVoice.
    moteurs_requis = set()
    for _, _, _voice, _, _, _ in sous_blocs:
        if _voice is None:
            continue
        moteurs_requis.add(_voice.moteur or config.MOTEUR_DEFAUT)
        if multi_prompt:
            for _nom in groupes_prompts.get(base_nom(_voice.name), [_voice.name]):
                if _nom in voices:
                    moteurs_requis.add(voices.get(_nom).moteur or config.MOTEUR_DEFAUT)
    moteurs: dict = {}
    if "cosyvoice" in moteurs_requis:
        moteurs["cosyvoice"] = cosyvoice_engine.load(
            device=device, fp16=fp16, load_vllm=load_vllm, load_trt=load_trt)
    if "omnivoice" in moteurs_requis:
        moteurs["omnivoice"] = omnivoice_engine.load(device=device)
    sr = moteurs["cosyvoice"][1] if "cosyvoice" in moteurs else moteurs["omnivoice"][1]
    pause_n = int(pause * sr)

    def _synth_choisir(t, voice, block_chars, block_speed):
        """Synthétise un bloc, en multi-prompt avec chaque candidat si activé.

        Renvoie ``(audio, prompt_gagnant | None, couverture | None)``.
        """
        if not multi_prompt:
            return (_synthesize_for(t, moteurs, sr, voice, block_chars, block_speed,
                                    verify, arret_demande), None, None)
        noms = groupes_prompts.get(base_nom(voice.name), [voice.name])
        noms = [n for n in noms if n in voices][:max(1, max_prompts)]
        if len(noms) < 2:
            return (_synthesize_for(t, moteurs, sr, voice, block_chars, block_speed,
                                    verify, arret_demande), None, None)
        meilleur, couv_max, gagnant = None, -1.0, noms[0]
        for nom in noms:
            cand = voices.get(nom)
            bc = cand.max_block_chars or block_chars
            spd = cand.speed if cand.speed is not None else block_speed
            audio = _synthesize_for(t, moteurs, sr, cand, bc, spd, False,
                                    arret_demande)
            couv = verifier.coverage(t, audio, sr)
            if verbose:
                print(f"  [prompt {nom}] couverture {couv:.0%}")
            if couv > couv_max:
                meilleur, couv_max, gagnant = audio, couv, nom
        if verbose:
            print(f"  [prompt gagnant] {gagnant} (couverture {couv_max:.0%})")
        return meilleur, gagnant, round(couv_max, 4)

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
            if pers == PAUSE:
                # Bloc de silence : on régénère le silence (même durée).
                duree_pause = float(block_chars)
                parts[positions[bid - 1]] = silence(duree_pause, sr)
                blocs_report[bid - 1]["duree"] = round(duree_pause, 2)
                wav_regen = None
                if block_dir:
                    wav_regen = str(block_dir / f"bloc_{bid}.wav")
                    cosyvoice_engine.save(parts[positions[bid - 1]], sr, wav_regen)
                if verbose:
                    print(f"[regen {bid}/{total}] {PAUSE_LABEL} ({duree_pause:g} s de silence)")
                if progress:
                    progress({"id": bid, "index": bid, "total": total,
                              "personnage": PAUSE_LABEL,
                              "voix": "—", "texte": t,
                              "chars": len(t), "duree": round(duree_pause, 2),
                              "wav": wav_regen, "regen": True})
                continue
            if multi_prompt:
                audio, prompt, couv = _synth_choisir(t, voice, block_chars, block_speed)
                if prompt != voix_nom:
                    blocs_report[bid - 1]["prompt"] = prompt
                if couv is not None:
                    blocs_report[bid - 1]["couverture"] = couv
            else:
                audio = _synthesize_for(t, moteurs, sr, voice, block_chars, block_speed,
                                        verify, arret_demande)
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
        if pers == PAUSE:
            # Bloc de silence : aucun TTS, aucune pause inter-blocs ajoutée.
            duree_pause = float(block_chars)
            audio = silence(duree_pause, sr)
            positions.append(len(parts))
            parts.append(audio)
            pers_precedent = pers
            dur = duree_pause
            info = {
                "id": i, "personnage": PAUSE_LABEL, "voix": "—", "texte": t,
                "chars": len(t), "duree": round(dur, 2), "pause": duree_pause,
            }
            if block_dir:
                wav = block_dir / f"bloc_{i}.wav"
                cosyvoice_engine.save(audio, sr, str(wav))
                info["wav"] = str(wav)
            blocs_report.append(info)
            if verbose:
                print(f"[{i}/{total}] {PAUSE_LABEL} ({duree_pause:g} s de silence)")
            if progress:
                progress({"id": i, "index": i, "total": total,
                          "personnage": PAUSE_LABEL,
                          "voix": "—", "texte": t,
                          "chars": len(t), "duree": round(dur, 2),
                          "pause": duree_pause,
                          "wav": info.get("wav")})
            _drain_regen()
            continue
        # Pause uniquement au changement de personnage : les sous-blocs d'un même
        # locuteur s'enchaînent sans coupure dans le montage final. Pas de pause
        # standard autour d'un silence explicite (paragraphe, [pause: Ns]).
        if (pers_precedent is not None and pers != pers_precedent
                and pers_precedent != PAUSE):
            parts.append(np.zeros(pause_n, dtype=np.float32))
        positions.append(len(parts))
        if multi_prompt:
            audio, prompt, couv = _synth_choisir(t, voice, block_chars, block_speed)
        else:
            audio = _synthesize_for(t, moteurs, sr, voice, block_chars, block_speed,
                                    verify, arret_demande)
            prompt, couv = None, None
        parts.append(audio)
        pers_precedent = pers
        dur = len(audio) / sr
        info = {
            "id": i, "personnage": pers, "voix": voix_nom, "texte": t,
            "chars": len(t), "duree": round(dur, 2),
        }
        if prompt is not None and prompt != voix_nom:
            info["prompt"] = prompt
        if couv is not None:
            info["couverture"] = couv
        if block_dir:
            wav = block_dir / f"bloc_{i}.wav"
            cosyvoice_engine.save(audio, sr, str(wav))
            info["wav"] = str(wav)
        blocs_report.append(info)
        if verbose:
            print(f"[{i}/{total}] {pers} ({len(t)} chars) -> {dur:.2f} s")
        if progress:
            evt = {"id": i, "index": i, "total": total, "personnage": pers,
                   "voix": voix_nom, "texte": t,
                   "chars": len(t), "duree": round(dur, 2),
                   "wav": info.get("wav")}
            if prompt is not None and prompt != voix_nom:
                evt["prompt"] = prompt
            if couv is not None:
                evt["couverture"] = couv
            progress(evt)
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