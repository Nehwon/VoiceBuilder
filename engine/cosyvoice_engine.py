"""Wrapper sur le moteur CosyVoice3 (clonage zéro-shot wav + txt)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import bgm
from . import config
from . import text_fr


def setup_cosyvoice_paths() -> None:
    """Rend importables les paquets ``cosyvoice`` et ``matcha`` du repo voisin."""
    if str(config.MATCHA_TTS_DIR) not in sys.path:
        sys.path.append(str(config.MATCHA_TTS_DIR))
    if str(config.COSYVOICE_ROOT) not in sys.path:
        sys.path.append(str(config.COSYVOICE_ROOT))


# Module cache
_model = None
_sr = None
_load_lock = threading.Lock()

# Pré-cache des prompts (M18-backlog) : les tenseurs dérivés du couple
# (wav + txt) — tokens texte, speech tokens, mel, embedding — sont identiques
# pour tous les blocs d'une même voix. On les calcule une fois via le
# mécanisme natif ``frontend.spk2info`` au lieu de les refaire à chaque bloc.
_CLES_PROMPT = ("prompt_text", "prompt_text_len",
                "llm_prompt_speech_token", "llm_prompt_speech_token_len",
                "flow_prompt_speech_token", "flow_prompt_speech_token_len",
                "prompt_speech_feat", "prompt_speech_feat_len",
                "llm_embedding", "flow_embedding")
_CACHE_PROMPTS: dict = {}
_CACHE_PROMPTS_MAX = 64


def vider_cache_prompts() -> None:
    """Vide le pré-cache des prompts (tests, changement de modèle)."""
    _CACHE_PROMPTS.clear()


def _id_prompt_cache(model, prompt_wav: str, prompt_text: str,
                     sample_rate: int) -> str:
    """Id ``spk2info`` du prompt, calculé une fois puis réutilisé.

    Clé = (wav, mtime, texte, sr) : un prompt réécrit (nettoyage, nouvel
    import) est re-calculé automatiquement. Best effort : en cas d'échec on
    renvoie "" (comportement historique, sans cache).
    """
    try:
        mtime = Path(prompt_wav).stat().st_mtime_ns
    except OSError:
        mtime = 0
    cle = (str(prompt_wav), mtime, prompt_text, sample_rate)
    sid = _CACHE_PROMPTS.get(cle)
    if sid is not None and sid in model.frontend.spk2info:
        return sid
    try:
        d = model.frontend.frontend_zero_shot(
            "", prompt_text, str(prompt_wav), sample_rate, "")
    except Exception:  # noqa: BLE001
        return ""
    sid = f"vb-prompt-{len(_CACHE_PROMPTS)}"
    model.frontend.spk2info[sid] = {k: d[k] for k in _CLES_PROMPT}
    if len(_CACHE_PROMPTS) >= _CACHE_PROMPTS_MAX:
        _CACHE_PROMPTS.clear()
    _CACHE_PROMPTS[cle] = sid
    return sid


def load(model_dir=None, device: str = None, fp16: bool = None,
         load_vllm: bool = False, load_trt: bool = False) -> "tuple":
    """Charge (une fois) le modèle CosyVoice3 et renvoie (engine, sample_rate).

    ``load_vllm`` / ``load_trt`` activent respectivement l'accélération vLLM
    (LLM) et TensorRT (Flow/DiT) si les paquets sont installés.
    """
    global _model, _sr
    if _model is not None:
        return _model, _sr

    # Verrou : deux générations simultanées pourraient déclencher deux
    # constructions d'AutoModel en même temps (course sur _model -> erreurs
    # type "Cannot copy out of meta tensor").
    with _load_lock:
        if _model is not None:
            return _model, _sr
        setup_cosyvoice_paths()
        device = device or config.DEFAULT_DEVICE
        fp16 = config.DEFAULT_FP16 if fp16 is None else fp16
        model_dir = Path(model_dir) if model_dir else config.COSYVOICE_MODEL_DIR

        from cosyvoice.cli.cosyvoice import AutoModel

        _model = AutoModel(model_dir=str(model_dir), fp16=fp16,
                           load_vllm=load_vllm, load_trt=load_trt)
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

    # Marqueurs BGM : retirés AVANT CosyVoice (sinon vocalisés — le zero-shot
    # ne génère pas de musique), le lit est mixé après synthèse.
    text, veut_bgm = bgm.preparer_texte(text)
    prompt_text = bgm.preparer_texte(prompt_text)[0]

    # CosyVoice lit les chiffres en anglais (inflect) : on normalise les
    # nombres en français avant la synthèse (cf. engine/text_fr.py).
    text = text_fr.normalize(text)
    prompt_text = text_fr.normalize(prompt_text)

    # Prompt pré-calculé une fois par voix (sinon tokens/embedding refaits
    # à chaque bloc). "" = repli historique.
    sid = _id_prompt_cache(model, prompt_wav, prompt_text, sample_rate)

    chunks = []
    for out in model.inference_zero_shot(
        text, prompt_text, prompt_wav, zero_shot_spk_id=sid,
        stream=stream, speed=speed
    ):
        chunks.append(np.asarray(out["tts_speech"].cpu().numpy(), dtype=np.float32).squeeze())
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    if veut_bgm:
        audio = bgm.appliquer(audio, sample_rate)
    return audio


def save(audio: np.ndarray, sample_rate: int, path: str) -> None:
    sf.write(path, audio, sample_rate)