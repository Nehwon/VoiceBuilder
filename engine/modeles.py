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
        def cb(a, b, c):
            progress(float(c) / max(1.0, float(_MODEL_TOTAL)) * 100, int(c))
    else:
        cb = None
    modelscope.snapshot_download(
        config.MODEL_ID_COSYVOICE3,
        local_dir=str(dest),
        progress_callback=cb,
    )


def _telech_huggingface(dest: Path, progress) -> None:
    import huggingface_hub

    if progress:
        class _Bar:
            """tqdm minimal qui reporte la progression à ``progress``."""
            total = _MODEL_TOTAL

            def __init__(self, *a, **k):
                self._n = 0
                self.n = 0

            def update(self, n=1):
                self._n += int(n)
                self.n = self._n
                progress(float(self._n) / max(1.0, float(_MODEL_TOTAL)) * 100,
                         int(self._n))

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        bar = _Bar()
        huggingface_hub.snapshot_download(
            config.MODEL_ID_COSYVOICE3,
            local_dir=str(dest),
            tqdm_class=bar,
        )
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

    staged = Path(tempfile.mkdtemp(prefix=".cv3-", dir=str(dest.parent)))
    try:
        if source == "huggingface":
            _telech_huggingface(staged, progress)
        else:
            _telech_modelscope(staged, progress)
        # glisser d'un seul tenant vers la destination (peut déjà exister)
        for sub in staged.iterdir():
            target = dest / sub.name
            if target.exists():
                import shutil
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            sub.rename(target)
        import shutil
        shutil.rmtree(staged, ignore_errors=True)
        return dest
    except BaseException:
        import shutil
        shutil.rmtree(staged, ignore_errors=True)
        raise