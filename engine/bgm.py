"""Musique de fond (BGM) : CosyVoice zero-shot ne sait pas générer de lit
musical depuis ``<|BGM|>`` (label d'annotation, pas contrôle de génération) —
on le mixe donc nous-mêmes.

Protocole : ``<|BGM|>texte<|/BGM|>`` dans l'éditeur → le texte est synthétisé
SANS les marqueurs (retirés avant CosyVoice, sinon ils seraient vocalisés),
puis le lit musical (fichier configuré dans ⚙️ Réglages) est bouclé sous
l'audio au volume choisi, avec fondus d'entrée/sortie. Sans lit configuré :
texte parlé normalement (marqueurs retirés).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import config

OUVRE = "<|BGM|>"
FERME = "<|/BGM|>"
_RE_OUVRE = re.compile(r"<\|BGM\|>")
_RE_FERME = re.compile(r"<\|/BGM\|>")

FONDU_S = 0.5  # fondu d'entrée/sortie du lit (s) pour éviter les clics


def preparer_texte(texte: str) -> tuple[str, bool]:
    """Retire les marqueurs BGM (sinon vocalisés) ; dit si un lit est demandé."""
    veut = bool(_RE_OUVRE.search(texte) or _RE_FERME.search(texte))
    net = _RE_OUVRE.sub("", _RE_FERME.sub("", texte))
    return net, veut


def charger_lit(chemin: str | Path, sr_cible: int) -> np.ndarray | None:
    """Charge le lit musical en mono float32 à ``sr_cible`` (None si illisible)."""
    try:
        import soundfile as sf
        y, sr = sf.read(str(chemin), dtype="float32", always_2d=True)
        y = y.mean(axis=1).astype(np.float32)
        if sr != sr_cible:
            import librosa
            y = librosa.resample(y, orig_sr=sr, target_sr=sr_cible).astype(np.float32)
        y = y - np.mean(y)  # recentré (pas de décalage continu)
        crete = np.max(np.abs(y))
        if crete > 0:
            y = (y / crete).astype(np.float32)  # normalisé : le volume fait le reste
        return y
    except Exception:  # noqa: BLE001
        return None


def mixer(audio: np.ndarray, sr: int, lit: np.ndarray, volume: float) -> np.ndarray:
    """Boucle le lit sous ``audio`` au volume donné + fondus aux bords."""
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) == 0 or len(lit) == 0 or volume <= 0:
        return audio
    n = len(audio)
    reps = n // len(lit) + 1
    bed = np.tile(lit, reps)[:n].astype(np.float32)
    # enveloppe : montée/descente linéaires (anti-clics aux raccords)
    nf = min(int(FONDU_S * sr), n // 2)
    if nf > 0:
        rampe = np.linspace(0.0, 1.0, nf, dtype=np.float32)
        bed[:nf] *= rampe
        bed[n - nf:] *= rampe[::-1]
    mix = audio + bed * float(volume)
    return np.clip(mix, -1.0, 1.0).astype(np.float32)


def appliquer(audio: np.ndarray, sr: int) -> np.ndarray:
    """Mixeur appelé après synthèse si ``preparer_texte`` a demandé un lit.

    Sans lit configuré (ou illisible) : audio inchangé.
    """
    lit_path = config.BGM_LIT
    if not lit_path:
        return audio
    lit = charger_lit(lit_path, sr)
    if lit is None:
        return audio
    return mixer(audio, sr, lit, config.BGM_VOLUME)
