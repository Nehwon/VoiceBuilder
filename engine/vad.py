"""Détection d'activité vocale (VAD) légère, sans dépendance (numpy seul).

Usage : recaler automatiquement les limites d'un segment sur la parole
réelle (``create_voix``, onglet 🎙️ Voix) au lieu d'une sélection manuelle
approximative. Détection par énergie (trames 20 ms, seuil adaptatif,
hangover, durées minimales) — suffisante pour du recentrage de bornes,
pas pour de la diarisation.
"""
from __future__ import annotations

import numpy as np

TRAME_S = 0.02       # trames d'analyse (s)
SEUIL_PLANCHER_DB = -40.0  # sous ce niveau : toujours du silence
SEUIL_REL_DB = 12.0  # au-dessus de la médiane d'énergie : parole probable
HANGOVER_S = 0.25    # prolonge la parole (plosives, micro-pauses)
DUREE_MIN_S = 0.3    # segment de parole minimal retenu
FUSION_S = 0.35      # fusionne deux spans séparés par moins que ça
TOLERANCE_S = 1.0    # snap bornes seulement si proches (défaut)


def detecter_parole(audio: np.ndarray, sr: int,
                    seuil_relatif_db: float = SEUIL_REL_DB) -> list[tuple[float, float]]:
    """Renvoie les spans de parole ``[(start, end)]`` en secondes, triés."""
    y = np.asarray(audio, dtype=np.float32).ravel()
    if len(y) == 0:
        return []
    n = max(1, int(sr * TRAME_S))
    trames = y[: len(y) // n * n].reshape(-1, n)
    energie = np.sqrt(np.mean(trames ** 2, axis=1))
    plancher = 10.0 ** (SEUIL_PLANCHER_DB / 20.0)
    # 10e percentile (pas la médiane : elle s'effondre quand la parole
    # occupe une large part du fichier) × ratio relatif.
    bruit = float(np.percentile(energie, 10))
    seuil = max(plancher, bruit * 10.0 ** (seuil_relatif_db / 20.0))
    parle = energie >= seuil
    if parle.mean() < 0.02 and energie.max() > plancher * 4:
        # Quasi rien détecté mais signal fort : parole dense (le p10 est
        # déjà de la parole) → seuil relatif à la crête.
        seuil = max(plancher, float(energie.max()) * 0.05)
        parle = energie >= seuil
    # hangover : comble les micro-coupures
    hang = max(1, int(HANGOVER_S / TRAME_S))
    idx = np.flatnonzero(parle)
    for i in idx:
        parle[i:i + hang + 1] = True
    spans: list[tuple[float, float]] = []
    deb = None
    for i, p in enumerate(parle):
        if p and deb is None:
            deb = i
        elif not p and deb is not None:
            spans.append((deb * TRAME_S, (i) * TRAME_S))
            deb = None
    if deb is not None:
        spans.append((deb * TRAME_S, len(parle) * TRAME_S))
    # fusion des quasi-jointifs + filtre durée minimale
    fusionnes: list[tuple[float, float]] = []
    for s, e in spans:
        if fusionnes and s - fusionnes[-1][1] <= FUSION_S:
            fusionnes[-1] = (fusionnes[-1][0], e)
        else:
            fusionnes.append((s, e))
    return [(s, e) for s, e in fusionnes if e - s >= DUREE_MIN_S]


def ajuster_segment(spans: list[tuple[float, float]], start: float, stop: float,
                    tolerance: float = TOLERANCE_S) -> dict:
    """Recale ``[start, stop]`` sur la parole : début avancé au premier span,
    fin reculée au dernier span (vers l'intérieur, jamais hors bornes).

    Ne touche une borne que si le bord de parole est à ``tolerance`` (s) près ;
    sinon la borne d'origine est gardée. Renvoie le segment ajusté + drapeaux.
    """
    res = {"start": start, "stop": stop,
           "ajuste_debut": False, "ajuste_fin": False}
    if stop <= start or not spans:
        return res
    premiers = [s for s, _ in spans if start - tolerance <= s <= stop]
    if premiers:
        nouveau = max(start, min(premiers))
        if nouveau > start:
            res["start"] = round(nouveau, 2)
            res["ajuste_debut"] = True
    derniers = [e for _, e in spans if start <= e <= stop + tolerance]
    if derniers:
        nouveau = min(stop, max(derniers))
        if nouveau < stop and nouveau > res["start"]:
            res["stop"] = round(nouveau, 2)
            res["ajuste_fin"] = True
    return res
