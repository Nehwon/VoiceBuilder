"""Wrapper sur le moteur OmniVoice (clonage zéro-shot wav + txt, 24 kHz).

Même contrat que ``cosyvoice_engine`` : ``load(device)`` renvoie
``(modele, sample_rate)``, ``synthesize(...)`` renvoie un array mono
float32. Différences assumées (V1) :

- pas de routage multilingue ``[en]`` : les marqueurs sont retirés et
  tout est normalisé en français (``text_fr.normalize``) ;
- pas de ``speed`` natif : une vitesse ≠ 1.0 est appliquée par
  étirement temporel (``librosa``) après synthèse ;
- pas de pré-cache de prompt (le modèle est déjà ~7× plus rapide).

Deux modes (M19.1-bis) : OmniVoice exige ``transformers>=5.3`` qui casse
CosyVoice3 — les deux moteurs ne cohabitent pas dans un processus :

- **direct** : ``import omnivoice`` possible (image ``voicebuilder-omni``,
  venv bench) → synthèse en processus ;
- **worker HTTP** : sinon, délégation au worker ``app/worker_omni.py``
  (``OMNIVOICE_WORKER_URL``, ex. ``http://omni:8100``). La normalisation
  FR/BGM reste côté appelant ; le worker reçoit du prêt-à-synthétiser.
"""
from __future__ import annotations

import io
import os
import re
import threading
from pathlib import Path
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

#: URL du worker HTTP (image dédiée). Réglable via ``OMNIVOICE_WORKER_URL``.
WORKER_URL = os.environ.get("OMNIVOICE_WORKER_URL", "http://omni:8100")

# Module cache (même motif que cosyvoice_engine : chargement unique).
_model = None
_load_lock = threading.Lock()
_direct_ok: bool | None = None


def _direct_disponible() -> bool:
    """Vrai si ``omnivoice`` est importable ici (transformers 5.x)."""
    global _direct_ok
    if _direct_ok is None:
        try:
            import omnivoice  # noqa: F401
            _direct_ok = True
        except Exception:  # noqa: BLE001
            _direct_ok = False
    return _direct_ok


def load(device: str = None, worker_url: str = None) -> "tuple":
    """Charge (une fois) le modèle OmniVoice et renvoie (modele, 24000).

    En mode worker, ``modele`` est un descripteur ``{"worker_url": ...}``
    (aucun chargement local, le worker porte le modèle).
    """
    global _model
    if _direct_disponible():
        if _model is not None and not isinstance(_model, dict):
            return _model, NATIVE_SR
        with _load_lock:
            if _model is not None and not isinstance(_model, dict):
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
    url = worker_url or WORKER_URL
    _model = {"worker_url": url}
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


def _synthesize_worker(url: str, text: str, prompt_wav: str,
                       prompt_text: str, speed: float,
                       out_sr: int) -> np.ndarray:
    """Délègue la synthèse au worker HTTP (lève RuntimeError en échec)."""
    import json
    import urllib.request
    import urllib.error

    payload = {"text": text, "prompt_wav": prompt_wav,
               "prompt_text": prompt_text, "speed": speed, "out_sr": out_sr}
    req = urllib.request.Request(
        url.rstrip("/") + "/synthesize", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            data = r.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("detail", exc.reason)
        except Exception:  # noqa: BLE001
            detail = exc.reason
        raise RuntimeError(f"Worker OmniVoice ({url}) : {detail}")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Worker OmniVoice injoignable ({url}) : {exc}. "
                           "Vérifiez le service `omni` (image voicebuilder-omni).")
    y, sr = sf.read(io.BytesIO(data), dtype="float32")
    if getattr(y, "ndim", 1) > 1:
        y = y.mean(axis=1)
    return np.asarray(y, dtype=np.float32)


def synthesize(
    text: str,
    prompt_wav: str,
    prompt_text: str,
    model: Optional[object] = None,
    sample_rate: Optional[int] = None,
    speed: float = config.DEFAULT_SPEED,
    stream: bool = False,
    out_sr: Optional[int] = None,
    worker_url: str = None,
) -> np.ndarray:
    """Génère le TTS de ``text`` en clonant ``prompt_wav/prompt_text``.

    ``prompt_text`` = transcription **brute** (sans préfixe système
    CosyVoice). Renvoie un array mono float32 à ``out_sr`` Hz
    (``sample_rate`` du montage par défaut, rééchantillonné depuis les
    24 kHz natifs si différent).
    """
    if model is None:
        model, _ = load(worker_url=worker_url)
    text, prompt_text, veut_bgm = _preparer(text, prompt_text)
    sr_cible = out_sr or sample_rate or NATIVE_SR

    if isinstance(model, dict):
        # Mode worker : normalisation déjà faite ici, synthèse là-bas.
        return _synthesize_worker(model["worker_url"], text, str(prompt_wav),
                                  prompt_text, speed or 1.0, sr_cible)

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


def vider_cache_prompts() -> None:
    """Compatibilité d'API avec cosyvoice_engine (aucun cache ici)."""
