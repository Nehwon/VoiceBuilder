#!/usr/bin/env python3
"""M1 — Génération d'un montage multi-voix (CLI).

Usage :
    python -m tools.gen_multi_voix texte/chapitre.md -o output/montage.wav \
        [--voix voix/voix.txt] [--pause 0.45] [--vitesse 1.0] \
        [--max-chars 260] [--no-verify]

Équivalent CLI du pipeline multi-voix (cf. §4 de PROJET.md) sur moteur CosyVoice3.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, multi
from engine.voix import load_voix


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Montage multi-voix (CosyVoice3)")
    parser.add_argument("texte", help="Fichier taggé .md/.txt")
    parser.add_argument("-o", "--out", default=None, help="WAV de sortie (défaut: output/<nom>.wav)")
    parser.add_argument("--voix", default=None, help="Fichier voix.txt")
    parser.add_argument("--pause", type=float, default=None, help="Silence entre blocs (s)")
    parser.add_argument("--vitesse", type=float, default=None, help="Vitesse globale")
    parser.add_argument("--max-chars", type=int, default=None, help="Taille max d'un bloc")
    parser.add_argument("--no-verify", action="store_true", help="Désactive la vérif Whisper")
    parser.add_argument("--multi-prompt", action="store_true",
                        help="M17.4 : chaque bloc avec jusqu'à 2 prompts candidats, meilleur gardé (coût ×2 GPU)")
    parser.add_argument("--vllm", action="store_true", help="Active vLLM (LLM accéléré)")
    parser.add_argument("--trt", action="store_true", help="Active TensorRT (Flow accéléré)")
    parser.add_argument("--texte-dir", default=str(config.TEXTE_DIR), help="Dossier des textes")
    args = parser.parse_args(argv)

    config.ensure_dirs()

    texte = Path(args.texte)
    if not texte.is_absolute():
        texte = Path(args.texte_dir) / texte

    voix = load_voix(args.voix)

    out = args.out
    if not out:
        out = config.OUTPUT_DIR / f"{texte.stem}.wav"

    config.ensure_dirs()
    res = multi.generate(
        str(texte),
        voix,
        out=str(out),
        max_block_chars=args.max_chars,
        pause=args.pause,
        speed=args.vitesse,
        verify=not args.no_verify,
        verbose=True,
        load_vllm=args.vllm,
        load_trt=args.trt,
        multi_prompt=args.multi_prompt,
    )
    print(f"\nDurée totale : {res['duration']} s")
    print(f"Blocs : {len(res['blocs'])}")
    for bloc in res["blocs"]:
        prompt = f" (prompt : {bloc['prompt']})" if bloc.get("prompt") else ""
        print(f"  - {bloc['personnage']}: {bloc['chars']} chars, {bloc['duree']} s{prompt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())