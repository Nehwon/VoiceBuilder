"""Worker OmniVoice — micro-service TTS (image dédiée, M19.1-bis).

Transformers 5.x (exigé par OmniVoice) casse CosyVoice3 : les deux moteurs
ne peuvent pas cohabiter dans un processus. Ce worker tourne dans sa propre
image (`voicebuilder-omni`) ; le serveur principal l'appelle en HTTP pour
les blocs `omnivoice` (voir ``engine/omnivoice_engine.py``).

API :
    GET  /health     → {moteur, version, device, cuda, modele_charge}
    POST /synthesize → WAV (24 kHz natifs, resample/out_sr appliqués)
        {text, prompt_wav, prompt_text, speed=1.0, out_sr=null}

Les chemins `prompt_wav` sont lus **dans le worker** : monter les mêmes
volumes de voix que le serveur (ex. `/app/voix`, `/data/voice`).
Modèle : cache HuggingFace (monter un volume sur `~/.cache/huggingface`
pour ne pas retélécharger 3,3 Go à chaque recréation).
"""
from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

MODEL_ID = os.environ.get("OMNIVOICE_MODEL_ID", "k2-fsa/OmniVoice")
DEVICE = os.environ.get("OMNIVOICE_DEVICE", "cuda:0")

_model = None
_sr = 24000


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    import torch
    from omnivoice import OmniVoice

    _model = OmniVoice.from_pretrained(
        MODEL_ID, device_map=DEVICE, dtype=torch.float16)
    print(f"worker-omni : modèle chargé ({MODEL_ID}, {DEVICE})", flush=True)
    yield
    _model = None


app = FastAPI(title="VoiceBuilder worker OmniVoice", lifespan=lifespan)


class SyntheseIn(BaseModel):
    text: str
    prompt_wav: str
    prompt_text: str
    speed: float = 1.0
    out_sr: int | None = None


@app.get("/health")
def health():
    import torch
    return {"moteur": "omnivoice", "version": "0.2.1",
            "device": DEVICE, "cuda": torch.cuda.is_available(),
            "modele_charge": _model is not None}


@app.post("/synthesize")
def synthesize(payload: SyntheseIn):
    if _model is None:
        raise HTTPException(500, "Modèle non chargé.")
    if not Path(payload.prompt_wav).exists():
        raise HTTPException(400, f"Prompt wav introuvable : {payload.prompt_wav}")
    try:
        audio = _model.generate(text=payload.text,
                                ref_audio=str(payload.prompt_wav),
                                ref_text=payload.prompt_text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Synthèse OmniVoice : {exc}")
    if isinstance(audio, (list, tuple)):
        audio = audio[0]
    if hasattr(audio, "cpu"):
        audio = audio.cpu().numpy()
    y = np.asarray(audio, dtype=np.float32).squeeze()
    sr = _sr
    if payload.speed and payload.speed != 1.0:
        import librosa
        y = np.asarray(librosa.effects.time_stretch(y, rate=payload.speed),
                       dtype=np.float32)
    if payload.out_sr and payload.out_sr != _sr:
        import librosa
        y = np.asarray(librosa.resample(y, orig_sr=_sr,
                                        target_sr=payload.out_sr),
                       dtype=np.float32)
        sr = payload.out_sr
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")
