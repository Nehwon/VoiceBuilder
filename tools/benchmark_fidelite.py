#!/usr/bin/env python3
"""M4.x — Benchmark de fidélité : max_chars, seuil Whisper, vérification.

Mesure l'impact de chaque paramètre sur :
  - le nombre de blocs (moins = mieux, moins de ruptures de ton)
  - la durée de génération
  - la couverture Whisper (fidélité du contenu)
  - les re-splits déclenchés par la vérification

Usage (Docker GPU) :
    docker compose run --rm gui python -m tools.benchmark_fidelite
    docker compose run --rm gui python -m tools.benchmark_fidelite --voice Superama
    docker compose run --rm gui python -m tools.benchmark_fidelite --device cpu --texte texte/exemple_demo.md

Usage (hors Docker, avec GPU + CosyVoice venv) :
    python -m tools.benchmark_fidelite [--voice NOM] [--texte PATH] [--device cuda:0]

Nécessite GPU + CosyVoice3 + dépendances (librosa, whisper, numpy, etc.).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, adaptive, cosyvoice_engine, text_fr, verifier
from engine.tagging import parse_texte, regrouper
from engine.voix import load_voix

# ── Texte de test (assez long pour forcer le découpage) ──────────────────────
TEXT_LONG = """\
[Astronogeek]: Dans cet épisode de démonstration, nous allons explorer les mécanismes \
fondamentaux de la synthèse vocale par clonage. La technologie CosyVoice3 utilise un \
modèle de neural qui apprend à reproduire le timbre et la prosodie d'un locuteur à \
partir d'un simple extrait audio de quelques secondes. C'est un domaine en pleine \
évolution qui promet de révolutionner la façon dont nous interagissons avec les machines.

Le principe est le suivant : on fournit un fichier audio de référence accompagné de sa \
transcription textuelle. Le modèle analyse les caractéristiques acoustiques de la voix \
et les associe au contenu linguistique. Ensuite, pour tout nouveau texte, il peut \
générer un audio qui sonne comme le locuteur original, tout en prononçant des phrases \
qu'il n'a jamais entendues.

Ce qui est fascinant, c'est la capacité du modèle à préserver l'identité vocale même \
sur de longs passages. Les défis restent nombreux : gestion des pauses naturelles, \
cohérence émotionnelle, et surtout la fidélité du contenu. On ne doit perdre aucun \
mot, aucune syllabe, dans le processus de synthèse.

La vérification par transcription joue un rôle crucial ici. On utilise Whisper pour \
transcrire l'audio généré et on compare le résultat avec le texte d'origine. Si des \
mots manquent, le bloc est automatiquement resplitté et régénéré. C'est ce qu'on \
appelle le découpage adaptatif, uneapproche qui garantit la complétude du contenu \
tout en minimisant le nombre de segments audio produits.

Pour évaluer la qualité, on fait varier plusieurs paramètres : la taille maximale \
des blocs en nombre de caractères, le seuil de couverture pour la vérification, et \
le modèle Whisper utilisé pour la transcription. Chaque paramètre a un impact sur \
le compromis entre vitesse de génération et qualité du résultat final.

La normalisation du texte en français est également essentielle. Les nombres doivent \
être lus correctement, les abbreviations développées, et la ponctuation respectée. \
CosyVoice3 gère naturellement le multilinguisme, mais un pré-traitement spécifique \
pour le français améliore significativement la qualité prosodique du résultat."""

# Texte plus court pour des tests rapides
TEXT_COURT = """\
[Astronogeek]: Dans cet épisode de démonstration, chaque réplique est portée par une voix différente. Ce qui suit reste attribué au même locuteur, l'astronome.

[Superama]: Tiens, c'est toi qui a pris ma place, ce matin ?

[Astronogeek]: Non non, je commente seulement la scène. La technologie, c'est aussi une affaire de patience.

[Gmilgram]: On n'apprend rien en restant dans sa zone de confort.

[Sylarticho]: Si vous me donnez une seconde chance, je ne la gâcherai pas.

