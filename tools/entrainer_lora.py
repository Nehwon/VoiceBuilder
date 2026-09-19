#!/usr/bin/env python3
"""M18.2 — Entraînement LoRA « petit GPU » (Palier 1).

Usage :
    python tools/entrainer_lora.py --dataset dataset/lora/<voix>/manifest.json
        --vram 12 --steps 300 [--out lora/<voix>] [--dry-run]

Presets `--vram 12/16/24` (`PROJET_FINE.md` §3.3) : rang, qLoRA 4-bit,
gradient checkpointing, micro-batch 1 + accumulation, optim 8-bit/paged,
freeze Flow (on n'entraîne que le LLM, comme la recette officielle),
ZeRO-2/offload en filet (`--zero 2`, deepspeed requis). Reprise auto sur
`dernier.pt`, logs CSV + courbe PNG, registre par voix (étage OOM, scores).

D'abord 1 voix test (15–30 min, quelques centaines de steps) avant le full ;
GPU 12 Go : l'inférence serveur et l'entraînement ne cohabitent pas
(arrêter le conteneur GUI ou entraîner ailleurs).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.lora import config_pour, resume
from engine.lora.donnees import (
    YAML_DEFAUT, charger_manifest, charger_yaml, construire_loaders,
    ecrire_listes,
)
from engine.lora.registre import enregistrer


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M18.2 — Entraînement LoRA petit GPU")
    ap.add_argument("--dataset", required=True, help="manifest.json M18.1")
    ap.add_argument("--vram", type=int, default=16, choices=[12, 16, 24])
    ap.add_argument("--steps", type=int, default=None, help="Plafond de steps")
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--out", default=None, help="Dossier LoRA (défaut: <dataset>/lora)")
    ap.add_argument("--yaml", default=YAML_DEFAUT, help="Yaml CosyVoice3")
    ap.add_argument("--model-dir", default=None, help="Modèle de base (défaut: config)")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--rang", type=int, default=None)
    ap.add_argument("--accum", type=int, default=None, dest="accumulation")
    ap.add_argument("--cibles", default=None, help="Modules LoRA (défaut: q_proj,v_proj)")
    ap.add_argument("--etage", default=None, help="Étage OOM retenu (défaut: auto)")
    ap.add_argument("--zero", type=int, default=None, help="0 (off) ou 2 (ZeRO-2+offload)")
    ap.add_argument("--sans-decodeur", action="store_true",
                    help="Gèle aussi la tête speech-tokens")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche la config résolue sans entraîner")
    args = ap.parse_args(argv)

    manifest = charger_manifest(args.dataset)
    perso = any([args.rang, args.accumulation, args.cibles, args.zero is not None])
    cfg = config_pour(args.vram, rang=args.rang, accumulation=args.accumulation,
                      cibles=args.cibles, zero=args.zero,
                      entrainer_decodeur=not args.sans_decodeur,
                      max_steps=args.steps, epochs=args.epochs,
                      etage=args.etage or "")
    if not cfg.etage:
        cfg.etage = f"{args.vram}-perso" if perso else config_pour(args.vram).etage
    racine = Path(args.dataset).parent if Path(args.dataset).is_file() \
        else Path(args.dataset)
    dossier = Path(args.out) if args.out else racine / "lora"
    print(f"LoRA M18.2 — dataset {manifest.get('segments')} segments "
          f"({manifest.get('duree_min')} min), {resume(cfg)}")
    print(f"Sortie : {dossier}")
    if args.dry_run:
        listes = ecrire_listes(manifest, dossier / "listes")
        print("Listes :", {k: str(v) for k, v in listes.items()})
        print("(dry-run : entraînement non lancé)")
        return 0

    import torch
    from engine import config as _cfg
    from engine.lora.boucle import entrainer
    from engine.lora.modele import appliquer_lora, construire_base

    model_dir = Path(args.model_dir) if args.model_dir \
        else Path(_cfg.COSYVOICE_MODEL_DIR)
    import os
    # active l'extraction en ligne (campplus) dans le pipeline dataset,
    # comme cosyvoice/bin/train.py (--onnx_path)
    os.environ.setdefault("onnx_path", str(model_dir))
    if args.zero == 2:
        try:
            import deepspeed  # noqa: F401
        except ImportError:
            print("❌ ZeRO-2 exige deepspeed (`pip install deepspeed`).")
            return 1
    listes = ecrire_listes(manifest, dossier / "listes")
    configs = charger_yaml(args.yaml, model_dir, cfg.micro_batch)
    print("Construction du modèle de base…")
    model = construire_base(configs, model_dir, cfg, args.device)
    print("Application LoRA…")
    model, nb, total = appliquer_lora(model, cfg)
    print(f"Paramètres entraînés : {nb / 1e6:.1f} M / {total / 1e6:.0f} M")
    print("Dataloaders…")
    train_loader, dev_loader = construire_loaders(configs, listes)
    print("Entraînement…")
    res = entrainer(model, train_loader, dev_loader, cfg, dossier,
                    args.device, log_fn=print)
    entree = enregistrer(racine, manifest.get("voix", "?"), {
        "poids": str((dossier / "meilleur.pt").resolve())
        if (dossier / "meilleur.pt").exists()
        else str((dossier / "dernier.pt").resolve()),
        "config": resume(cfg), "etage": cfg.etage,
        "steps": res["steps"], "meilleur_dev": res["meilleur_dev"],
        "courbe": res["courbe"]})
    print(f"Terminé : {res['steps']} steps, dev {res['meilleur_dev']} "
          f"(registre : {entree})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
