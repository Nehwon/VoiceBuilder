"""Gestion des modèles CosyVoice (téléchargement au premier lancement, M15).

Le modèle n'est volontairement **pas** embarqué dans l'image Docker : il est
téléchargé par l'utilisateur **depuis l'interface** au premier lancement, dans
un volume (ou le dossier ``pretrained_models``) monté en écriture. Si le volume
contient déjà le modèle, il est détecté et rien n'est re-téléchargé.

Sources supportées (voir ``config.MODEL_SOURCE``) :
  - ``modelscope``  (défaut) : ``FunAudioLLM/Fun-CosyVoice3-0.5B-2512``
  - ``huggingface``           : identifiant identique (miroir)
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import config

# Fichiers minimaux requis pour qu'un dossier soit considéré comme un modèle
# CosyVoice3 utilisable (le `cosyvoice3.yaml` pilote le chargement AutoModel).
FICHIERS_REQUIS = (
    "cosyvoice3.yaml",
    "campplus.onnx",
    "speech_tokenizer_v3.onnx",
    "llm.pt",
    "flow.pt",
    "hift.pt",
)

# Taille (octets) du repo Fun-CosyVoice3-0.5B-2512 (~11 Go) — estimation
# utilisée uniquement pour produire un pourcentage global de progression.
_MODEL_TOTAL = 11767984206


def chemin_modele() -> Path:
    return config.COSYVOICE_MODEL_DIR


def modele_present() -> bool:
    """True si ``config.COSYVOICE_MODEL_DIR`` contient un modèle utilisable."""
    d = config.COSYVOICE_MODEL_DIR
    if not d.is_dir():
        return False
    return all((d / f).is_file() for f in FICHIERS_REQUIS)


def manquants() -> list:
    d = config.COSYVOICE_MODEL_DIR
    if not d.is_dir():
        return list(FICHIERS_REQUIS)
    return [f for f in FICHIERS_REQUIS if not (d / f).is_file()]


def octets_dans(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())


def infos() -> dict:
    """État courant du modèle pour l'interface."""
    present = modele_present()
    return {
        "present": present,
        "dossier": str(config.COSYVOICE_MODEL_DIR),
        "source": config.MODEL_SOURCE,
        "id": config.MODEL_ID_COSYVOICE3,
        "manquants": [] if present else manquants(),
        "octets": octets_dans(config.COSYVOICE_MODEL_DIR),
        "total": _MODEL_TOTAL,
    }


def _telech_modelscope(dest: Path, progress) -> None:
    import modelscope

    if progress:
        from modelscope.hub import file_download

        class _MsBar(file_download.tqdm):
            _octets = 0

            def __init__(self, *a, **k):
                k.setdefault("disable", True)
                super().__init__(*a, **k)

            def update(self, n=1):
                super().update(n)
                type(self)._octets += int(n)
                t = type(self)._octets
                progress(
                    float(t) / max(1.0, float(_MODEL_TOTAL)) * 100, int(t))

        original = file_download.tqdm
        file_download.tqdm = _MsBar
        try:
            modelscope.snapshot_download(
                config.MODEL_ID_COSYVOICE3,
                local_dir=str(dest),
            )
        finally:
            file_download.tqdm = original
    else:
        modelscope.snapshot_download(
            config.MODEL_ID_COSYVOICE3,
            local_dir=str(dest),
        )


def _telech_huggingface(dest: Path, progress) -> None:
    import importlib
    import huggingface_hub
    import huggingface_hub._snapshot_download as _sd
    hf_tqdm_module = importlib.import_module("huggingface_hub.utils.tqdm")

    if progress:
        class _HfBar(hf_tqdm_module.tqdm):
            _octets = 0

            def __init__(self, *a, **k):
                self._compte_octets = k.get("unit") == "B"
                k.setdefault("disable", True)
                super().__init__(*a, **k)

            def update(self, n=1):
                super().update(n)
                if self._compte_octets:
                    type(self)._octets += int(n)
                    t = type(self)._octets
                    progress(
                        float(t) / max(1.0, float(_MODEL_TOTAL)) * 100,
                        int(t))

        orig_utils = hf_tqdm_module.tqdm
        orig_sd = _sd.hf_tqdm
        hf_tqdm_module.tqdm = _HfBar
        _sd.hf_tqdm = _HfBar
        try:
            huggingface_hub.snapshot_download(
                config.MODEL_ID_COSYVOICE3,
                local_dir=str(dest),
            )
        finally:
            hf_tqdm_module.tqdm = orig_utils
            _sd.hf_tqdm = orig_sd
    else:
        huggingface_hub.snapshot_download(
            config.MODEL_ID_COSYVOICE3,
            local_dir=str(dest),
        )


def telecharger(source: Optional[str] = None,
                progress: Optional[Callable[[float, int], None]] = None) -> Path:
    """Télécharge le modèle CosyVoice3 dans ``config.COSYVOICE_MODEL_DIR``.

    - ``source`` : "modelscope" (défaut) ou "huggingface".
    - ``progress(pct, octets)`` : rappel facultatif, appelé durant le transfert.

    Le téléchargement passe par un dossier temporaire puis un `rename`, de sorte
    qu'un échec ne laisse jamais un modèle partiel à la place du modèle courant.
    Renvoie le chemin du dossier téléchargé.
    """
    source = (source or config.MODEL_SOURCE).lower()
    dest = config.COSYVOICE_MODEL_DIR
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)

    # Staging *dans* le volume de destination : `dest` peut être un point de
    # montage Docker distinct de `/`, un simple `rename` échouerait sinon
    # (Errno 18 Invalid cross-device link).
    staged = Path(tempfile.mkdtemp(prefix=".cv3-", dir=str(dest)))
    try:
        if source == "huggingface":
            _telech_huggingface(staged, progress)
        else:
            _telech_modelscope(staged, progress)
        # glisser d'un seul tenant vers la destination (peut déjà exister)
        import shutil
        for sub in staged.iterdir():
            target = dest / sub.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(sub), str(target))
        shutil.rmtree(staged, ignore_errors=True)
        return dest
    except BaseException:
        import shutil
        shutil.rmtree(staged, ignore_errors=True)
        raise