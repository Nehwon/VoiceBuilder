"""M18.2 — Registre des LoRA par voix (poids, config, étage OOM, scores)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def chemin_registre(racine_dataset: str | Path) -> Path:
    return Path(racine_dataset) / "lora_registry.json"


def lire(racine_dataset: str | Path) -> dict:
    p = chemin_registre(racine_dataset)
    if not p.exists():
        return {"voix": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"voix": {}}


def enregistrer(racine_dataset: str | Path, voix: str, entree: dict) -> dict:
    """Ajoute/met à jour l'entrée d'une voix (étage OOM + scores)."""
    reg = lire(racine_dataset)
    entree = dict(entree)
    entree["maj"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg.setdefault("voix", {})[voix] = entree
    p = chemin_registre(racine_dataset)
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    return entree
