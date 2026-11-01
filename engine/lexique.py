"""Lexique de prononciation par document (VoiceBuilder, branche omni).

Un document ``texte/<nom>.md`` peut avoir son lexique
``texte/<nom>.lexique`` — une règle par ligne::

    Ben => Bène
    # commentaire (ignoré)

Le lexique est appliqué en toute première étape de
``text_fr.normalize()`` (avant dates/heures/nombres) puis la substitution
suit le pipeline normal. Seul le texte à synthétiser est substitué :
ni le prompt de la voix, ni le ``.md`` d'origine, ni les blocs affichés
ne sont modifiés.

L'application se fait en une passe unique (alternance triée par longueur
décroissante) : pas de substitutions en chaîne (``A => B`` + ``B => C``
ne donne pas ``C``) et pas de remplacement partiel (mots entiers
uniquement, insensible à la casse).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from . import config

#: Extension du fichier lexique posé à côté du document (même dossier).
EXTENSION = ".lexique"

#: Séparateur mot / prononciation de remplacement.
SEPARATEUR = "=>"

#: Garde-fous (fichier édité à la main, jamais de plantage dessus).
MAX_REGLES = 200
MAX_MOT = 60
MAX_REMPLACEMENT = 120

#: Une règle : (mot exact, graphie de remplacement).
Regle = Tuple[str, str]


def analyser(contenu: str) -> Tuple[List[Regle], List[str]]:
    """Valide le contenu brut d'un lexique.

    Renvoie ``(règles, erreurs)`` — les lignes vides et ``#…`` sont
    ignorées, les lignes fautives sont signalées ``L<n> : …`` sans
    bloquer les valides.
    """
    regles: List[Regle] = []
    erreurs: List[str] = []
    if not contenu or not contenu.strip():
        return regles, erreurs
    for i, brute in enumerate(contenu.splitlines(), 1):
        ligne = brute.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if SEPARATEUR not in ligne:
            erreurs.append(f"L{i} : séparateur « {SEPARATEUR} » manquant "
                           f"(attendu : Mot {SEPARATEUR} prononciation).")
            continue
        mot, remplacement = (p.strip() for p in ligne.split(SEPARATEUR, 1))
        if not mot or not remplacement:
            erreurs.append(f"L{i} : mot ou prononciation vide.")
            continue
        if len(mot) > MAX_MOT:
            erreurs.append(f"L{i} : mot trop long (max {MAX_MOT} caractères).")
            continue
        if len(remplacement) > MAX_REMPLACEMENT:
            erreurs.append(f"L{i} : prononciation trop longue "
                           f"(max {MAX_REMPLACEMENT} caractères).")
            continue
        regles.append((mot, remplacement))
        if len(regles) > MAX_REGLES:
            erreurs.append(f"Limite de {MAX_REGLES} règles dépassée "
                           f"(suite ignorée).")
            break
    return regles, erreurs


def appliquer(texte: str, regles: Optional[List[Regle]]) -> str:
    """Substitue les mots du lexique dans ``texte`` (une passe, mots entiers).

    Insensible à la casse ; la plus longue règle gagne en cas de
    chevauchement (``New York`` avant ``York``).
    """
    if not texte or not regles:
        return texte
    table = {}
    for mot, remplacement in regles:
        cle = mot.lower()
        if cle not in table:
            table[cle] = remplacement
    mots = sorted(table, key=len, reverse=True)
    rx = re.compile(r"(?<!\w)(" + "|".join(re.escape(m) for m in mots)
                    + r")(?!\w)", re.IGNORECASE)
    return rx.sub(lambda m: table[m.group(0).lower()], texte)


def chemin_pour(fichier_document: str) -> Path:
    """Chemin du lexique d'un document (``nom.md`` → ``nom.lexique``)."""
    return config.TEXTE_DIR / (Path(fichier_document).stem + EXTENSION)


def lire(fichier_document: str) -> Tuple[str, List[Regle], List[str]]:
    """Lit le lexique d'un document (absent → contenu vide, sans erreur)."""
    p = chemin_pour(fichier_document)
    try:
        contenu = p.read_text(encoding="utf-8")
    except OSError:
        return "", [], []
    regles, erreurs = analyser(contenu)
    return contenu, regles, erreurs


def ecrire(fichier_document: str, contenu: str) -> List[Regle]:
    """Valide puis enregistre le lexique d'un document.

    Contenu vide → le fichier est supprimé s'il existe (pas de fichier
    fantôme). Renvoie les règles valides retenues.
    """
    regles, _ = analyser(contenu or "")
    p = chemin_pour(fichier_document)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not (contenu or "").strip():
        try:
            p.unlink()
        except OSError:
            pass
        return []
    p.write_text(contenu if contenu.endswith("\n") else contenu + "\n",
                 encoding="utf-8")
    return regles