[Micode]: Et je clôture en douceur cette démonstration de bout en bout."""


def split_sentences(text: str) -> List[str]:
    """Découpe le texte en phrases (pour mesurer la granularité)."""
    import re
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return sents or [text]


def bench_max_chars(
    text: str,
    voice,
    model,
    sr: int,
    max_chars_values: List[int],
    verify: bool = True,
    speed: float = 1.0,
) -> List[dict]:
    """Teste différentes valeurs de max_chars et mesure l'impact."""
    results = []
    for mc in max_chars_values:
        print(f"\n  max_chars={mc} ...", end=" ", flush=True)
        t0 = time.time()
        blocks = adaptive.build_blocks(text, max_chars=mc)
        n_blocks = len(blocks)
        avg_chars = sum(len(b) for b in blocks) / n_blocks if n_blocks else 0

        # Générer chaque bloc et mesurer
        total_audio_len = 0
        n_re_splits = 0
        total_coverage = 0.0
        for block_text in blocks:
            audio = adaptive.generate_block(
                block_text, str(voice.wav), voice.system_prompt,
                lambda t, _pw="", _pt="": cosyvoice_engine.synthesize(
                    t, str(voice.wav), voice.system_prompt, model, sr, speed=speed
                ),
                sr, verify=verify,
            )
            total_audio_len += len(audio)
            cov = verifier.coverage(block_text, audio, sr)
            total_coverage += cov

        elapsed = time.time() - t0
        avg_cov = total_coverage / n_blocks if n_blocks else 0
        avg_dur = (total_audio_len / sr) / n_blocks if n_blocks else 0

        results.append({
            "max_chars": mc,
            "n_blocks": n_blocks,
            "avg_chars_per_block": round(avg_chars, 1),
            "avg_coverage": round(avg_cov, 4),
            "avg_duration_s": round(avg_dur, 2),
            "total_duration_s": round(total_audio_len / sr, 2),
            "elapsed_s": round(elapsed, 1),
            "verify": verify,
        })
        print(f"{n_blocks} blocs, couv={avg_cov:.2%}, {elapsed:.1f}s")
    return results


def bench_verify_threshold(
    text: str,
    voice,
    model,
    sr: int,
    thresholds: List[float],
    max_chars: int = 600,
    speed: float = 1.0,
) -> List[dict]:
    """Teste différents seuils de vérification."""
    results = []
    original_threshold = config.VERIFY_THRESHOLD
    try:
        for thr in thresholds:
            config.VERIFY_THRESHOLD = thr
            print(f"\n  seuil={thr} ...", end=" ", flush=True)
            t0 = time.time()

            audio = adaptive.synthesize_verified(
                text, str(voice.wav), voice.system_prompt,
                lambda t, _pw="", _pt="": cosyvoice_engine.synthesize(
                    t, str(voice.wav), voice.system_prompt, model, sr, speed=speed
                ),
                sr, max_chars=max_chars, verify=True,
            )
            elapsed = time.time() - t0
            cov = verifier.coverage(text, audio, sr)
            n_blocks = len(adaptive.build_blocks(text, max_chars=max_chars))

            results.append({
                "threshold": thr,
                "coverage": round(cov, 4),
                "duration_s": round(len(audio) / sr, 2),
                "elapsed_s": round(elapsed, 1),
                "max_chars": max_chars,
            })
            print(f"couv={cov:.2%}, {elapsed:.1f}s")
    finally:
        config.VERIFY_THRESHOLD = original_threshold
    return results


