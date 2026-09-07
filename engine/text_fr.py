"""Normalisation du texte français avant synthèse TTS (CosyVoice).

Pipeline complet de conversion du texte écrit en texte lisible à voix haute :
  - Dates (ISO, barre oblique, mois écrits)
  - Heures (14h30, 14:30)
  - Abréviations courantes (M., Dr, etc., c.-à-d.)
  - Devises (€, $, £, ¥)
  - Chiffres romains (IV, XII)
  - Ponctuation fine (…, —)
  - Nombres → mots français (num2words)

Le patch CosyVoice 0003 désactive la conversion anglaise (`spell_out_number`) ;
ce module fournit la normalization française en amont de ``inference_zero_shot``.
"""
from __future__ import annotations

import re

from num2words import num2words

# ---------------------------------------------------------------------------
# mois
# ---------------------------------------------------------------------------
_MOIS = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}
_MOIS_ABBREV = {
    "janv": 1, "jan": 1, "févr": 2, "fév": 2, "fev": 2, "mars": 3, "mar": 3,
    "avri": 4, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "juill": 7,
    "août": 8, "aou": 8, "sept": 9, "octo": 10, "oct": 10,
    "nove": 11, "nov": 11, "déce": 12, "déc": 12, "dec": 12,
}

# ---------------------------------------------------------------------------
# nombres → mots (utilisé en dernier recours par _mots)
# ---------------------------------------------------------------------------
_PERCENT_RE = re.compile(
    r"((?:\d{1,3}(?:[\s\u202f\xa0]\d{3})+|\d+[.,]\d+|\d+))\s*%"
)
_ORDINAL_RE = re.compile(r"(\d+)(er|ère|re|e|ème|eme)\b")
_THOUSAND_RE = re.compile(r"\d{1,3}(?:[\s\u202f\xa0]\d{3})+")
_DECIMAL_RE = re.compile(r"\d+[.,]\d+")
_INT_RE = re.compile(r"\d+")


def _mots(nombre: str) -> str:
    """Convertit un nombre (entier ou décimal) en mots français."""
    try:
        if re.fullmatch(r"\d+", nombre):
            return num2words(int(nombre), lang="fr")
        return num2words(float(nombre.replace(",", ".")), lang="fr")
    except Exception:
        return nombre


def _mots_ordinal(nombre: str) -> str:
    try:
        return num2words(int(nombre), lang="fr", ordinal=True)
    except Exception:
        return nombre


def _cardinal(m: re.Match) -> str:
    """Substitue un nombre trouvé par son écriture en français."""
    w = _mots(m.group(0))
    if m.start() > 0 and not m.string[m.start() - 1].isspace():
        w = " " + w
    if m.end() < len(m.string) and not m.string[m.end()].isspace():
        w = w + " "
    return w


# ---------------------------------------------------------------------------
# 1. Dates
# ---------------------------------------------------------------------------
#   2026-09-04  → quatre septembre deux mille vingt-six
#   04/09/2026  → quatre septembre deux mille vingt-six
#   4/9/2026    → quatre septembre deux mille vingt-six
#   04.09.2026  → quatre septembre deux mille vingt-six
#   4 sept. 2026 → quatre septembre deux mille vingt-six

def _format_date(d: int, mo: int, y: int) -> str:
    """Formate une date en texte français."""
    if mo < 1 or mo > 12 or d < 1 or d > 31:
        return ""
    jour = _mots(str(d)) if d != 1 else "premier"
    return f"{jour} {_MOIS[mo]} {_mots(str(y))}"


def _date_iso(m: re.Match) -> str:
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return _format_date(d, mo, y) or m.group(0)


def _date_slash(m: re.Match) -> str:
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return _format_date(d, mo, y) or m.group(0)


_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DATE_SLASH_RE = re.compile(r"\b(\d{1,2})[/\.](\d{1,2})[/\.](\d{4})\b")

