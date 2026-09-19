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
    lignes = []
    for seg in transcribe_segments(audio, sample_rate, lang):
        lignes.append(
            f"[{_estamp(seg['start'])} - {_estamp(seg['end'])}] {seg['text'].strip()}"
        )
    return "\n".join(lignes)


def transcribe_segments(
    audio: np.ndarray, sample_rate: int, lang: str | None = None
) -> list[dict]:
    """Transcription horodatée structurée : ``[{start, end, text}]`` (secondes)."""
    y = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000).astype(np.float32)
    model = _load_model()
    res = model.transcribe(y, language=lang or config.WHISPER_LANG, fp16=False)
    return [{"start": float(s["start"]), "end": float(s["end"]),
             "text": s["text"].strip()}
            for s in res.get("segments", []) if s["text"].strip()]


def couverture_bloc(texte_bloc: str, segments: list[dict],
                    debut: float, fin: float, marge: float = 1.0) -> dict:
    """Couverture d'un bloc dans la transcription du montage complet.

    On ne retient que les segments Whisper chevauchant la fenêtre du bloc
    (marges incluses : les frontières Whisper sont approximatives), puis
    fraction des mots uniques du bloc retrouvés + mots manquants.
    """
    fenetre = " ".join(
        s["text"] for s in segments
        if s["end"] >= debut - marge and s["start"] <= fin + marge)
    tn = normalize(fenetre)
    mots = list(dict.fromkeys(normalize(texte_bloc).split()))
    manquants = [w for w in mots if w not in tn]
    couverture = (len(mots) - len(manquants)) / len(mots) if mots else 0.0
    return {"couverture": round(couverture, 4), "manquants": manquants,
            "nb_mots": len(mots)}


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