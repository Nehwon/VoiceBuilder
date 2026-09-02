"""Nettoyage d'échantillons voix (préparation au clonage zéro-shot).

Pipeline en deux étapes :
  1. Demucs (htdemucs) — retire la musique / les autres voix du mix (stem
     "vocals").
  2. DeepFilterNet (df, modèle DeepFilterNet3) — débruite / dé-réverbère le
     stem vocal obtenu.

Les modèles sont téléchargés au premier usage dans ``config.ENHANCE_MODEL_DIR``
(volume ``/models`` en Docker) via ``TORCH_HOME`` / ``XDG_CACHE_HOME``.

L'import de demucs / deepfilternet est volontairement *paresseux* : le serveur
peut démarrer sans ces dépendances (le bouton « Nettoyer » affiche alors un
message clair).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from engine import config

_SR_DEMUCS = 44100   # fréquence d'échantillonnage du modèle Demucs htdemucs
_SR_DF = 48000       # fréquence d'échantillonnage de DeepFilterNet3
_SR_SORTIE = 44100   # fréquence du wav produit (référence voix)

# Indices de stems Demucs (htdemucs -> 4 stems : drums, bass, other, vocals)
_STEM_VOCALS = 3


def modele_dossier() -> Path:
    return Path(config.ENHANCE_MODEL_DIR)


def _set_caches() -> None:
    """Oriente les caches de téléchargement des modèles vers le dossier prévu."""
    base = modele_dossier()
    os.environ["TORCH_HOME"] = str(base / "demucs")
    os.environ["XDG_CACHE_HOME"] = str(base / "df")
    base.mkdir(parents=True, exist_ok=True)


def dispos() -> dict:
    """État des dépendances (sans les importer lourdement)."""
    import importlib.util
    demucs = importlib.util.find_spec("demucs") is not None
    df = importlib.util.find_spec("df") is not None and \
        importlib.util.find_spec("libdf") is not None
    return {
        "demucs": demucs,
        "deepfilternet": df,
        "dossier_modeles": str(modele_dossier()),
    }


def _lire_audio(chemin, sr_cible: int):
    """Charge un wav et le ramène en float32 mono à ``sr_cible`` Hz."""
    import librosa
    import soundfile as sf
    audio, sr = sf.read(chemin, dtype="float32", always_2d=True)
    if audio.shape[1] > 1:
        audio = audio.mean(axis=1, keepdims=True)
    audio = audio[:, 0]
    if sr != sr_cible:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=sr_cible)
    return audio, sr_cible


def _ecrire_audio(chemin, audio, sr: int) -> None:
    import soundfile as sf
    sf.write(chemin, audio, sr)


# ---------------------------------------------------------------------------
# Étape 1 : Demucs (séparation vocale)
# ---------------------------------------------------------------------------

def _demucs_vocals(src: Path, out: Path, mode: str, progress: Callable | None) -> dict:
    """Extrait le stem vocal d'un fichier (mode : cuda_fp16 | cuda_fp32 | cpu)."""
    import numpy as np
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    device = "cuda" if mode.startswith("cuda") else "cpu"
    fp16 = mode == "cuda_fp16"
    use_cuda = device == "cuda" and torch.cuda.is_available()
    if mode.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA demandé mais indisponible.")

    if progress:
        progress("Chargement du modèle Demucs (htdemucs)…", 5)

    model = get_model("htdemucs")
    model.eval()
    if use_cuda:
        model = model.cuda()
        if fp16:
            model = model.half()

    # lecture + resample 44,1 kHz stéréo
    audio, sr = _lire_audio(src, _SR_DEMUCS)
    # stéréo pour Demucs (2 canaux attendus)
    mix = np.stack([audio, audio], axis=0)  # [2, T]
    wav = torch.from_numpy(mix).unsqueeze(0)  # [1, 2, T]
    if use_cuda:
        wav = wav.cuda()
        if fp16:
            wav = wav.half()

    if progress:
        progress("Séparation vocale (Demucs)…", 25)
    with torch.no_grad():
        sources = apply_model(model, wav, split=True, overlap=0.25,
                              progress=False, num_workers=0)
    # sources: [1, stems, canaux, T]
    vocals = sources[0, _STEM_VOCALS].float()
    if vocals.ndim > 1 and vocals.shape[0] > 1:
        vocals = vocals.mean(dim=0)
    vocals = vocals.squeeze(0).cpu().numpy()

    if fp16:
        model.float()  # libère proprement
    out.parent.mkdir(parents=True, exist_ok=True)
    _ecrire_audio(out, vocals, _SR_DEMUCS)
    return {"mode": mode, "sr": _SR_DEMUCS}


