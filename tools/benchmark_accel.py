#!/usr/bin/env python3
"""M5.3 — Benchmark comparatif avec warmup séparé.

Mesure le RTF pur de synthèse CosyVoice (hors vérif Whisper) pour chaque
combinaison d'accélération, avec warmup pour éliminer le cold start.

Usage (Docker GPU) :
    docker compose run --rm gui python -m tools.benchmark_accel
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, cosyvoice_engine

TEXT = """\
Dans cet épisode de démonstration, nous allons explorer les mécanismes \
fondamentaux de la synthèse vocale par clonage. La technologie CosyVoice trois \
utilise un modèle de neural qui apprend à reproduire le timbre et la prosodie \
d'un locuteur à partir d'un simple extrait audio de quelques secondes. C'est un \
domaine en pleine évolution qui promet de révolutionner la façon dont nous \
interagissons avec les machines."""


def synthetize(model, text, prompt_wav, prompt_text):
    """Synthetise et retourne (audio_np, duration_s)."""
    import torch
    chunks = []
    for out in model.inference_zero_shot(text, prompt_text, prompt_wav, stream=False, speed=1.0):
        chunks.append(out["tts_speech"])
    audio = torch.cat(chunks, dim=1).squeeze().cpu().numpy()
    return audio, len(audio) / model.sample_rate


def measure_rtf(model, text, prompt_wav, prompt_text, n_warmup=1, n_runs=3):
    """Warmup puis mesure du RTF moyen sur n_runs itérations."""
    for _ in range(n_warmup):
        synthetize(model, text, prompt_wav, prompt_text)

    times = []
    durations = []
    for _ in range(n_runs):
        t0 = time.time()
        audio, dur = synthetize(model, text, prompt_wav, prompt_text)
        elapsed = time.time() - t0
        times.append(elapsed)
        durations.append(dur)

    avg_time = sum(times) / len(times)
    avg_dur = sum(durations) / len(durations)
    return avg_time, avg_dur, avg_time / avg_dur


def main():
    from engine.voix import load_voix
    config.ensure_dirs()

    voices = load_voix()
    voice = list(voices)[0]
    print(f"Voix : {voice.name} ({voice.wav})")
    print(f"Texte : {len(TEXT)} chars")

    prompt_wav = str(voice.wav)
    prompt_text = voice.system_prompt

    results = {}

    configs = [
        ("PyTorch (baseline)", False, False),
        ("+ vLLM", True, False),
        ("+ TensorRT", False, True),
        ("+ vLLM + TensorRT", True, True),
    ]

    for label, use_vllm, use_trt in configs:
        print(f"\n{'='*50}")
        print(f"  {label}")
        print(f"{'='*50}")

        cosyvoice_engine._model = None
        cosyvoice_engine._sr = None

        try:
            model, sr = cosyvoice_engine.load(
                device=config.DEFAULT_DEVICE,
                fp16=config.DEFAULT_FP16,
                load_vllm=use_vllm,
                load_trt=use_trt,
            )
            avg_time, avg_dur, rtf = measure_rtf(model, TEXT, prompt_wav, prompt_text)
            results[label] = {"rtf": rtf, "time": avg_time, "duration": avg_dur, "ok": True}
            print(f"  RTF : {rtf:.3f}")
            print(f"  Temps : {avg_time:.2f} s")
            print(f"  Durée audio : {avg_dur:.2f} s")
        except Exception as e:
            results[label] = {"rtf": None, "ok": False, "error": str(e)}
            print(f"  ❌ Erreur : {e}")

    print(f"\n{'='*60}")
    print("  RÉSUMÉ (avec warmup)")
    print(f"{'='*60}")
    print(f"{'Configuration':<25} {'RTF':>8} {'Temps':>8} {'Durée':>8} {'Statut'}")
    print("-" * 60)
    for label, r in results.items():
        if r["ok"]:
            print(f"{label:<25} {r['rtf']:>8.3f} {r['time']:>7.2f}s {r['duration']:>7.2f}s  ✅")
        else:
            print(f"{label:<25} {'—':>8} {'—':>8} {'—':>8}  ❌ {r.get('error', '')[:30]}")

    baseline = results.get("PyTorch (baseline)", {}).get("rtf")
    if baseline:
        print(f"\nAccélérations vs baseline (RTF {baseline:.3f}) :")
        for label, r in results.items():
            if r["ok"] and r["rtf"] is not None:
                speedup = baseline / r["rtf"]
                print(f"  {label}: ×{speedup:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
