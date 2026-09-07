"""Extraction audio depuis vidéo, données waveform et découpage de segment.

Fournit les briques backend pour l'onglet « Voix » (M13) :
  - ``extraire_audio``  : piste son depuis une vidéo (ffmpeg)
  - ``waveform_data``   : pics d'amplitude pour rendu graphique
  - ``decouper_segment``: extrait un segment [start, stop] en WAV
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# 1. Extraction audio depuis vidéo (ffmpeg)
# ---------------------------------------------------------------------------

def extraire_audio(video_path: str, out_wav: str, sr: int = 24000) -> dict:
    """Extrait la piste son d'une vidéo et la convertit en WAV mono.

    Retourne ``{"wav": str, "duree": float, "sr": int}``.
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn",                      # pas de vidéo
        "-acodec", "pcm_s16le",     # 16-bit PCM
        "-ar", str(sr),             # fréquence d'échantillonnage
        "-ac", "1",                 # mono
        str(out_wav),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg a échoué :\n{result.stderr[-500:]}")

    duree = _duree_wav(out_wav)
    return {"wav": out_wav, "duree": round(duree, 3), "sr": sr}


def _duree_wav(path: str) -> float:
    """Renvoie la durée (secondes) d'un fichier WAV via soundfile."""
    import soundfile as sf
    info = sf.info(path)
    return info.duration


# ---------------------------------------------------------------------------
# 2. Données waveform (pics d'amplitude pour rendu JS)
# ---------------------------------------------------------------------------

def waveform_data(wav_path: str, num_points: int = 2000) -> list[list[float]]:
    """Renvoie les pics d'amplitude pour le rendu waveform.

    Retourne une liste de ``[min, max]`` pour chaque point, normalisée
    dans [-1, 1].  ``num_points`` contrôle la résolution horizontale.
    """
    import soundfile as sf
    data, sr = sf.read(wav_path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)

    total = len(data)
    if total == 0:
        return [[0.0, 0.0]] * num_points

    chunk = max(1, total // num_points)
    peaks: list[list[float]] = []
    for i in range(0, total, chunk):
        segment = data[i : i + chunk]
        peaks.append([float(segment.min()), float(segment.max())])
    return peaks


# ---------------------------------------------------------------------------
# 3. Découpage d'un segment
# ---------------------------------------------------------------------------

def decouper_segment(
    src: str, start: float, stop: float, out: str | None = None,
) -> dict:
    """Découpe ``[start, stop]`` d'un fichier audio → WAV mono float32.

    Renvoie ``{"wav": str, "duree": float, "sr": int}``.
    """
    import soundfile as sf

    data, sr = sf.read(src, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)

    i0, i1 = int(start * sr), int(stop * sr)
    if i0 < 0 or i1 > len(data) or i0 >= i1:
        raise ValueError(
            f"Segment [{start}..{stop}] hors bornes "
            f"(durée = {len(data)/sr:.1f} s)"
        )

    segment = data[i0:i1]
    if out is None:
        out = tempfile.mktemp(suffix=".wav", prefix="vb_seg_")
    sf.write(out, segment, sr)
    return {"wav": out, "duree": round(len(segment) / sr, 3), "sr": sr}
