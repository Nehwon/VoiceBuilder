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


def transcribe(audio: np.ndarray, sample_rate: int, lang: str | None = None) -> str:
    """Transcrit un audio mono float32 (rééchantillonné à 16 kHz pour whisper).

    ``lang`` surcharge la langue par défaut (``config.WHISPER_LANG``).
    """
    y = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000).astype(np.float32)
    model = _load_model()
    return model.transcribe(y, language=lang or config.WHISPER_LANG, fp16=False)["text"]


def _estamp(t: float) -> str:
    """Formate une durée en ``MM:SS.centièmes`` pour ``[0000.00 - 0005.28]``."""
    m, s = divmod(int(t), 60)
    cs = int((t - int(t)) * 100)
    return f"{m:02d}{s:02d}.{cs:02d}"


def transcribe_timestamped(
    audio: np.ndarray, sample_rate: int, lang: str | None = None
) -> str:
    """Transcription par segments, chaque ligne préfixée ``[MMSS.cc - MMSS.cc] texte``.

    Le format horodaté reste ignoré au parsing de ``voix.py`` (``_strip_timestamps``).
    """
    y = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000).astype(np.float32)
    model = _load_model()
    res = model.transcribe(y, language=lang or config.WHISPER_LANG, fp16=False)
    lignes = []
    for seg in res["segments"]:
        lignes.append(
            f"[{_estamp(seg['start'])} - {_estamp(seg['end'])}] {seg['text'].strip()}"
        )
    return "\n".join(lignes)


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