#!/usr/bin/env python3
"""M17.1 — Audit qualité des voix (Palier 0, curation).

Usage :
    python tools/audit_voix.py [--voix NOM] [--sans-whisper]

Pour chaque entrée de ``voix/voix.txt`` : durée (alerte hors 5–30 s),
niveau/SNR, silences dominants, écrêtage ; retranscription Whisper du
``.wav`` prompt + diff mot à mot vs ``.txt`` (mots divergents ou manquants
= transcription à recurer, ``PROJET_FINE.md`` §2 point 3).

Verdict par voix (le plus grave l'emporte) : ``OK`` / ``à recurer`` (txt)
/ ``à ré-extraire`` (wav) / ``à nettoyer`` (bruit/musique → M13.0).
Sortie console uniquement.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import verifier
from engine.voix import _strip_timestamps, load_voix

# Seuils simples (cf. TODO M17.1) — volontairement non paramétrables.
DUREE_MIN, DUREE_MAX = 5.0, 30.0       # plage idéale d'un prompt de clonage
DUREE_CRIT_MIN, DUREE_CRIT_MAX = 3.0, 60.0  # hors de ça : segment à ré-extraire
SEUIL_SILENCE_DB = -40.0               # trame < seuil => silence (20 ms)
SILENCE_DOMINANT_PCT = 60.0            # au-delà : segment à ré-extraire
ECRET_PCT_CRIT = 5.0                   # % d'échantillons à ±0.99 : wav à ré-extraire
SNR_NETTOYER_DB = 10.0                 # en dessous : bruit → M13.0
COUVERTURE_MIN = 0.85                  # mots du txt retrouvés (même seuil que verify)


def _db(x: float) -> float:
    return 20.0 * np.log10(max(x, 1e-12))


def analyser_wav(wav: Path) -> dict:
    """Niveau, écrêtage, silences, SNR estimée (énergie voix vs silences)."""
    import soundfile as sf
    y, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    duree = len(y) / sr
    rms = float(np.sqrt(np.mean(y ** 2)))
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    ecret = float(np.mean(np.abs(y) >= 0.99) * 100.0) if len(y) else 0.0
    # trames de 20 ms : part sous le seuil de silence
    n = max(1, int(sr * 0.02))
    trames = y[: len(y) // n * n].reshape(-1, n)
    e_trame = np.sqrt(np.mean(trames ** 2, axis=1))
    est_sil = e_trame < 10.0 ** (SEUIL_SILENCE_DB / 20.0)
    silence_pct = float(est_sil.mean() * 100.0)
    e_voix = float(np.mean(e_trame[~est_sil] ** 2)) if (~est_sil).any() else 0.0
    e_sil = float(np.mean(e_trame[est_sil] ** 2)) if est_sil.any() else 0.0
    snr = 10.0 * np.log10(e_voix / max(e_sil, 1e-12)) if e_voix > 0 else 0.0
    return {"sr": sr, "duree": duree, "rms_db": _db(rms), "peak_db": _db(peak),
            "ecret_pct": ecret, "silence_pct": silence_pct,
            "snr_db": min(snr, 60.0), "audio": y.astype(np.float32)}


def comparer_transcription(ref_txt: str, hyp: str) -> dict:
    """Diff mot à mot (normalisé, horodatages ignorés comme au parsing voix)."""
    ref = verifier.normalize(_strip_timestamps(ref_txt)).split()
    h = verifier.normalize(hyp).split()
    if not ref:
        return {"couverture": 0.0, "manquants": [], "divergents": [], "nb_ref": 0}
    dans_hyp = set(h)
    manquants = [w for w in dict.fromkeys(ref) if w not in dans_hyp]
    sm = difflib.SequenceMatcher(None, ref, h, autojunk=False)
    divergents = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            divergents.extend(f"{a}→{b}" for a, b in zip(ref[i1:i2], h[j1:j2]))
    couverture = (len(ref) - len(manquants)) / len(ref)
    return {"couverture": couverture, "manquants": manquants,
            "divergents": divergents, "nb_ref": len(ref)}


def auditer(nom: str, wav: Path, txt: Path, sans_whisper: bool) -> dict:
    """Audite une voix, renvoie métriques + verdict."""
    met = analyser_wav(wav)
    txt_brut = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
    txt_net = _strip_timestamps(txt_brut)  # même nettoyage qu'au parsing voix
    res = {"nom": nom, "wav": str(wav), "txt": str(txt), **met,
           "nb_mots_txt": len(txt_net.split())}
    # --- verdict (priorité : ré-extraire > nettoyer > recurer > OK)
    d, e, s, snr = met["duree"], met["ecret_pct"], met["silence_pct"], met["snr_db"]
    if d < DUREE_CRIT_MIN or d > DUREE_CRIT_MAX or e >= ECRET_PCT_CRIT \
            or s >= SILENCE_DOMINANT_PCT:
        res["verdict"] = "à ré-extraire"
    elif snr < SNR_NETTOYER_DB:
        res["verdict"] = "à nettoyer"
    else:
        res["verdict"] = "OK"
    # --- Whisper : diff vs txt (recure uniquement si le wav est sain)
    if sans_whisper:
        res["whisper"] = None
        return res
    hyp = verifier.transcribe(met["audio"], met["sr"])
    cmp = comparer_transcription(txt_net, hyp)
    res["whisper"] = {"couverture": round(cmp["couverture"], 3),
                      "manquants": cmp["manquants"][:10],
                      "nb_manquants": len(cmp["manquants"]),
                      "divergents": cmp["divergents"][:10],
                      "nb_divergents": len(cmp["divergents"])}
    if res["verdict"] == "OK" and cmp["couverture"] < COUVERTURE_MIN:
        res["verdict"] = "à recurer"
    return res


def afficher(r: dict) -> None:
    m = r
    print(f"[{m['nom']}] {m['duree']:.1f}s · {m['sr']}Hz · "
          f"rms {m['rms_db']:.1f}dB · peak {m['peak_db']:.1f}dB · "
          f"écrêt {m['ecret_pct']:.1f}% · silence {m['silence_pct']:.0f}% · "
          f"SNR {m['snr_db']:.1f}dB")
    alertes = []
    if not DUREE_MIN <= m["duree"] <= DUREE_MAX:
        alertes.append(f"durée hors {DUREE_MIN:.0f}–{DUREE_MAX:.0f}s")
    if m["whisper"] is None:
        alertes.append("whisper ignoré")
    else:
        w = m["whisper"]
        print(f"  txt {m['nb_mots_txt']} mots → couverture {w['couverture'] * 100:.0f}% · "
              f"manquants {w['nb_manquants']} · divergents {w['nb_divergents']}")
        if w["manquants"]:
            print(f"  manquants : {', '.join(w['manquants'])}")
        if w["divergents"]:
            print(f"  divergents : {', '.join(w['divergents'])}")
        if w["couverture"] < COUVERTURE_MIN:
            alertes.append(f"couverture txt {w['couverture'] * 100:.0f}% < 85%")
    if alertes:
        print(f"  ⚠ {'; '.join(alertes)}")
    print(f"  ⇒ {m['verdict']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M17.1 — Audit qualité des voix")
    ap.add_argument("--voix", default=None, help="N'analyser qu'une voix (nom, sans crochets)")
    ap.add_argument("--sans-whisper", action="store_true",
                    help="Mode rapide : métriques audio seules, sans retranscription")
    args = ap.parse_args(argv)

    try:
        voix = load_voix()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {exc}")
        return 1
    noms = voix.names()
    if args.voix:
        cible = args.voix.strip().strip("[]").lower()
        noms = [n for n in noms if n.lower() == cible]
        if not noms:
            print(f"❌ Voix inconnue : {args.voix} (voix.txt : {', '.join(voix.names())})")
            return 1

    print(f"Audit M17.1 — {len(noms)} voix"
          + (" (sans Whisper)" if args.sans_whisper else " (Whisper small, FR)") + "\n")
    verdicts: dict[str, int] = {}
    for n in noms:
        v = voix.get(n)
        try:
            r = auditer(n, v.wav, v.txt, args.sans_whisper)
        except Exception as exc:  # noqa: BLE001
            print(f"[{n}] ❌ {exc}")
            verdicts["erreur"] = verdicts.get("erreur", 0) + 1
            continue
        afficher(r)
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    print("\nRésumé : " + " · ".join(f"{k} : {v}" for k, v in sorted(verdicts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
