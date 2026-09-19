"""M18.2 — Base LLM CosyVoice3 + adaptateurs LoRA (+ qLoRA 4-bit optionnel)."""
from __future__ import annotations

from pathlib import Path

import torch

from .presets import ConfigEntrainement


def poids_llm(model_dir: str | Path) -> Path:
    p = Path(model_dir) / "llm.pt"
    if not p.exists():
        raise FileNotFoundError(f"Poids LLM introuvables : {p}")
    return p


def construire_base(configs, model_dir: str | Path, cfg: ConfigEntrainement,
                    device: str):
    """Construit le LLM (yaml), charge llm.pt, quantifie si qLoRA.

    La quantification 4-bit NF4 passe par l'API publique transformers
    (monkeypatch localisé de ``from_pretrained`` du Qwen2) : pas de
    bricolage de modules maison.
    """
    from transformers import BitsAndBytesConfig, Qwen2ForCausalLM

    _origine = Qwen2ForCausalLM.from_pretrained
    if cfg.qlora:
        try:
            import bitsandbytes  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "qLoRA exige bitsandbytes (`pip install bitsandbytes`)") from exc
        conf = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True)
        Qwen2ForCausalLM.from_pretrained = classmethod(
            lambda cls, *a, **k: _origine(*a, **{**k, "quantization_config": conf}))
    try:
        model = configs["llm"]
    finally:
        Qwen2ForCausalLM.from_pretrained = _origine
    if not cfg.qlora:
        dtype = torch.bfloat16 if cfg.precision == "bf16" else torch.float32
        model = model.to(dtype)
    etat = torch.load(str(poids_llm(model_dir)), map_location="cpu")
    model.load_state_dict(etat, strict=False)
    return model


def appliquer_lora(model, cfg: ConfigEntrainement):
    """Enveloppe PEFT du Qwen2 + gel (sauf adaptateurs et décodeur si demandé)."""
    try:
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    except ImportError as exc:
        raise RuntimeError(
            "LoRA exige peft (`pip install peft`)") from exc
    backbone = model.llm.model
    if cfg.qlora or cfg.checkpointing:
        backbone = prepare_model_for_kbit_training(
            backbone, use_gradient_checkpointing=cfg.checkpointing)
    if cfg.checkpointing and not cfg.qlora:
        try:
            backbone.gradient_checkpointing_enable()
        except Exception:  # noqa: BLE001
            pass
    lora_conf = LoraConfig(r=cfg.rang, lora_alpha=cfg.alpha,
                           lora_dropout=cfg.dropout,
                           target_modules=list(cfg.cibles),
                           task_type="CAUSAL_LM")
    interne = backbone.model  # Qwen2 interne (chaîne model.llm.model.model.*)
    backbone = get_peft_model(backbone, lora_conf)
    # PEFT décale la chaîne d'attributs (peft.model → Qwen2 de base) :
    # on la restaure pour le forward CosyVoice (embed_tokens).
    backbone.model = interne
    model.llm.model = backbone
    # gel global, sauf adaptateurs LoRA (+ décodeur speech-tokens si demandé)
    for p in model.parameters():
        p.requires_grad = False
    for n, p in model.named_parameters():
        if "lora_" in n:
            p.requires_grad = True
        if cfg.entrainer_decodeur and n.startswith("llm_decoder."):
            p.requires_grad = True
    model.train()
    nb = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    return model, nb, total


def resumer_adaptateurs(model) -> dict:
    """État à sauvegarder : adaptateurs LoRA + décodeur (+ config PEFT)."""
    return {k: v.cpu() for k, v in model.state_dict().items()
            if "lora_" in k or k.startswith("llm_decoder.")}
