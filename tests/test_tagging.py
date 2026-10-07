"""Tests du parsing taggé (engine/tagging.py), dont split inline multi-locuteurs."""

import pytest

from engine.tagging import PAUSE, TaggingError, parse_texte, regrouper


def test_base_debut_ligne():
    segs = parse_texte("[Alice] Bonjour.\nComment vas-tu ?", ["Alice"])
    assert segs == [("Alice", "Bonjour."), ("Alice", "Comment vas-tu ?")]


def test_ligne_nue_sans_locuteur_erreur():
    with pytest.raises(TaggingError):
        parse_texte("Bonjour sans voix.", ["Alice"])


def test_split_inline_meme_ligne():
    segs = parse_texte("[Alice] Bonjour. [Bob] Salut !", ["Alice", "Bob"])
    assert segs == [("Alice", "Bonjour."), ("Bob", "Salut !")]


def test_split_inline_ligne_nue():
    segs = parse_texte("[Alice] Il dit bonjour [Bob] et il répond salut.",
                       ["Alice", "Bob"])
    assert segs == [("Alice", "Il dit bonjour"),
                    ("Bob", "et il répond salut.")]


def test_split_inline_trois_locuteurs():
    segs = parse_texte("[A] un [B] deux [C] trois", ["A", "B", "C"])
    assert segs == [("A", "un"), ("B", "deux"), ("C", "trois")]


def test_split_inline_sans_espace():
    segs = parse_texte("[A] un[B] deux", ["A", "B"])
    assert segs == [("A", "un"), ("B", "deux")]


def test_split_inline_variante_deux_points():
    segs = parse_texte("[Alice]: Bonjour. [Bob]: Salut !", ["Alice", "Bob"])
    assert segs == [("Alice", "Bonjour."), ("Bob", "Salut !")]


def test_tag_non_verbal_reste_contenu():
    segs = parse_texte("[Alice] Bonjour [sigh] mon ami.", ["Alice"])
    assert segs == [("Alice", "Bonjour [sigh] mon ami.")]


def test_tag_non_verbal_ne_coupe_pas():
    segs = parse_texte("[Alice] Bonjour [sigh] [Bob] Salut.", ["Alice", "Bob"])
    assert segs == [("Alice", "Bonjour [sigh]"), ("Bob", "Salut.")]


def test_marqueur_inconnu_ne_coupe_pas():
    segs = parse_texte("[Alice] Va [Bob] voir.", ["Alice"])
    assert segs == [("Alice", "Va [Bob] voir.")]


def test_pause_ligne_seule():
    segs = parse_texte("[Alice] Bonjour.\n[pause: 2s]\nAu revoir.", ["Alice"])
    assert segs == [("Alice", "Bonjour."), (PAUSE, "2.0"),
                    ("Alice", "Au revoir.")]


def test_saut_paragraphe_un_seul_silence():
    segs = parse_texte("[Alice] Bonjour.\n\n\nAu revoir.", ["Alice"])
    assert segs == [("Alice", "Bonjour."), (PAUSE, "0.5"),
                    ("Alice", "Au revoir.")]


def test_saut_paragraphe_avant_split_inline():
    # Un seul silence de paragraphe même si la ligne suivante a 2 locuteurs.
    segs = parse_texte("[Alice] Bonjour.\n\nSalut [Bob] yo.", ["Alice", "Bob"])
    assert segs == [("Alice", "Bonjour."), (PAUSE, "0.5"),
                    ("Alice", "Salut"), ("Bob", "yo.")]
    pauses = [s for s in segs if s[0] == PAUSE]
    assert len(pauses) == 1


def test_pas_de_silence_entre_locuteurs_meme_ligne():
    # Changement de locuteur inline = enchaîné, sans silence artificiel.
    segs = parse_texte("[Alice] oui [Bob] non", ["Alice", "Bob"])
    assert not any(s[0] == PAUSE for s in segs)


def test_regrouper_fusionne_meme_locuteur():
    assert regrouper([("A", "un"), ("A", "deux"), ("B", "trois")]) == [
        ("A", "un deux"), ("B", "trois")]


def test_regrouper_pause_coupe_fusion():
    assert regrouper([("A", "un"), (PAUSE, "0.5"), ("A", "deux")]) == [
        ("A", "un"), (PAUSE, "0.5"), ("A", "deux")]
