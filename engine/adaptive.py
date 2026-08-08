"""Synthèse d'un paragraphe en blocs adaptatifs vérifiés.

Reprend la logique validée expérimentalement : on groupe les phrases en blocs aussi
longs que possible (max ``max_chars``) et, après synthèse, on vérifie par
transcription (Whisper) ; si du contenu manque, le bloc est resplitté en deux et
régénéré récursivement jusqu'à ce que le contenu soit complet (ou trop petit).
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional

import numpy as np

from . import config
from .verifier import verify_text

# (texte, prompt_wav, prompt_text) -> np.ndarray (float32, mono)
SynthesizeFn = Callable[[str, str, str], np.ndarray]


def split_sentences(text: str) -> List[str]:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return sents or [text]


def build_blocks(text: str, max_chars: Optional[int] = None) -> List[str]:
    """Regroupe les phrases en blocs de <= ``max_chars`` caractères."""
    max_chars = max_chars or config.DEFAULT_MAX_BLOCK_CHARS
    blocks: List[str] = []
    current = ""
    for s in split_sentences(text):
        if current and len(current) + len(s) > max_chars:
            blocks.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        blocks.append(current)
    return blocks or [text]


def _split_in_half(text: str) -> Optional[tuple[str, str]]:
    for m in re.finditer(r"[.;!?]", text):
        frac = m.end() / len(text)
        if 0.3 <= frac <= 0.7:
            a, b = text[: m.end()].strip(), text[m.end():].strip()
            if a and b and _word_count(a) >= 2 and _word_count(b) >= 2:
                return a, b
    mid = len(text) // 2
    a, b = text[:mid].strip(), text[mid:].strip()
    if a and b and _word_count(a) >= 2 and _word_count(b) >= 2:
        return a, b
    return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def generate_block(
    text: str,
    prompt_wav: str,
    prompt_text: str,
    synth: SynthesizeFn,
    sample_rate: int,
    verify: Optional[bool] = None,
) -> np.ndarray:
    """Génère ``text``, et le re-split récursivement s'il est incomplet."""
    if verify is None:
        verify = config.VERIFY_ENABLED

    audio = synth(text, prompt_wav, prompt_text)

    if not verify or _word_count(text) <= config.DEFAULT_MIN_BLOCK_WORDS:
        return audio

    if verify_text(text, audio, sample_rate):
        return audio

    halves = _split_in_half(text)
    if halves is None:
        return audio

    a = generate_block(halves[0], prompt_wav, prompt_text, synth, sample_rate, verify)
    b = generate_block(halves[1], prompt_wav, prompt_text, synth, sample_rate, verify)
    return np.concatenate([a, b])


def synthesize_verified(
    text: str,
    prompt_wav: str,
    prompt_text: str,
    synth: SynthesizeFn,
    sample_rate: int,
    max_chars: Optional[int] = None,
    verify: Optional[bool] = None,
) -> np.ndarray:
    """Découpe un paragraphe en blocs adaptatifs puis concatène les blocs générés."""
    max_chars = max_chars or config.DEFAULT_MAX_BLOCK_CHARS
    parts = [
        generate_block(b, prompt_wav, prompt_text, synth, sample_rate, verify)
        for b in build_blocks(text, max_chars)
    ]
    return np.concatenate(parts)