def bench_verify_vs_no_verify(
    text: str,
    voice,
    model,
    sr: int,
    max_chars: int = 600,
    speed: float = 1.0,
) -> dict:
    """Compare vérification activée vs désactivée."""
    results = {}
    for label, do_verify in [("avec_verify", True), ("sans_verify", False)]:
        print(f"\n  {label} ...", end=" ", flush=True)
        t0 = time.time()
        audio = adaptive.synthesize_verified(
            text, str(voice.wav), voice.system_prompt,
            lambda t, _pw="", _pt="": cosyvoice_engine.synthesize(
                t, str(voice.wav), voice.system_prompt, model, sr, speed=speed
            ),
            sr, max_chars=max_chars, verify=do_verify,
        )
        elapsed = time.time() - t0
        cov = verifier.coverage(text, audio, sr)
        results[label] = {
            "coverage": round(cov, 4),
            "duration_s": round(len(audio) / sr, 2),
            "elapsed_s": round(elapsed, 1),
        }
        print(f"couv={cov:.2%}, {elapsed:.1f}s")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de fidélité VoiceBuilder")
    parser.add_argument("--voice", default=None, help="Nom de voix dans voix.txt (défaut: première)")
    parser.add_argument("--texte", default=None, help="Fichier texte (défaut: texte démo long)")
    parser.add_argument("--device", default="cuda:0", help="Device GPU/CPU")
    parser.add_argument("--speed", type=float, default=1.0, help="Vitesse de génération")
    parser.add_argument("--output", default=None, help="Fichier JSON de sortie (défaut: output/benchmark.json)")
    args = parser.parse_args(argv)

    config.ensure_dirs()

    # Charger les voix
    print("Chargement des voix...")
    voices = load_voix()
    if args.voice:
        voice = voices.get(args.voice)
    else:
        voice = list(voices)[0]
    print(f"  Voix : {voice.name} ({voice.wav})")

    # Préparer le texte
    if args.texte:
        text = Path(args.texte).read_text(encoding="utf-8")
    else:
        text = TEXT_LONG

    # Nettoyer le texte (enlever les balises de personnage pour le test unitaire)
    import re
    clean_text = re.sub(r"\[[^\]]+\]:\s*", "", text)
    clean_text = re.sub(r"\n\n+", "\n\n", clean_text).strip()

    n_phrases = len(split_sentences(clean_text))
    print(f"  Texte : {n_phrases} phrases, {len(clean_text)} caractères")

    # Charger le modèle
    print(f"\nChargement du modèle CosyVoice3 (device={args.device})...")
    model, sr = cosyvoice_engine.load(device=args.device)
    print(f"  Sample rate : {sr} Hz")

    results = {"voice": voice.name, "text_chars": len(clean_text), "text_phrases": n_phrases}

    # ── 1. Benchmark max_chars ────────────────────────────────────────────────
    print("\n═══ 1. Benchmark max_chars (vérif=ON, seuil=0.85) ═══")
    max_chars_values = [150, 250, 400, 600, 800, 1000, 1200]
    results["max_chars"] = bench_max_chars(
        clean_text, voice, model, sr, max_chars_values,
        verify=True, speed=args.speed,
    )

    # ── 2. Benchmark seuil Whisper ────────────────────────────────────────────
    print("\n═══ 2. Benchmark seuil Whisper (max_chars=600) ═══")
    thresholds = [0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 1.0]
    results["thresholds"] = bench_verify_threshold(
        clean_text, voice, model, sr, thresholds,
        max_chars=600, speed=args.speed,
    )

    # ── 3. Verify vs no-verify ────────────────────────────────────────────────
    print("\n═══ 3. Vérification ON vs OFF (max_chars=600) ═══")
    results["verify_comparison"] = bench_verify_vs_no_verify(
        clean_text, voice, model, sr, max_chars=600, speed=args.speed,
    )

    # ── Sauvegarder ───────────────────────────────────────────────────────────
    out_path = Path(args.output) if args.output else config.OUTPUT_DIR / "benchmark.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nRésultats sauvegardés : {out_path}")

    # ── Résumé ────────────────────────────────────────────────────────────────
    print("\n═══ RÉSUMÉ ═══")
    print("max_chars | Blocs | Couverture | Durée totale | Temps")
    print("----------|-------|------------|--------------|------")
    for r in results["max_chars"]:
        print(f"  {r['max_chars']:>5}   | {r['n_blocks']:>5} | {r['avg_coverage']:>8.2%}   | {r['total_duration_s']:>8.1f} s  | {r['elapsed_s']:>5.1f} s")

    print("\nSeuil  | Couverture | Durée")
    print("-------|------------|------")
    for r in results["thresholds"]:
        print(f"  {r['threshold']:.2f} | {r['coverage']:>8.2%}   | {r['duration_s']:>5.1f} s")

    vc = results["verify_comparison"]
    print(f"\nVérif ON  : couv={vc['avec_verify']['coverage']:.2%}, durée={vc['avec_verify']['duration_s']:.1f}s")
    print(f"Vérif OFF : couv={vc['sans_verify']['coverage']:.2%}, durée={vc['sans_verify']['duration_s']:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
