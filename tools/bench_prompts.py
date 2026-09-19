#!/usr/bin/env python3
"""M17.2 — Banc A/B de prompts par personnage (CLI).

Usage :
    python tools/bench_prompts.py [--personnage NOM] [--promouvoir]
        [--device cuda:0] [--out output/bench]

Le paragraphe FR de référence (nombres, date, dialogue, 1 émotion) est
synthétisé avec chaque segment candidat (variantes ``_2``/``_3``, versions
``_clean``) : ``coverage`` Whisper + RTF + WAV d'écoute comparative dans
``output/bench/<personnage>/``. ``--promouvoir`` fait du gagnant la référence
dans ``voix.txt`` (sauvegarde ``voix.txt.bak``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import bench, config, multi
from engine.voix import load_voix


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M17.2 — Banc A/B de prompts")
    ap.add_argument("--personnage", default=None,
                    help="Ne bencher qu'un personnage (nom de base)")
    ap.add_argument("--promouvoir", action="store_true",
                    help="Le gagnant devient la référence dans voix.txt (backup .bak)")
    ap.add_argument("--device", default="cuda:0", help="Device CosyVoice")
    ap.add_argument("--out", default=None, help="Dossier des WAV (défaut: output/bench)")
    args = ap.parse_args(argv)

    try:
        voix = load_voix()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}")
        return 1
    groupes = bench.grouper_candidats(voix.names())
    if args.personnage:
        if args.personnage not in groupes:
            print(f"❌ Personnage inconnu : {args.personnage} "
                  f"(bases : {', '.join(groupes)})")
            return 1
        groupes = {args.personnage: groupes[args.personnage]}

    out_racine = Path(args.out) if args.out else config.OUTPUT_DIR / "bench"
    print(f"Banc M17.2 — {len(groupes)} personnage(s), device {args.device}\n"
          f"Référence : {bench.PARAGRAPHE_REF[:60]}…\n")
    print("Chargement du modèle…")
    model, sr = multi.load(device=args.device, fp16=False)

    gagnants: dict[str, str] = {}
    for base, candidats in groupes.items():
        print(f"[{base}] {len(candidats)} candidat(s) : {', '.join(candidats)}")
        if len(candidats) < 2:
            print("  (candidat unique : rien à comparer)\n")
            continue
        res = bench.bench_personnage(base, candidats, voix, model, sr,
                                     out_racine / bench.slug(base))
        for l in res["lignes"]:
            marque = " ★" if l["candidat"] == res["gagnant"] else ""
            print(f"  {l['candidat']:<28} couv {l['coverage']:.0%} · "
                  f"RTF {l['rtf']:.2f} · {l['duree']:.1f}s{marque}")
        print(f"  ⇒ gagnant : {res['gagnant']} (WAV : {out_racine / bench.slug(base)})\n")
        gagnants[base] = res["gagnant"]

    if args.promouvoir:
        if not gagnants:
            print("Rien à promouvoir.")
            return 0
        voix_path = config.VOIX_FILE
        for base, g in gagnants.items():
            r = bench.promouvoir(voix_path, base, g)
            print(f"[{base}] promu : {r['ligne']} (backup : {r['sauvegarde']})")
    elif gagnants:
        print("Astuce : relance avec --promouvoir pour faire des gagnants "
              "les références dans voix.txt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