_MOIS_ABBREV_RE = re.compile(
    r"\b(\d{1,2})\s*("
    + "|".join(re.escape(k) for k in sorted(_MOIS_ABBREV, key=len, reverse=True))
    + r")\.?\s*(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_dates(text: str) -> str:
    text = _DATE_ISO_RE.sub(_date_iso, text)
    text = _DATE_SLASH_RE.sub(_date_slash, text)

    def _mois_abbrev(m: re.Match) -> str:
        d, abbr, y = int(m.group(1)), m.group(2).lower().rstrip("."), int(m.group(3))
        mo = _MOIS_ABBREV.get(abbr)
        if mo is None:
            return m.group(0)
        jour = _mots(str(d)) if d != 1 else "premier"
        return f"{jour} {_MOIS[mo]} {_mots(str(y))}"

    text = _MOIS_ABBREV_RE.sub(_mois_abbrev, text)
    return text


# ---------------------------------------------------------------------------
# 2. Heures
# ---------------------------------------------------------------------------
#   14h30         → quatorze heures trente
#   14:30         → quatorze heures trente
#   8h            → huit heures
#   8h00          → huit heures
#   14h30m        → quatorze heures trente
#   14h30min      → quatorze heures trente
#   14h30minutes  → quatorze heures trente

_TIME_HM_RE = re.compile(
    r"\b(\d{1,2})\s*[hH:]\s*(\d{1,2})\s*(?:minutes?|mins?|m)?\b"
)
_TIME_H_RE = re.compile(
    r"\b(\d{1,2})\s*[hH]\b(?!\s*\d)"
)


def _normalize_times(text: str) -> str:
    def _hm(m: re.Match) -> str:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return m.group(0)
        h_mot = _mots(str(h))
        mi_mot = _mots(str(mi))
        if mi == 0:
            return f"{h_mot} heures"
        return f"{h_mot} heures {mi_mot}"

    def _h(m: re.Match) -> str:
        h = int(m.group(1))
        if h > 23:
            return m.group(0)
        return f"{_mots(str(h))} heures"

    text = _TIME_HM_RE.sub(_hm, text)
    text = _TIME_H_RE.sub(_h, text)
    return text


# ---------------------------------------------------------------------------
# 3. Abréviations courantes
# ---------------------------------------------------------------------------
_ABBREV = {
    # titres
    "m.": "monsieur", "mr": "monsieur",
    "mme": "madame", "mlle": "mademoiselle",
    "dr": "docteur", "pr": "professeur",
    "me": "maître", "me.": "maître",
    # académique / administratif
    "etc.": "et cetera", "etc": "et cetera",
    "c.-à-d.": "c'est-à-dire", "c‑à‑d": "c'est-à-dire",
    "p. ex.": "par exemple", "p.ex.": "par exemple",
    "av. j.-c.": "avant Jésus-Christ",
    "j.-c.": "Jésus-Christ",
    "n°": "numéro", "n°.": "numéro",
    "av.": "avenue", "bp": "boîte postale",
    "vs": "contre", "vs.": "contre",
    "cf.": "voir", "ex.": "exemple",
    "art.": "article", "al.": "alinéa",
    "tél.": "téléphone", "fax": "télécopie",
    "jr": "junior", "sr": "sénior",
    # unités courantes (devant un nombre)
    "hab.": "habitants", "hab": "habitants",
    "env.": "environ", "env": "environ",
    "p.": "page", "pp.": "pages",
    "vol.": "volume", "t.": "tome", "ch.": "chapitre",
    "fig.": "figure", "tab.": "tableau",
    "rép.": "réponse", "resp.": "responsable",
    "rég.": "région", "dép.": "département",
    "max.": "maximum", "min.": "minimum",
}

_ABBREV_SORTED = sorted(_ABBREV, key=len, reverse=True)
# (?!\w) au lieu de \b final : les abréviations se terminent souvent par un
# point ou un caractère spécial (°) qui ne passe pas le test \b.
_ABBREV_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _ABBREV_SORTED) + r")(?!\w)\.?",
    re.IGNORECASE,
)


