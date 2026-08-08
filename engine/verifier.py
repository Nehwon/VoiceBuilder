"""Vérification par transcription (Whisper) : détecte les contenus non rendus."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import librosa
import numpy as np

from . import config


def normalize(s: str) -> str:
    """Minuscules, ponctuation et accents retirés (normalisation pour comparaison)."""
    s = re.sub(r"[^\w\s]", "", s).lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=1)
def _load_model():
    import whisper
    return whisper.load_model(config.WHISPER_MODEL, device="cuda")


def transcribe(audio: np.ndarray, sample_rate: int) -> str:
    """Transcrit un audio mono float32 (rééchantillonné à 16 kHz pour whisper)."""
    y = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000).astype(np.float32)
    model = _load_model()
    return model.transcribe(y, language=config.WHISPER_LANG, fp16=False)["text"]


def coverage(text: str, audio: np.ndarray, sample_rate: int) -> float:
    """Fraction des mots uniques attendus retrouvés dans la transcription.

    ``1.0`` = contenu intégralement rendu ; plus bas = du texte perdu.
    """
    if audio.shape[0] < sample_rate * 0.5:
        return 0.0
    transcript = transcribe(audio, sample_rate)
    tn = normalize(transcript)
    words = list(dict.fromkeys(normalize(text).split()))
    if not words:
        return 0.0
    return sum(1 for w in words if w in tn) / len(words)


def verify_text(text: str, audio: np.ndarray, sample_rate: int) -> bool:
    """True si l'audio rend fidèlement ``text`` (couverture >= seuil)."""
    return coverage(text, audio, sample_rate) >= config.VERIFY_THRESHOLD