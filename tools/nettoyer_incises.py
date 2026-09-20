#!/usr/bin/env python3
"""M20 — Nettoyage des incises de dialogue (CLI).

Détecte les incises (``dit-il``, ``murmura-t-elle``, ``dit Lambda``),
retire celles sans intérêt vocal (verbes de parole purs), bascule les
incises d'action en narration, et propose les personnages manquants
pour le ``.map`` du document (jamais ``voix.txt``).

Usage :
    python -m tools.nettoyer_incises texte/chapitre.md --dry-run --diff
    python -m tools.nettoyer_incises texte/chapitre.md --in-place --auto-map
    python -m tools.nettoyer_incises texte/chapitre.md -o texte/chapitre_net.md
"""
from __future__ import annotations

import argparse
import csv
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config
from engine.incises import nettoyer, synchroniser_map


def _lire_map(map_path: Path) -> dict:
    mapping: dict[str, str] = {}
    if not map_path.exists():
        return mapping
    with open(map_path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return mapping
    header = [c.strip().lower() for c in rows[0]]
    try:
        i_pers, i_voix = header.index("personnage"), header.index("voix")
    except ValueError:
        return mapping
    for row in rows[1:]:
        if len(row) >= 2 and row[i_pers].strip() and row[i_voix].strip():
            mapping[row[i_pers].strip()] = row[i_voix].strip()
    return mapping


def _ecrire_map(map_path: Path, mapping: dict) -> None:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    with open(map_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["voix", "personnage"])
        for pers, vx in mapping.items():
            if pers.strip() and vx:
                w.writerow([vx, pers])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Nettoyage des incises (M20)")
    p.add_argument("texte", help="Fichier .md/.txt (roman brut ou déjà taggé)")
    p.add_argument("-o", "--out", default=None, help="Fichier de sortie (défaut: stdout)")
    p.add_argument("--mode", default="auto",
                   choices=["auto", "import_roman", "nettoyer_tagge"])
    p.add_argument("--keep-action", default="narration",
                   choices=["narration", "garder", "supprimer"],
                   help="Sort des incises d'action (défaut: narration)")
    p.add_argument("--auto-map", action="store_true",
                   help="Ajoute les nouveaux personnages au .map (voix par défaut)")
    p.add_argument("--voix-defaut", default="Narrateur")
    p.add_argument("--narrateur-je", default=None,
                   help="Personnage incarnant le « je » (ex. Michel)")
    p.add_argument("--in-place", action="store_true",
                   help="Écrase le fichier d'entrée (+ .map si --auto-map)")
    p.add_argument("--dry-run", action="store_true",
                   help="N'écrit rien, affiche les stats (+ diff avec --diff)")
    p.add_argument("--diff", action="store_true", help="Affiche le diff avant/après")
    p.add_argument("--texte-dir", default=str(config.TEXTE_DIR))
    args = p.parse_args(argv)

    src = Path(args.texte)
    if not src.is_absolute():
        cand = Path(args.texte_dir) / src
        src = cand if cand.exists() else src
    if not src.exists():
        print(f"Fichier introuvable : {src}", file=sys.stderr)
        return 1
    original = src.read_text(encoding="utf-8")
    map_path = src.with_suffix(".map")
    mapping = _lire_map(map_path)

    res = nettoyer(original, mode=args.mode, keep_action=args.keep_action,
                   mapping=mapping, voix_defaut=args.voix_defaut,
                   narrateur_je=args.narrateur_je)
    fusion = synchroniser_map(mapping, res.nouveaux_personnages,
                              voix_defaut=args.voix_defaut)

    print(f"Incises : {res.stats['incises']} "
          f"(parole retirées : {res.stats['parole_retirees']}, "
          f"actions→narration : {res.stats['actions_narration']})")
    if res.nouveaux_personnages:
        print(f"Nouveaux personnages : {', '.join(res.nouveaux_personnages)}"
              f" → {'ajoutés au .map' if args.auto_map and not args.dry_run else 'proposés (voix ' + args.voix_defaut + ')'}")
    else:
        print("Aucun nouveau personnage.")
    if args.diff or args.dry_run:
        for ligne in difflib.unified_diff(
                original.splitlines(), res.texte.splitlines(),
                "avant", "après", lineterm=""):
            print(ligne)
    if args.dry_run:
        return 0
    dest = src if args.in_place else (Path(args.out) if args.out else None)
    if dest is not None:
        dest.write_text(res.texte, encoding="utf-8")
        print(f"Écrit : {dest}")
    else:
        print(res.texte, end="")
    if args.auto_map and res.nouveaux_personnages:
        _ecrire_map(map_path, fusion)
        print(f".map mis à jour : {map_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