# ---------------------------------------------------------------------------
# Étape 2 : DeepFilterNet (débruitage / dé-réverbération)
# ---------------------------------------------------------------------------

def _deepfilternet(chemins_in: Path, out: Path, progress: Callable | None) -> dict:
    """Débruite un fichier audio (DeepFilterNet3, modèle chargé automatiquement)."""
    import torch
    import df.enhance as df_enhance
    from df.enhance import enhance, init_df

    # DeepFilterNet est léger : on le force sur CPU pour ne pas concurrencer
    # Demucs / CosyVoice sur le GPU (VRAM partagée).
    df_enhance.get_device = lambda: "cpu"

    if progress:
        progress("Chargement du modèle DeepFilterNet (débruitage)…", 55)
    model, df_state, suffix = init_df(model_base_dir=None, log_level="WARNING")

    audio, sr = _lire_audio(chemins_in, _SR_DF)
    audio_t = torch.from_numpy(audio).unsqueeze(0)  # [1, T]

    if progress:
        progress("Débruitage / dé-réverbération (DeepFilterNet)…", 70)
    with torch.no_grad():
        out_t = enhance(model, df_state, audio_t)

    final = out_t.squeeze(0).cpu().numpy()
    # on repasse en 44,1 kHz pour un échantillon voix standard
    import librosa
    if _SR_DF != _SR_SORTIE:
        final = librosa.resample(final, orig_sr=_SR_DF, target_sr=_SR_SORTIE)
    out.parent.mkdir(parents=True, exist_ok=True)
    _ecrire_audio(out, final, _SR_SORTIE)
    return {"mode": "cpu", "sr": _SR_SORTIE}


# ---------------------------------------------------------------------------
# Pipeline public
# ---------------------------------------------------------------------------

def nettoyer(src: str | Path, out: str | Path,
             mode: str | None = None,
             progress: Callable | None = None,
             annuler: Callable | None = None) -> dict:
    """Nettoie un échantillon voix : Demucs puis DeepFilterNet.

    - ``mode`` : ``"auto"`` (défaut) tente cuda fp16, puis cuda fp32, puis cpu ;
      sinon ``"cuda_fp16" | "cuda_fp32" | "cpu"``.
    - ``progress(etape, pct)`` : rappel de progression (0-100).
    - ``annuler()`` : rappel renvoyant True pour interrompre le traitement.

    Renvoie un dict avec le mode réellement utilisé et la durée.
    """
    import torch

    src, out = Path(src), Path(out)
    _set_caches()
    t0 = time.time()

    # Ordre des modes Demucs à tenter (auto = fp16 -> fp32 -> cpu selon dispo)
    if mode in ("cuda_fp16", "cuda_fp32", "cpu"):
        modes: list[str] = [mode]
    elif torch.cuda.is_available():
        modes = ["cuda_fp16", "cuda_fp32", "cpu"]
    else:
        modes = ["cpu"]

    # --- étape 1 : Demucs ---
    if annuler and annuler():
        raise RuntimeError("Nettoyage annulé.")
    vocals_tmp = out.with_name(out.stem + "_vocals_tmp.wav")
    erreur_demucs = None
    mode_demucs = None
    for m in modes:
        if m.startswith("cuda") and not torch.cuda.is_available():
            continue
        try:
            if annuler and annuler():
                raise RuntimeError("Nettoyage annulé.")
            if progress:
                progress(f"Demucs ({m})…", 10)
            _demucs_vocals(src, vocals_tmp, m, progress)
            erreur_demucs = None
            mode_demucs = m
            break
        except torch.cuda.OutOfMemoryError:
            erreur_demucs = "manque de mémoire GPU"
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001
            erreur_demucs = str(exc)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    if mode_demucs is None or not vocals_tmp.exists():
        raise RuntimeError(f"Demucs a échoué : {erreur_demucs or 'fichier non produit'}")

    # --- étape 2 : DeepFilterNet ---
    if annuler and annuler():
        vocals_tmp.unlink(missing_ok=True)
        raise RuntimeError("Nettoyage annulé.")
    try:
        _deepfilternet(vocals_tmp, out, progress)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"DeepFilterNet a échoué : {exc}")
    finally:
        vocals_tmp.unlink(missing_ok=True)

    duree = round(time.time() - t0, 1)
    if progress:
        progress("Terminé.", 100)
    return {"mode": mode_demucs, "duree": duree, "sr": _SR_SORTIE,
            "sortie": str(out)}
