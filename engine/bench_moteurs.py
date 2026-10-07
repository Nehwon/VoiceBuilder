"""Comparaison de moteurs TTS sur le paragraphe FR de référence (M19.0).

Chaque moteur est une fonction ``fn(texte) -> (audio_np, sample_rate)``.
Métriques identiques pour tous : coverage Whisper, RTF, WAV réécoutable.
Décision selon PROJET_FINE.md §4 : n'intégrer que sur victoire mesurée
+ écoute aveugle (grille hors code).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict

import numpy as np

from . import verifier
from .bench import PARAGRAPHE_REF
from . import omnivoice_engine

SynthFn = Callable[[str], tuple[np.ndarray, int]]
SEUIL_COVERAGE = 0.85


def comparer(moteurs: Dict[str, SynthFn], out_dir: str | Path,
             progress=None) -> dict:
    """Fait synthétiser PARAGRAPHE_REF à chaque moteur, retourne le verdict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lignes = []
    for nom, fn in moteurs.items():
        t0 = time.time()
        audio, sr = fn(PARAGRAPHE_REF)
        duree_gen = time.time() - t0
        audio = np.asarray(audio, dtype=np.float32)
        duree = len(audio) / sr
        couverture = verifier.coverage(PARAGRAPHE_REF, audio, sr)
        rtf = duree_gen / duree if duree > 0 else 0.0
        wav = out_dir / f"moteur-{nom}.wav"
        omnivoice_engine.save(audio, sr, str(wav))
        ligne = {"moteur": nom, "coverage": round(float(couverture), 4),
                 "rtf": round(float(rtf), 3), "duree": round(float(duree), 2),
                 "duree_gen": round(float(duree_gen), 1), "wav": str(wav)}
        lignes.append(ligne)
        if progress:
            progress({"moteur": nom, "index": len(lignes),
                      "total": len(moteurs), **ligne})
    admissibles = [l for l in lignes if l["coverage"] >= SEUIL_COVERAGE]
    pool = admissibles if admissibles else lignes
    gagnant = max(pool, key=lambda l: (l["coverage"], -l["rtf"]))["moteur"]
    return {"paragraphe": PARAGRAPHE_REF, "seuil_coverage": SEUIL_COVERAGE,
            "lignes": lignes, "admissibles": [l["moteur"] for l in admissibles],
            "gagnant": gagnant}
