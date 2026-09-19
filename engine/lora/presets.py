"""M18.2 — Presets VRAM 12/16/24 + échelle anti-OOM (`PROJET_FINE.md` §3.3).

Pur (sans torch) : `config_pour()` résout un preset en configuration
effective complète, documentée dans le registre par voix.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfigEntrainement:
    vram: int = 16
    rang: int = 8
    alpha: int = 16
    dropout: float = 0.05
    cibles: list = field(default_factory=lambda: ["q_proj", "v_proj"])
    qlora: bool = False            # backbone quantifié 4-bit NF4 (bitsandbytes)
    checkpointing: bool = True     # gradient checkpointing
    micro_batch: int = 1
    accumulation: int = 8
    optim: str = "adamw_8bit"      # adamw | adamw_8bit | paged_adamw_8bit
    precision: str = "bf16"        # bf16 | fp32
    zero: int = 0                  # 0 = désactivé, 2 = ZeRO-2 + offload CPU
    entrainer_decodeur: bool = True  # tête speech-tokens (petite, utile au timbre)
    warmup: int = 100
    lr: float = 2e-4
    clip: float = 1.0
    max_steps: int | None = 2000
    epochs: int | None = None
    eval_chaque: int = 200
    sauver_chaque: int = 200
    etage: str = ""                # étage OOM retenu (auto si vide)


PRESETS = {
    # 24 Go : confortable — LoRA large, AdamW standard, pas de checkpointing.
    24: dict(rang=16, alpha=32, qlora=False, checkpointing=False,
             micro_batch=2, accumulation=4, optim="adamw",
             etage="24-base"),
    # 16 Go : checkpointing + accumulation + optim 8-bit.
    16: dict(rang=8, alpha=16, qlora=False, checkpointing=True,
             micro_batch=1, accumulation=8, optim="adamw_8bit",
             etage="16+ckpt+accum8+bnb8bit"),
    # 12 Go : + qLoRA 4-bit + optim pagé + accumulation poussée.
    12: dict(rang=8, alpha=16, qlora=True, checkpointing=True,
             micro_batch=1, accumulation=16, optim="paged_adamw_8bit",
             etage="12+ckpt+accum16+qlora+paged"),
}


def config_pour(vram: int = 16, **surcharges) -> ConfigEntrainement:
    """Résout le preset VRAM + surcharges explicites (CLI)."""
    if vram not in PRESETS:
        raise ValueError(f"VRAM gérée : {sorted(PRESETS)} (reçu {vram})")
    cfg = ConfigEntrainement(vram=vram, **PRESETS[vram])
    for cle, val in surcharges.items():
        if val is None:
            continue
        if not hasattr(cfg, cle):
            raise ValueError(f"Option inconnue : {cle}")
        setattr(cfg, cle, val)
    if isinstance(cfg.cibles, str):
        cfg.cibles = [c.strip() for c in cfg.cibles.split(",") if c.strip()]
    if cfg.zero not in (0, 2):
        raise ValueError("zero géré : 0 (off) ou 2 (ZeRO-2 + offload CPU)")
    if cfg.optim not in ("adamw", "adamw_8bit", "paged_adamw_8bit"):
        raise ValueError("optim géré : adamw | adamw_8bit | paged_adamw_8bit")
    return cfg


def resume(cfg: ConfigEntrainement) -> str:
    """Une ligne de résumé (logs + registre)."""
    bits = [f"r={cfg.rang}", f"accum={cfg.accumulation}",
            f"optim={cfg.optim}", cfg.precision]
    if cfg.qlora:
        bits.append("qLoRA-4bit")
    if cfg.checkpointing:
        bits.append("ckpt")
    if cfg.zero == 2:
        bits.append("zero2+offload")
    if not cfg.entrainer_decodeur:
        bits.append("decodeur-gelé")
    return f"vram={cfg.vram} " + " ".join(bits) + f" [{cfg.etage}]"
