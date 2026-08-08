"""Parsing d'un texte taggé au format OmniVoice.

Règles :
  - ``[Nom]: texte``  -> nouveau segment attribué à la voix ``Nom``.
  - ``[Nom] texte``   -> variante sans ``:`` autorisée.
  - ligne nue          -> reprend le locuteur précédent (narrateur).
  - ``[tag]`` inline (ex. ``[sigh]``) -> conservé dans le texte (s'il n'est pas
    un nom de voix, il est traité comme du contenu).
  - ``[stop]``         -> interrompt la génération (le reste est ignoré).
  - lignes vides et ``#`` : ignorées.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

Segment = Tuple[str, str]   # (personnage, texte)


class TaggingError(Exception):
    pass


def parse_texte(text: str, voix_names: Sequence[str]) -> List[Segment]:
    """Renvoie les segments ``(personnage, texte)`` d'un texte annoté.

    ``voix_names`` : ensemble des noms de locuteurs valides (issus de voix.txt).
    """
    voices = set(voix_names)
    segments: List[Segment] = []
    current: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "[stop]":
            break
        if stripped.startswith("[") and "]" in stripped:
            close = stripped.index("]")
            marker = stripped[1:close].strip()
            content = stripped[close + 1 :].lstrip()
            if content.startswith(":"):
                content = content[1:].strip()
            if marker not in voices:
                # C'est un tag non-verbal (ex. [sigh]) : on le garde en contenu.
                if current is None:
                    raise TaggingError(
                        f"Ligne sans locuteur avant tout personnage défini : {line}"
                    )
                segments.append((current, stripped))
                continue
            if not content:
                continue
            current = marker
            segments.append((current, content))
        else:
            if current is None:
                raise TaggingError(
                    f"Ligne sans tag avant tout personnage défini : {line}"
                )
            segments.append((current, stripped))

    if not segments:
        raise TaggingError("Le texte taggé est vide.")
    return segments


def regrouper(segments: Sequence[Segment]) -> List[Segment]:
    """Fusionne les segments consécutifs d'un même locuteur en un seul bloc.

    Chaque bloc est généré en un seul appel TTS, ce qui évite l'artefact de tête
    (mot parasite) au début de chaque appel.
    """
    blocs: List[Segment] = []
    for pers, text in segments:
        if blocs and blocs[-1][0] == pers:
            blocs[-1] = (pers, f"{blocs[-1][1]} {text}")
        else:
            blocs.append((pers, text))
    return blocs