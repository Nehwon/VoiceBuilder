"""M18.2 — Boucle d'entraînement LoRA (1 GPU, accumulation, AMP, reprise)."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import torch

from .modele import resumer_adaptateurs
from .presets import ConfigEntrainement


def _optimiseur(model, cfg: ConfigEntrainement):
    params = [p for p in model.parameters() if p.requires_grad]
    if cfg.optim == "adamw":
        return torch.optim.AdamW(params, lr=cfg.lr)
    try:
        import bitsandbytes as bnb
    except ImportError as exc:
        raise RuntimeError(
            f"optim {cfg.optim} exige bitsandbytes (`pip install bitsandbytes`)") from exc
    if cfg.optim == "adamw_8bit":
        return bnb.optim.AdamW8bit(params, lr=cfg.lr)
    return bnb.optim.PagedAdamW8bit(params, lr=cfg.lr)


def _scheduler(optim, cfg: ConfigEntrainement, total_steps: int):
    def _lr(step: int) -> float:
        if step < cfg.warmup:
            return cfg.lr * max(1, step) / max(1, cfg.warmup)
        prog = (step - cfg.warmup) / max(1, total_steps - cfg.warmup)
        return cfg.lr * max(0.0, 1.0 - prog)
    return torch.optim.lr_scheduler.LambdaLR(optim, _lr)


def _courbe_png(csv_path: Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    steps, pertes = [], []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("phase") == "train":
                steps.append(int(row["step"]))
                pertes.append(float(row["loss"]))
    if not pertes:
        return None
    plt.figure()
    plt.plot(steps, pertes)
    plt.xlabel("step")
    plt.ylabel("loss")
    plt.title("Perte d'entraînement LoRA")
    out = csv_path.with_suffix(".png")
    plt.savefig(out)
    plt.close()
    return out


def entrainer(model, train_loader, dev_loader, cfg: ConfigEntrainement,
              dossier: str | Path, device: str,
              log_fn=print) -> dict:
    """Boucle complète : accumulation, AMP bf16, clip, eval, checkpoints, CSV+PNG."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    csv_path = dossier / "pertes.csv"
    model.to(device)
    optim = _optimiseur(model, cfg)

    total_steps = cfg.max_steps or 10 ** 9
    sched = _scheduler(optim, cfg, total_steps)
    step, accum = 0, 0
    meilleur_dev: float | None = None

    if (dossier / "dernier.pt").exists():
        ckpt = torch.load(str(dossier / "dernier.pt"), map_location="cpu")
        model.load_state_dict(ckpt["adaptateurs"], strict=False)
        optim.load_state_dict(ckpt["optim"])
        sched.load_state_dict(ckpt["sched"])
        step = ckpt.get("step", 0)
        meilleur_dev = ckpt.get("meilleur_dev")
        log_fn(f"Reprise au step {step} ({dossier / 'dernier.pt'})")

    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["step", "phase", "loss"])
    amp = device.startswith("cuda") and cfg.precision == "bf16"
    fini = False
    epoch = 0
    while not fini:
        epoch += 1
        for batch in train_loader:
            if "instruct_token" not in batch:
                raise RuntimeError(
                    "Batch sans instruct_token : régénère le dataset "
                    "(preparer_lora écrit `instruct` depuis M18.1).")
            for k in ("text_token", "speech_token"):
                batch[k] = batch[k].to(device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                res = model(batch, torch.device(device))
                perte = res["loss"] / cfg.accumulation
            perte.backward()
            accum += 1
            if accum < cfg.accumulation:
                continue
            accum = 0
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], cfg.clip)
            optim.step()
            sched.step()
            optim.zero_grad()
            step += 1
            val = float(perte.detach()) * cfg.accumulation
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([step, "train", round(val, 4)])
            if step % 50 == 0:
                log_fn(f"step {step} — loss {val:.4f}")
            if cfg.max_steps and step >= cfg.max_steps:
                fini = True
                break
            if step % cfg.eval_chaque == 0:
                perte_dev = evaluer(model, dev_loader, device)
                log_fn(f"step {step} — dev {perte_dev:.4f}")
                with open(csv_path, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([step, "dev", round(perte_dev, 4)])
                if meilleur_dev is None or perte_dev < meilleur_dev:
                    meilleur_dev = perte_dev
                    torch.save({"adaptateurs": resumer_adaptateurs(model),
                                "step": step},
                               str(dossier / "meilleur.pt"))
            if step % cfg.sauver_chaque == 0:
                torch.save({"adaptateurs": resumer_adaptateurs(model),
                            "optim": optim.state_dict(),
                            "sched": sched.state_dict(), "step": step,
                            "meilleur_dev": meilleur_dev},
                           str(dossier / "dernier.pt"))
        if cfg.epochs and epoch >= cfg.epochs:
            fini = True
    torch.save({"adaptateurs": resumer_adaptateurs(model),
                "optim": optim.state_dict(), "sched": sched.state_dict(),
                "step": step, "meilleur_dev": meilleur_dev},
               str(dossier / "dernier.pt"))
    png = _courbe_png(csv_path)
    return {"steps": step, "epochs": epoch, "meilleur_dev": meilleur_dev,
            "courbe": str(png) if png else None, "csv": str(csv_path)}


@torch.no_grad()
def evaluer(model, dev_loader, device: str) -> float:
    model.eval()
    pertes, n = 0.0, 0
    for batch in dev_loader:
        if "instruct_token" not in batch:
            raise RuntimeError("Batch sans instruct_token (cf. preparer_lora).")
        for k in ("text_token", "speech_token"):
            batch[k] = batch[k].to(device)
        res = model(batch, torch.device(device))
        pertes += float(res["loss"])
        n += 1
        if n >= 20:
            break
    model.train()
    return pertes / max(1, n)
