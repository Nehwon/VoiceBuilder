#!/usr/bin/env python3
"""M17.3 — Nettoyage en lot des voix (Palier 0, curation).

Usage :
    python tools/nettoyer_voix.py --tout [--voix NOM] [--promouvoir]
        [--forcer] [--mode auto]

Applique le pipeline M13.0 (Demucs + DeepFilterNet, ``engine/enhance.py``) à
chaque voix : produit ``<tige>_clean.wav`` (+ ``.txt`` recopié) et l'entrée
``[Nom_clean]`` dans ``voix.txt``. Comparaison avant/après (``coverage``
Whisper + SNR, écoute des deux WAV côte à côte) ; avec ``--promouvoir``, le
gagnant devient la référence (``bench.promouvoir()``, backup
``voix.txt.bak``).

Règle de victoire du ``_clean`` : couverture conservée (tolérance 2 pts) ET
SNR non dégradée ; sinon verdict indécis (écoute manuelle).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_voix import analyser_wav
from engine import bench, enhance, verifier
from engine.voix import load_voix

COUV_TOL = 0.02  # tolérance sur la couverture (bruit Whisper)


def _couverture(txt: Path, wav: Path):
    """Coverage Whisper du txt sur le wav (None si échec)."""
    import soundfile as sf
    try:
        y, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        return verifier.coverage(
            txt.read_text(encoding="utf-8"), y.mean(axis=1).astype("float32"), sr)
    except Exception:  # noqa: BLE001
        return None


def nettoyer_une(nom: str, wav: Path, txt: Path, mode: str, forcer: bool) -> dict:
    """Nettoie une voix → fichiers _clean + entrée voix.txt. Idempotent."""
    tige = wav.stem
    wav_c = wav.with_name(f"{tige}_clean.wav")
    txt_c = wav.with_name(f"{tige}_clean.txt")
    res = {"nom": nom, "clean": f"{nom}_clean", "wav_clean": str(wav_c)}
    if wav_c.exists() and txt_c.exists() and not forcer:
        res["statut"] = "déjà fait"
        return res

    def _prog(etape, pct):
        print(f"  [{nom}] {etape} {pct:.0f}%", flush=True)

    enhance.nettoyer(wav, wav_c, mode=mode, progress=_prog)
    shutil.copy2(txt, txt_c)
    res["statut"] = "nettoyé"
    return res


def comparer(nom: str, wav: Path, txt: Path, wav_c: Path) -> dict:
    """Avant/après : coverage Whisper + SNR ; gagnant = clean conservant
    le contenu (tolérance) sans dégrader le SNR."""
    m0, m1 = analyser_wav(wav), analyser_wav(wav_c)
    c0, c1 = _couverture(txt, wav), _couverture(txt, wav_c)
    gagnant, pourquoi = None, ""
    if c0 is None or c1 is None:
        pourquoi = "métrique manquante (écoute manuelle)"
    elif c1 >= c0 - COUV_TOL and m1["snr_db"] >= m0["snr_db"]:
        gagnant = "clean"
        pourquoi = f"couv {c0:.0%}→{c1:.0%}, SNR {m0['snr_db']:.1f}→{m1['snr_db']:.1f} dB"
    elif c1 < c0 - COUV_TOL:
        gagnant = "original"
        pourquoi = f"contenu perdu (couv {c0:.0%}→{c1:.0%})"
    else:
        gagnant = "original"
        pourquoi = f"SNR dégradée ({m0['snr_db']:.1f}→{m1['snr_db']:.1f} dB)"
    return {"couv_avant": c0, "couv_apres": c1,
            "snr_avant": round(m0["snr_db"], 1), "snr_apres": round(m1["snr_db"], 1),
            "gagnant": gagnant, "pourquoi": pourquoi}


def assurer_entree(voix_path: Path, nom_clean: str, wav_c: Path, txt_c: Path) -> bool:
    """Ajoute l'entrée [Nom_clean] à voix.txt si absente (True si ajoutée)."""
    lignes = voix_path.read_text(encoding="utf-8").splitlines()
    noms = {l.strip().split(",", 1)[0].strip()
            for l in lignes if l.strip() and not l.strip().startswith("#")}
    if f"[{nom_clean}]" in noms:
        return False
    base = Path(voix_path).parent
    try:
        rel_w = wav_c.relative_to(base)
    except ValueError:
        rel_w = wav_c
    try:
        rel_t = txt_c.relative_to(base)
    except ValueError:
        rel_t = txt_c
    with open(voix_path, "a", encoding="utf-8") as f:
        f.write(f"[{nom_clean}], {rel_w}, {rel_t}\n")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M17.3 — Nettoyage en lot des voix")
    ap.add_argument("--tout", action="store_true", help="Traiter toutes les voix")
    ap.add_argument("--voix", default=None, help="Ne traiter qu'une voix")
    ap.add_argument("--promouvoir", action="store_true",
                    help="Les gagnants deviennent références (backup voix.txt.bak)")
    ap.add_argument("--forcer", action="store_true",
                    help="Refaire même si le _clean existe déjà")
    ap.add_argument("--mode", default="auto",
                    help="Mode Demucs : auto (défaut), cuda_fp16, cuda_fp32, cpu")
    args = ap.parse_args(argv)
    if not args.tout and not args.voix:
        ap.error("précise --tout ou --voix NOM")

    from engine import config
    try:
        voix = load_voix()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}")
        return 1
    noms = voix.names()
    if args.voix:
        cible = args.voix.strip().strip("[]").lower()
        noms = [n for n in noms if n.lower() == cible or n.lower() == cible + "_clean"]
        if not noms:
            print(f"❌ Voix inconnue : {args.voix}")
            return 1
    # ne jamais nettoyer un _clean (on part toujours de l'original)
    noms = [n for n in noms if not n.lower().endswith("_clean")]

    voix_path = Path(config.VOIX_FILE)
    print(f"Nettoyage M17.3 — {len(noms)} voix, mode {args.mode}\n")
    bilan: dict[str, int] = {}
    for nom in noms:
        v = voix.get(nom)
        try:
            r = nettoyer_une(nom, v.wav, v.txt, args.mode, args.forcer)
        except Exception as exc:  # noqa: BLE001
            print(f"[{nom}] ❌ {exc}")
            bilan["erreur"] = bilan.get("erreur", 0) + 1
            continue
        wav_c = Path(r["wav_clean"])
        txt_c = wav_c.with_name(wav_c.stem + ".txt")
        ajout = assurer_entree(voix_path, r["clean"], wav_c, txt_c)
        c = comparer(nom, v.wav, v.txt, wav_c)
        etat = r["statut"] + (", entrée ajoutée" if ajout else "")
        c0 = "?" if c["couv_avant"] is None else f"{c['couv_avant']:.0%}"
        c1 = "?" if c["couv_apres"] is None else f"{c['couv_apres']:.0%}"
        print(f"[{nom}] {etat} : couv {c0}→{c1}, "
              f"SNR {c['snr_avant']}→{c['snr_apres']} dB")
        if c["gagnant"] == "clean":
            print(f"  ⇒ gagnant : clean ({c['pourquoi']})")
            bilan["clean"] = bilan.get("clean", 0) + 1
            if args.promouvoir:
                pr = bench.promouvoir(voix_path, nom, r["clean"])
                print(f"  ⇒ promu : {pr['ligne']}")
                bilan["promu"] = bilan.get("promu", 0) + 1
        elif c["gagnant"] == "original":
            print(f"  ⇒ gagnant : original ({c['pourquoi']})")
            bilan["original"] = bilan.get("original", 0) + 1
        else:
            print(f"  ⇒ indécis ({c['pourquoi']}) — écoute manuelle")
            bilan["indécis"] = bilan.get("indécis", 0) + 1
    print("\nRésumé : " + " · ".join(f"{k} : {v}" for k, v in sorted(bilan.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
