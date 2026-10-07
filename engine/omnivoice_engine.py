"""Moteur OmniVoice (clonage zéro-shot wav + txt, 24 kHz natifs).

Contrat : ``load(device)`` renvoie ``(modele, 24000)`` (chargement unique),
``synthesize(...)`` renvoie un array mono float32. Branche omni : synthèse
directe en processus (transformers 5.x, image dédiée). Différences
assumées (V1) :

- pas de routage multilingue ``[en]`` : les marqueurs sont retirés et
  tout est normalisé en français (``text_fr.normalize``) ;
- pas de ``speed`` natif : une vitesse ≠ 1.0 est appliquée par
  étirement temporel (``librosa``) après synthèse ;
- pas de pré-cache de prompt (le modèle est déjà ~7× plus rapide).

Branche omni : pas de CosyVoice ici, donc pas de conflit transformers.
"""
from __future__ import annotations

import re
import threading
from typing import Optional

import numpy as np
import soundfile as sf

from . import bgm
from . import config
from . import text_fr

# Marqueurs de langue inline (cf. text_fr.normalize_multilangue) : OmniVoice
# ne les consomme pas, on les retire avant synthèse (tout en français, V1).
_LANGUES_RE = re.compile(r"\[/?(?:en|fr)\]", re.IGNORECASE)

#: Fréquence native du modèle (imposée, cf. bench M19).
NATIVE_SR = 24000

# Modèle chargé une fois (singleton).
_model = None
_load_lock = threading.Lock()


def load(device: str = None) -> "tuple":
    """Charge (une fois) le modèle OmniVoice et renvoie (modele, 24000)."""
    global _model
    if _model is not None:
        return _model, NATIVE_SR
    with _load_lock:
        if _model is not None:
            return _model, NATIVE_SR
        device = device or config.DEFAULT_DEVICE
        from omnivoice import OmniVoice

        import torch

        _model = OmniVoice.from_pretrained(
            str(config.OMNIVOICE_MODEL_DIR),
            device_map=device,
            dtype=torch.float16,
        )
    return _model, NATIVE_SR


def _preparer(text: str, prompt_text: str) -> tuple:
    """Normalisation FR + BGM (commune aux deux modes)."""
    text, veut_bgm = bgm.preparer_texte(text)
    prompt_text = bgm.preparer_texte(prompt_text)[0]
    text = text_fr.normalize(_LANGUES_RE.sub("", text))
    prompt_text = text_fr.normalize(_LANGUES_RE.sub("", prompt_text))
    return text, prompt_text, veut_bgm


def _post_traiter(audio: np.ndarray, speed: float, veut_bgm: bool,
                  sr_cible: int) -> np.ndarray:
    if speed and speed != 1.0:
        import librosa

        audio = np.asarray(librosa.effects.time_stretch(audio, rate=speed),
                           dtype=np.float32)
    if sr_cible != NATIVE_SR:
        import librosa

        audio = np.asarray(
            librosa.resample(audio, orig_sr=NATIVE_SR, target_sr=sr_cible),
            dtype=np.float32,
        )
    if veut_bgm:
        audio = bgm.appliquer(audio, sr_cible)
    return audio


def synthesize(
    text: str,
    prompt_wav: str,
    prompt_text: str,
    model: Optional[object] = None,
    sample_rate: Optional[int] = None,
    speed: float = config.DEFAULT_SPEED,
    stream: bool = False,
    out_sr: Optional[int] = None,
) -> np.ndarray:
    """Génère le TTS de ``text`` en clonant ``prompt_wav/prompt_text``.

    ``prompt_text`` = transcription **brute**. Renvoie un array mono
    float32 à ``out_sr`` Hz (``sample_rate`` du montage par défaut,
    rééchantillonné depuis les 24 kHz natifs si différent).
    """
    if model is None:
        model, _ = load()
    text, prompt_text, veut_bgm = _preparer(text, prompt_text)
    sr_cible = out_sr or sample_rate or NATIVE_SR

    audio = model.generate(text=text, ref_audio=str(prompt_wav),
                           ref_text=prompt_text)
    if isinstance(audio, (list, tuple)):
        audio = audio[0]
    if hasattr(audio, "cpu"):
        audio = audio.cpu().numpy()
    audio = np.asarray(audio, dtype=np.float32).squeeze()
    return _post_traiter(audio, speed, veut_bgm, sr_cible)


def save(audio: np.ndarray, sample_rate: int, path: str) -> None:
    sf.write(path, audio, sample_rate)

