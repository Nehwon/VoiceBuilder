"""Tests du module engine/text_fr.py — normalisation française pour TTS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.text_fr import (
    normalize,
    _normalize_dates,
    _normalize_times,
    _normalize_abbreviations,
    _normalize_currency,
    _normalize_roman,
    _normalize_punctuation,
    _roman_to_int,
)


# ═══════════════════════════════════════════════════════════════════════════
# Dates
# ═══════════════════════════════════════════════════════════════════════════

class TestDates:
    def test_iso(self):
        result = _normalize_dates("2026-09-04")
        assert "septembre" in result
        assert "deux mille vingt-six" in result

    def test_iso_single_digit_month_day(self):
        result = _normalize_dates("2025-01-01")
        assert "premier" in result
        assert "janvier" in result

    def test_slash_dd_mm_yyyy(self):
        result = _normalize_dates("04/09/2026")
        assert "septembre" in result

    def test_slash_single_digit(self):
        result = _normalize_dates("4/9/2026")
        assert "septembre" in result

    def test_dot_separator(self):
        result = _normalize_dates("04.09.2026")
        assert "septembre" in result

    def test_month_abbrev_sept(self):
        result = _normalize_dates("4 sept. 2026")
        assert "septembre" in result

    def test_month_abbrev_janv(self):
        result = _normalize_dates("1 janv. 2026")
        assert "premier" in result
        assert "janvier" in result

    def test_month_abbrev_fevr(self):
        result = _normalize_dates("14 févr. 2024")
        assert "février" in result

    def test_invalid_date_unchanged(self):
        assert _normalize_dates("abcd") == "abcd"


# ═══════════════════════════════════════════════════════════════════════════
# Heures
# ═══════════════════════════════════════════════════════════════════════════

class TestTimes:
    def test_14h30(self):
        assert "quatorze heures trente" in _normalize_times("14h30")

    def test_14h30_with_min(self):
        assert "quatorze heures trente" in _normalize_times("14h30min")

    def test_14h30_minutes(self):
        assert "quatorze heures trente" in _normalize_times("14h30minutes")

    def test_8h(self):
        assert "huit heures" in _normalize_times("8h")

    def test_8h00(self):
        assert "huit heures" in _normalize_times("8h00")

    def test_23h59(self):
        assert "vingt-trois heures cinquante-neuf" in _normalize_times("23h59")

    def test_colon_separator(self):
        assert "quatorze heures trente" in _normalize_times("14:30")

    def test_invalid_hour_unchanged(self):
        assert _normalize_times("25h00") == "25h00"

    def test_invalid_minute_unchanged(self):
        assert _normalize_times("14h70") == "14h70"

    def test_no_time_unchanged(self):
        assert _normalize_times("hello world") == "hello world"


# ═══════════════════════════════════════════════════════════════════════════
# Abréviations
# ═══════════════════════════════════════════════════════════════════════════

class TestAbbreviations:
    def test_monsieur(self):
        result = _normalize_abbreviations("M. Dupont")
        assert "monsieur" in result.lower()

    def test_madame(self):
        result = _normalize_abbreviations("Mme Dupont")
        assert "madame" in result.lower()

    def test_docteur(self):
        result = _normalize_abbreviations("Dr Martin")
        assert "docteur" in result.lower()

    def test_professeur(self):
        result = _normalize_abbreviations("Pr Durand")
        assert "professeur" in result.lower()

    def test_etc(self):
        result = _normalize_abbreviations("a, b, c, etc.")
        assert "et cetera" in result.lower()

    def test_cad(self):
        result = _normalize_abbreviations("c.-à-d. il parle")
        assert "c'est-à-dire" in result.lower()

    def test_numero(self):
        result = _normalize_abbreviations("n° 42")
        assert "numéro" in result.lower()

    def test_article(self):
        result = _normalize_abbreviations("art. 12")
        assert "article" in result.lower()

    def test_preserve_case(self):
        result = _normalize_abbreviations("Dr Martin")
        assert result.startswith("D")  # Majuscule préservée

    def test_unchanged_no_abbrev(self):
        assert _normalize_abbreviations("bonjour") == "bonjour"


# ═══════════════════════════════════════════════════════════════════════════
# Devises
# ═══════════════════════════════════════════════════════════════════════════

class TestCurrency:
    def test_euros(self):
        assert "euros" in _normalize_currency("10 €")

    def test_dollars(self):
        assert "dollars" in _normalize_currency("10 $")

    def test_livres(self):
        assert "livres" in _normalize_currency("10 £")

    def test_yens(self):
        assert "yens" in _normalize_currency("10 ¥")

    def test_decimal_comma(self):
        result = _normalize_currency("10,50 €")
        assert "virgule" in result
        assert "euros" in result

    def test_decimal_dot(self):
        result = _normalize_currency("10.5 €")
        assert "virgule" in result
        assert "euros" in result

    def test_code_eur(self):
        assert "euros" in _normalize_currency("10 EUR")

    def test_code_usd(self):
        assert "dollars" in _normalize_currency("10 USD")

    def test_unchanged_no_currency(self):
        assert _normalize_currency("hello") == "hello"


# ═══════════════════════════════════════════════════════════════════════════
# Chiffres romains
# ═══════════════════════════════════════════════════════════════════════════

class TestRoman:
    def test_iv(self):
        assert _roman_to_int("IV") == 4

    def test_xii(self):
        assert _roman_to_int("XII") == 12

    def test_xlii(self):
        assert _roman_to_int("XLII") == 42

    def test_cmxcix(self):
        assert _roman_to_int("CMXCIX") == 999

    def test_xcix(self):
        assert _roman_to_int("XCIX") == 99

    def test_invalid_returns_none(self):
        assert _roman_to_int("IIII") is None

    def test_single_i(self):
        # _roman_to_int("I") == 1, mais le regex {2,} l'exclut du pipeline
        assert _roman_to_int("I") == 1
        # Verify regex won't match single char
        from engine.text_fr import _ROMAN_RE
        assert _ROMAN_RE.findall("I") == []

    def test_normalize_xii(self):
        result = _normalize_roman("Chapitre XII")
        assert "douze" in result

    def test_normalize_iv(self):
        result = _normalize_roman("Partie IV")
        assert "quatre" in result

    def test_unchanged_word(self):
        assert _normalize_roman("coucou") == "coucou"


# ═══════════════════════════════════════════════════════════════════════════
# Ponctuation
# ═══════════════════════════════════════════════════════════════════════════

class TestPunctuation:
    def test_ellipsis(self):
        assert "..." in _normalize_punctuation("Il dit\u2026")

    def test_en_dash(self):
        result = _normalize_punctuation("mot\u2013mot")
        assert " — " in result

    def test_em_dash(self):
        result = _normalize_punctuation("mot\u2014mot")
        assert " — " in result

    def test_guillemets(self):
        result = _normalize_punctuation("\u201cBonjour\u201d")
        assert "«" in result and "»" in result

    def test_unchanged_ascii(self):
        assert _normalize_punctuation("Hello!") == "Hello!"


# ═══════════════════════════════════════════════════════════════════════════
# Nombres → mots
# ═══════════════════════════════════════════════════════════════════════════

class TestNumbers:
    def test_percent(self):
        assert "pour cent" in normalize("85 %")

    def test_ordinal(self):
        assert "premier" in normalize("1er")

    def test_thousands(self):
        assert "deux mille deux cent quatre-vingt-dix" in normalize("2 290")

    def test_decimal(self):
        assert "sept virgule sept" in normalize("7,7")

    def test_integer(self):
        assert "six cents" in normalize("600")


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline complet
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalize:
    def test_mixed_text(self):
        text = "Le 4 septembre 2026 à 14h30, Dr Martin a publié 3 articles, etc."
        result = normalize(text)
        assert "quatorze heures trente" in result
        assert "docteur" in result.lower()
        assert "et cetera" in result.lower()

    def test_empty(self):
        assert normalize("") == ""

    def test_no_numbers(self):
        assert normalize("Bonjour le monde") == "Bonjour le monde"

    def test_idempotent_on_pure_text(self):
        text = "Bonjour, ceci est un test."
        assert normalize(text) == text
