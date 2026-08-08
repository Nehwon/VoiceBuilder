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


def generate(
    texte_path: str,
    voices: Voices,
    out: Optional[str] = None,
    max_block_chars: Optional[int] = None,
    pause: Optional[float] = None,
    speed: Optional[float] = None,
    verify: Optional[bool] = None,
    device: Optional[str] = None,
    fp16: Optional[bool] = None,
    verbose: bool = True,
) -> dict:
    """Génère l'audio complet pour un texte taggé et une liste de voix.

    ``out`` : chemin WAV écrit. Renvoie un dict avec ``audio``, ``sample_rate``,
    ``duration``, ``blocs`` et ``out``.
    """
    if verbose:
        print(f"Voix disponibles : {voices.names()}")

    segments = parse_texte(_read_text(texte_path), voices.names())
    blocs = regrouper(segments)
    inconnus = {pers for pers, _ in blocs if pers not in voices}
    if inconnus:
        raise ValueError(f"Personnage(s) sans voix définie : {inconnus}")

    model, sr = cosyvoice_engine.load(device=device, fp16=fp16)
    max_chars = config.DEFAULT_MAX_BLOCK_CHARS if max_block_chars is None else max_block_chars
    pause = config.DEFAULT_PAUSE if pause is None else pause
    if verify is None:
        verify = config.VERIFY_ENABLED
    pause_n = int(pause * sr)

    parts: List[np.ndarray] = []
    blocs_report: List[Tuple[str, int, float]] = []
    total = len(blocs)
    for i, (pers, block) in enumerate(blocs, 1):
        voice = voices.get(pers)
        block_chars = voice.max_block_chars or max_chars
        block_speed = voice.speed if voice.speed is not None else (speed or config.DEFAULT_SPEED)

        audio = _synthesize_for(block, model, sr, voice, block_chars, block_speed, verify)
        parts.append(audio)
        dur = len(audio) / sr
        blocs_report.append((pers, len(block), round(dur, 2)))
        if verbose:
            print(f"[{i}/{total}] {pers} ({len(block)} chars) -> {dur:.2f} s")
        parts.append(np.zeros(pause_n, dtype=np.float32))

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
    return res