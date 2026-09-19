"""M17.2 — Banc A/B de prompts par personnage (Palier 0, curation).

Le même paragraphe FR de référence (nombres, date, dialogue, 1 émotion —
``PROJET_FINE.md`` §3.4) est synthétisé avec chaque segment candidat d'un
personnage (variantes ``_2``/``_3``, versions ``_clean``) : ``coverage``
Whisper + RTF + écoute comparative. Le gagnant peut devenir la référence
dans ``voix.txt`` (``promouvoir()``, avec sauvegarde ``voix.txt.bak``).

Utilisé par ``tools/bench_prompts.py`` (CLI) et l'onglet 🎙️ Voix (GUI).
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from . import config, cosyvoice_engine, multi, verifier
from .voix import Voices, base_nom, grouper_candidats

# Paragraphe FR de référence (validé) : nombres, date, dialogue, 1 émotion.
PARAGRAPHE_REF = (
    "Le 14 juillet 2025, à 8 h 30 précises, 1 247 spectateurs s'étaient "
    "massés devant la grande scène du festival. — Tu as vu les résultats ? "
    "demanda Léa, le cœur battant. — Oui ! répondit Mehdi, <|HAPPY|> on a "
    "gagné la troisième place avec 97,5 points ! La foule applaudit pendant "
    "près de deux minutes."
)


def slug(nom: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", nom).strip("_") or "voix"


def bench_personnage(
    base: str,
    candidats: List[str],
    voix: Voices,
    model,
    sr: int,
    out_dir: Path,
    speed: Optional[float] = None,
    progress: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Synthétise le paragraphe de référence avec chaque candidat.

    Mesures par candidat : ``coverage`` Whisper (≥ 0.85 attendu) + RTF
    (temps synthèse / durée audio). Les WAV sont écrits dans ``out_dir``
    pour l'écoute comparative. Gagnant : meilleure couverture, puis RTF.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lignes = []
    for nom in candidats:
        v = voix.get(nom)
        t0 = time.time()
        # verify=False : on compare les prompts bruts, la couverture est
        # mesurée après (même métrique pour tous).
        audio = multi.synth_bloc(v, PARAGRAPHE_REF, model, sr,
                                 speed=speed, verify=False)
        duree_gen = time.time() - t0
        duree = len(audio) / sr
        couverture = verifier.coverage(PARAGRAPHE_REF, np.asarray(audio), sr)
        rtf = duree_gen / duree if duree > 0 else 0.0
        wav = out_dir / f"{slug(nom)}.wav"
        cosyvoice_engine.save(np.asarray(audio), sr, str(wav))
        ligne = {"candidat": nom, "coverage": round(couverture, 4),
                 "rtf": round(rtf, 3), "duree": round(duree, 2),
                 "duree_gen": round(duree_gen, 1), "wav": str(wav)}
        lignes.append(ligne)
        if progress:
            progress({"candidat": nom, "index": len(lignes),
                      "total": len(candidats), **ligne})
    gagnant = max(lignes, key=lambda l: (l["coverage"], -l["rtf"]))["candidat"]
    return {"personnage": base, "paragraphe": PARAGRAPHE_REF,
            "lignes": lignes, "gagnant": gagnant}


def promouvoir(voix_path: Path, base: str, gagnant: str) -> dict:
    """Le gagnant devient la référence du personnage dans ``voix.txt``.

    La ligne ``[base]`` pointe désormais vers les fichiers du gagnant (les
    réglages éventuels de la ligne de base sont conservés) ; l'entrée du
    gagnant est inchangée. Sauvegarde préalable : ``voix.txt.bak`` (écrasée).
    """
    voix_path = Path(voix_path)
    lignes = voix_path.read_text(encoding="utf-8").splitlines()
    idx_base = idx_win = None
    for i, ln in enumerate(lignes):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        nom = s.split(",", 1)[0].strip()
        if nom == f"[{base}]":
            idx_base = i
        if nom == f"[{gagnant}]":
            idx_win = i
    if idx_base is None:
        raise ValueError(f"Personnage introuvable dans voix.txt : {base}")
    if idx_win is None:
        raise ValueError(f"Candidat introuvable dans voix.txt : {gagnant}")
    champs_win = [p.strip() for p in lignes[idx_win].split(",")]
    champs_base = [p.strip() for p in lignes[idx_base].split(",")]
    if len(champs_win) < 3:
        raise ValueError(f"Entrée gagnante sans couple wav+txt : {lignes[idx_win]}")
    # wav + txt du gagnant, reste de la ligne de base inchangé.
    nouvelle = [champs_base[0], champs_win[1], champs_win[2]] + champs_base[3:]
    bak = voix_path.with_name(voix_path.name + ".bak")
    shutil.copy2(voix_path, bak)
    lignes[idx_base] = ", ".join(nouvelle)
    voix_path.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return {"personnage": base, "gagnant": gagnant, "ligne": lignes[idx_base],
            "sauvegarde": str(bak)}
