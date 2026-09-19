"""M18.2 — Listes parquet + dataloaders CosyVoice depuis un manifest M18.1."""
from __future__ import annotations

import json
from functools import partial
from pathlib import Path

YAML_DEFAUT = "vendor/CosyVoice/examples/libritts/cosyvoice3/conf/cosyvoice3.yaml"


def charger_manifest(manifest: str | Path) -> dict:
    manifest = Path(manifest)
    if manifest.is_dir():
        manifest = manifest / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if "splits" not in data:
        raise ValueError(f"Manifest sans splits parquet (relance preparer_lora --tokens) : {manifest}")
    return data


def ecrire_listes(manifest: dict, dossier: str | Path) -> dict[str, Path]:
    """Écrit train.data.list / dev.data.list (chemins parquet) pour le loader."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    sorties = {}
    for split in ("train", "dev"):
        info = (manifest.get("splits") or {}).get(split)
        if not info:
            continue
        parquets = sorted(Path(info["parquet"]).glob("parquet_*.tar"))
        if not parquets:
            raise ValueError(f"Aucun parquet dans {info['parquet']}")
        lst = dossier / f"{split}.data.list"
        lst.write_text("".join(f"{p}\n" for p in parquets), encoding="utf-8")
        sorties[split] = lst
    if "train" not in sorties:
        raise ValueError("Split train introuvable dans le manifest")
    return sorties


def charger_yaml(yaml_path: str | Path, model_dir: str | Path,
                 micro_batch: int):
    """Charge le yaml CosyVoice3 (LLM seul, batch statique = micro-batch)."""
    import sys
    from hyperpyyaml import load_hyperpyyaml
    from engine import config as _cfg
    for p in (str(_cfg.COSYVOICE_ROOT), str(_cfg.MATCHA_TTS_DIR)):
        if p not in sys.path:
            sys.path.append(p)
    yaml_path = Path(yaml_path)
    if not yaml_path.is_absolute():
        from engine import config as _cfg2
        yaml_path = Path(_cfg2.PROJECT_ROOT) / yaml_path
    model_dir = Path(model_dir)
    overrides = {"qwen_pretrain_path": str(model_dir / "CosyVoice-BlankEN")}
    for k in ("flow", "hift", "hifigan"):
        overrides[k] = None
    with open(yaml_path, encoding="utf-8") as f:
        configs = load_hyperpyyaml(f, overrides=overrides)
    # batch statique (micro-batch maîtrisé, accumulation gérée par la boucle)
    pipe = []
    for p in configs["data_pipeline"]:
        if getattr(getattr(p, "func", None), "__name__", "") == "batch":
            p = partial(p.func, **{**p.keywords, "batch_type": "static",
                                   "batch_size": micro_batch})
        pipe.append(p)
    configs["data_pipeline"] = pipe
    return configs


def construire_loaders(configs, listes: dict, workers: int = 2):
    """Dataloaders train/dev (même montage que la recette officielle,
    sans deepspeed : inutile hors ZeRO)."""
    from torch.utils.data import DataLoader

    from cosyvoice.dataset.dataset import Dataset
    pipe = configs["data_pipeline"]
    train_ds = Dataset(str(listes["train"]), data_pipeline=pipe, mode="train",
                       gan=False, dpo=False, shuffle=True, partition=True)
    dev_liste = str(listes.get("dev", listes["train"]))
    dev_ds = Dataset(dev_liste, data_pipeline=pipe, mode="dev",
                     gan=False, dpo=False, shuffle=False, partition=False)
    mk = lambda ds: DataLoader(ds, batch_size=None, pin_memory=False,
                               num_workers=workers, prefetch_factor=10)
    return mk(train_ds), mk(dev_ds)
