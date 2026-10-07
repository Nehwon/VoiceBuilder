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

import os
import re
import threading
from typing import Optional

import numpy as np
import soundfile as sf

from . import bgm
from . import config
from . import text_fr

# --- Téléchargement du modèle : progression exposée à l'UI --------------------
# Au premier lancement, les poids (3,3 Go) se téléchargent en silence.
# ``precharger_async()`` lance le téléchargement en tâche de fond pendant que
# l'UI affiche une modale avec la progression réelle (au lieu d'une barre
# figée sur « Lancement de la génération... »).
_TELECHARGEMENT = {"en_cours": False, "pct": 0, "fichier": "", "erreur": None}
_VERROU_DL = threading.Lock()
_FIL_DL: threading.Thread | None = None


def progression_telechargement() -> dict:
    """État du téléchargement (copie : ``en_cours``, ``pct``, ``fichier``)."""
    with _VERROU_DL:
        return dict(_TELECHARGEMENT)


def _maj_progression(pct: float, fichier: str = "", en_cours: bool = True) -> None:
    with _VERROU_DL:
        _TELECHARGEMENT["pct"] = max(0, min(100, round(pct)))
        if fichier:
            _TELECHARGEMENT["fichier"] = fichier
        _TELECHARGEMENT["en_cours"] = en_cours


class _TqdmProgression(__import__("tqdm").tqdm):
    """Barre tqdm réelle + report de l'avancement vers l'UI.

    Sous-classe du vrai ``tqdm`` (et non façade minimale) : huggingface_hub
    appelle ``refresh``/``close``/``set_description``/contexte, y compris pour
    les barres de reconstruction Xet — d'où le crash ``AttributeError:
    refresh`` avec la façade précédente.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("leave", False)
        super().__init__(*args, **kwargs)
        self._dernier_pct = -1.0

    def update(self, n=1):
        res = super().update(n)
        try:
            total = self.total or 0
            if total > 0:
                pct = 100.0 * (self.n or 0) / total
                if pct - self._dernier_pct >= 0.5 or pct >= 100:
                    self._dernier_pct = pct
                    desc = (getattr(self, "desc", "") or "").split("/")[-1][:60]
                    _maj_progression(pct, desc)
        except Exception:  # noqa: BLE001 — le report ne doit jamais casser le DL
            pass
        return res


def _repo_id() -> str:
    mid = config.OMNIVOICE_MODEL_ID
    return str(mid or config.OMNIVOICE_MODEL_DIR)


def modele_en_cache() -> bool:
    """Vrai si les poids sont déjà présents (aucun téléchargement requis)."""
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(repo_id=_repo_id(), local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 — absent du cache
        return False


def precacher_modele() -> None:
    """Télécharge les poids (bloquant) avec progression ; sans effet si en cache."""
    from huggingface_hub import snapshot_download

    if modele_en_cache():
        _maj_progression(100, en_cours=False)
        return
    _maj_progression(0, "connexion…")
    with _VERROU_DL:
        _TELECHARGEMENT["erreur"] = None
    try:
        snapshot_download(
            repo_id=_repo_id(),
            token=config.hf_token(),
            tqdm_class=_TqdmProgression,
        )
    except Exception as exc:  # noqa: BLE001 — exposée à l'UI, re-levée
        with _VERROU_DL:
            _TELECHARGEMENT["erreur"] = f"{type(exc).__name__} : {exc}"[:300]
            _TELECHARGEMENT["en_cours"] = False
        raise
    else:
        _maj_progression(100, en_cours=False)


def precharger_async() -> dict:
    """Lance ``precacher_modele`` en tâche de fond (une seule fois)."""
    global _FIL_DL
    with _VERROU_DL:
        en_cours = _TELECHARGEMENT["en_cours"]
        lance = _FIL_DL is not None and _FIL_DL.is_alive()
    if not en_cours and not lance and not modele_en_cache():
        with _VERROU_DL:
            _TELECHARGEMENT["en_cours"] = True
        _FIL_DL = threading.Thread(target=precacher_modele, daemon=True)
        _FIL_DL.start()
    return progression_telechargement()


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

        precacher_modele()  # sans effet si déjà en cache (progression sinon)
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

