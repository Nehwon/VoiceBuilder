"""Wrapper sur le moteur CosyVoice3 (clonage zéro-shot wav + txt)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import config


def setup_cosyvoice_paths() -> None:
    """Rend importables les paquets ``cosyvoice`` et ``matcha`` du repo voisin."""
    if str(config.MATCHA_TTS_DIR) not in sys.path:
        sys.path.append(str(config.MATCHA_TTS_DIR))
    if str(config.COSYVOICE_ROOT) not in sys.path:
        sys.path.append(str(config.COSYVOICE_ROOT))


# Module cache
_model = None
_sr = None


def load(model_dir=None, device: str = None, fp16: bool = None) -> "tuple":
    """Charge (une fois) le modèle CosyVoice3 et renvoie (engine, sample_rate)."""
    global _model, _sr
    if _model is not None:
        return _model, _sr

    setup_cosyvoice_paths()
    device = device or config.DEFAULT_DEVICE
    fp16 = config.DEFAULT_FP16 if fp16 is None else fp16
    model_dir = Path(model_dir) if model_dir else config.COSYVOICE_MODEL_DIR

    from cosyvoice.cli.cosyvoice import AutoModel

    _model = AutoModel(model_dir=str(model_dir), fp16=fp16)
    _sr = _model.sample_rate
    return _model, _sr


def synthesize(
    text: str,
    prompt_wav: str,
    prompt_text: str,
    model: Optional[object] = None,
    sample_rate: Optional[int] = None,
    speed: float = config.DEFAULT_SPEED,
    stream: bool = False,
) -> np.ndarray:
    """Génère le TTS de ``text`` en clonant ``prompt_wav/prompt_text``.

    Renvoie un array mono float32 à ``sample_rate`` Hz.
    """
    if model is None or sample_rate is None:
        model, sample_rate = load()

    chunks = []
    for out in model.inference_zero_shot(
        text, prompt_text, prompt_wav, stream=stream, speed=speed
    ):
        chunks.append(np.asarray(out["tts_speech"].cpu().numpy(), dtype=np.float32).squeeze())
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def save(audio: np.ndarray, sample_rate: int, path: str) -> None:
    sf.write(path, audio, sample_rate)