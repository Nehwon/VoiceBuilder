"""Parsing d'un texte taggé au format OmniVoice.

Règles :
  - ``[Nom]: texte``  -> nouveau segment attribué à la voix ``Nom``.
  - ``[Nom] texte``   -> variante sans ``:`` autorisée.
  - ``[Nom]`` **inline** (milieu de ligne) -> découpe automatique : le texte
    qui suit appartient à ``Nom`` jusqu'au prochain marqueur de voix
    (plusieurs locuteurs par phrase, sans silence artificiel entre eux).
  - ligne nue          -> reprend le locuteur précédent (narrateur).
  - ``[tag]`` inline (ex. ``[sigh]``) -> conservé dans le texte (s'il n'est pas
    un nom de voix, il est traité comme du contenu).
  - ligne vide         -> saut de paragraphe : insère un silence automatique
    de ``PARAGRAPH_PAUSE`` secondes (sans TTS) ; plusieurs lignes vides
    consécutives = un seul silence ; jamais en tête de document ni accolé à
    un ``[pause: …]`` explicite (pas de doublon).
  - ``[pause: 1s]`` / ``[pause 3s]`` / ``[pause=5]`` (ligne seule) -> silence
    de N secondes, sans TTS (autorisé même avant tout personnage).
  - ``[stop]``         -> interrompt la génération (le reste est ignoré).
  - lignes ``#`` : ignorées (commentaires).
"""
from __future__ import annotations

import re
from typing import List, Sequence, Tuple

Segment = Tuple[str, str]   # (personnage, texte)

# Marqueur interne pour les silences explicites (jamais un nom de voix).
PAUSE = "__pause__"

# Silence automatique inséré à chaque saut de paragraphe (ligne vide).
PARAGRAPH_PAUSE = 0.5

# Ligne seule : [pause], [pause: 1s], [pause 3s], [pause=5], [pause 1.5s]…
_PAUSE_RE = re.compile(
    r"^\[\s*pause\s*(?:[:=\s]+?\s*(\d+(?:[.,]\d+)?)\s*s?)?\s*\]\s*:?\s*$",
    re.IGNORECASE,
)


# Tout crochet ``[quelque chose]`` (voix ou tag non-verbal).
_MARQUEUR_RE = re.compile(r"\[([^\[\]]+)\]")


def _decouper_inline(line: str, voices: set) -> List[Tuple[str | None, str]]:
    """Découpe une ligne en ``[(marqueur_ou_None, texte)]``.

    Seuls les crochets dont le contenu est un nom de voix coupent ; les
    autres (ex. ``[sigh]``) restent dans le texte. Un ``:`` en tête du texte
    qui suit un marqueur (variante ``[Nom]: texte``) est retiré. Les morceaux
    vides sont éliminés (ex. ligne ``[Nom]`` seul).
    """
    morceaux: List[Tuple[str | None, str]] = []
    marqueur: str | None = None
    pos = 0
    for m in _MARQUEUR_RE.finditer(line):
        nom = m.group(1).strip()
        if nom not in voices:
            continue
        avant = line[pos:m.start()].strip()
        if marqueur is not None and avant.startswith(":"):
            avant = avant[1:].strip()
        if avant:
            morceaux.append((marqueur, avant))
        marqueur = nom
        pos = m.end()
    reste = line[pos:].strip()
    if marqueur is not None and reste.startswith(":"):
        reste = reste[1:].strip()
    if reste:
        morceaux.append((marqueur, reste))
    return morceaux


def parse_duree_pause(texte: str) -> float | None:
    """Renvoie la durée (s) si ``texte`` est une ligne de pause, sinon None."""
    m = _PAUSE_RE.match(texte.strip())
    if not m:
        return None
    brut = (m.group(1) or "1").replace(",", ".")
    try:
        duree = float(brut)
    except ValueError:
        return None
    if not 0 < duree <= 30:
        raise TaggingError(f"Durée de pause invalide (0–30 s) : {texte.strip()}")
    return duree


class TaggingError(Exception):
    pass


def _pause_paragraphe(segments: List[Segment]) -> None:
    """Ajoute le silence de paragraphe, sauf en tête ou après une pause."""
    if segments and segments[-1][0] != PAUSE:
        segments.append((PAUSE, str(PARAGRAPH_PAUSE)))


def parse_texte(text: str, voix_names: Sequence[str]) -> List[Segment]:
    """Renvoie les segments ``(personnage, texte)`` d'un texte annoté.

    ``voix_names`` : ensemble des noms de locuteurs valides (issus de voix.txt).
    Les segments de pause sont ``(__pause__, "<duree>")`` (durée en secondes,
    en texte) et ne requièrent aucun locuteur courant. Un saut de paragraphe
    (une ou plusieurs lignes vides) insère ``PARAGRAPH_PAUSE`` secondes de
    silence entre deux segments parlés — une seule fois par ligne, même si
    elle contient plusieurs locuteurs (pas de silence entre eux).
    """
    voices = set(voix_names)
    segments: List[Segment] = []
    current: str | None = None
    saut_paragraphe = False

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            saut_paragraphe = True
            continue
        if stripped.startswith("#"):
            continue
        if stripped == "[stop]":
            break
        duree = parse_duree_pause(stripped)
        if duree is not None:
            segments.append((PAUSE, str(duree)))
            saut_paragraphe = False
            continue
        morceaux = _decouper_inline(stripped, voices)
        if not morceaux:
            continue
        premier = True
        for marqueur, texte in morceaux:
            pers = marqueur if marqueur is not None else current
            if pers is None:
                raise TaggingError(
                    f"Ligne sans locuteur avant tout personnage défini : {line}"
                )
            if premier:
                if saut_paragraphe:
                    _pause_paragraphe(segments)
                saut_paragraphe = False
                premier = False
            if marqueur is not None:
                current = marqueur
            segments.append((pers, texte))

    if not segments:
        raise TaggingError("Le texte taggé est vide.")
    return segments


def regrouper(segments: Sequence[Segment]) -> List[Segment]:
    """Fusionne les segments consécutifs d'un même locuteur en un seul bloc.

    Chaque bloc est généré en un seul appel TTS, ce qui évite l'artefact de tête
    (mot parasite) au début de chaque appel. Les pauses (explicites ou de
    paragraphe) restent des blocs séparés et coupent la fusion (pas de fusion
    à travers un silence).
    """
    blocs: List[Segment] = []
    for pers, text in segments:
        if pers == PAUSE:
            blocs.append((pers, text))
            continue
        if blocs and blocs[-1][0] == pers:
            blocs[-1] = (pers, f"{blocs[-1][1]} {text}")
        else:
            blocs.append((pers, text))
    return blocs