def _normalize_abbreviations(text: str) -> str:
    def _replace(m: re.Match) -> str:
        key = m.group(1).lower().rstrip(".")
        replacement = _ABBREV.get(key, _ABBREV.get(key + ".", m.group(0)))
        if m.group(1)[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    return _ABBREV_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# 4. Devises
# ---------------------------------------------------------------------------
#   10 €     → dix euros
#   10,50 €  → dix virgule cinquante euros
#   10 $     → dix dollars
#   10 £     → dix livres
#   10 ¥     → dix yens
#   10 CHF   → dix francs suisses

_DEVISES = {
    "€": "euros", "eur": "euros",
    "$": "dollars", "usd": "dollars",
    "£": "livres", "gbp": "livres",
    "¥": "yens", "jpy": "yens",
    "chf": "francs suisses",
    "cad": "dollars canadiens",
    "aud": "dollars australiens",
}

# Les symboles €, $, £, ¥ ne sont pas des word-chars : pas de \b autour
_DEVISE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(€|\$|£|¥|EUR|USD|GBP|JPY|CHF|CAD|AUD)",
    re.IGNORECASE,
)


def _normalize_currency(text: str) -> str:
    def _replace(m: re.Match) -> str:
        montant = m.group(1).replace(",", ".")
        symbole = m.group(2).lower()
        devise = _DEVISES.get(symbole, symbole)
        try:
            montant_mot = _mots(montant)
        except Exception:
            montant_mot = m.group(1)
        return f"{montant_mot} {devise}"

    return _DEVISE_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# 5. Chiffres romains
# ---------------------------------------------------------------------------
#   IV   → quatre
#   XII  → douze
#   XLII → quarante-deux

_ROMAN_MAP = {
    "I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000,
}


def _roman_to_int(s: str) -> int | None:
    """Convertit un chiffre romain majuscule en entier."""
    s = s.upper()
    result = 0
    prev = 0
    for ch in reversed(s):
        val = _ROMAN_MAP.get(ch)
        if val is None:
            return None
        if val < prev:
            result -= val
        else:
            result += val
        prev = val
    if result <= 0 or result > 3999:
        return None
    # vérification stricte : reconvertir et comparer (sans modifier result)
    check = ""
    remaining = result
    for v, sym in [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
                    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        while remaining >= v:
            check += sym
            remaining -= v
    return result if check.upper() == s else None


_ROMAN_RE = re.compile(r"\b([IVXLCDM]{2,})\b")


def _normalize_roman(text: str) -> str:
    def _replace(m: re.Match) -> str:
        val = _roman_to_int(m.group(1))
        if val is None:
            return m.group(0)
        return _mots(str(val))

    return _ROMAN_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# 6. Ponctuation fine
# ---------------------------------------------------------------------------
#   …   → ...
#   —   → — (espace autour pour meilleure tokenisation)
#   –   → — (normaliser en tiret long)
#   « » → " " (guillemets français → dialogues)

_PUNC_REPLACEMENTS = [
    ("\u2026", "..."),      # … → ...
    ("\u2013", " — "),     # tiret court → tiret long espacé
    ("\u2014", " — "),     # déjà tiret long, mais espacer
    ("\u2018", "« "),      # guillemet ouvrant typographique
    ("\u2019", " »"),      # guillemet fermant typographique
    ("\u201c", "« "),      # double guillemet ouvrant
    ("\u201d", " »"),      # double guillemet fermant
]


def _normalize_punctuation(text: str) -> str:
    for old, new in _PUNC_REPLACEMENTS:
        text = text.replace(old, new)
    text = re.sub(r"  +", " ", text)
    return text


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Normalise le texte français pour la synthèse TTS.

    Ordre : dates → heures → abréviations → devises → romains →
    ponctuation → nombres → mots.
    Les étapes les plus spécifiques passent en premier pour éviter les
    conflits avec la normalisation générique des nombres.
    """
    text = _normalize_dates(text)
    text = _normalize_times(text)
    text = _normalize_abbreviations(text)
    text = _normalize_currency(text)
    text = _normalize_roman(text)
    text = _normalize_punctuation(text)

    # --- nombres → mots (étape générique en dernier) ---
    text = _PERCENT_RE.sub(
        lambda m: _mots(m.group(1)) + " pour cent", text
    )
    text = _ORDINAL_RE.sub(
        lambda m: _mots_ordinal(m.group(1)), text
    )
    text = _THOUSAND_RE.sub(
        lambda m: _mots(re.sub(r"[\s\u202f\xa0]", "", m.group(0))), text
    )
    text = _DECIMAL_RE.sub(_cardinal, text)
    text = _INT_RE.sub(_cardinal, text)
    return text
