"""Normalisation du texte avant synthèse : nombres -> mots français.

CosyVoice convertit les chiffres en anglais (`spell_out_number`, lib `inflect`)
dans `frontend.py`. On remplace donc les nombres par leurs équivalents écrits en
français (num2words, `lang="fr"`) avant l'appel au moteur : le modèle n'a plus
aucun chiffre à lire, et le patch CosyVoice 0003 désactive la conversion anglaise.
"""
from __future__ import annotations

import re

from num2words import num2words

_PERCENT_RE = re.compile(r"((?:\d{1,3}(?:[\s\u202f\xa0]\d{3})+|\d+[.,]\d+|\d+))\s*%")
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
    except Exception:  # noqa: BLE001 — ne jamais bloquer la génération
        return nombre


def normalize(text: str) -> str:
    """Remplace les nombres du texte par leur écriture en français."""
    # pourcentages : « 85 % » -> « quatre-vingt-cinq pour cent »
    text = _PERCENT_RE.sub(lambda m: _mots(m.group(1)) + " pour cent", text)
    # ordinaux : « 1er » -> « premier », « 4e » -> « quatrième »
    text = _ORDINAL_RE.sub(
        lambda m: num2words(int(m.group(1)), lang="fr", ordinal=True), text
    )
    # milliers espacés : « 2 290 » -> « deux mille deux cent quatre-vingt-dix »
    text = _THOUSAND_RE.sub(
        lambda m: _mots(re.sub(r"[\s\u202f\xa0]", "", m.group(0))), text
    )

    def _num(m: re.Match) -> str:
        w = _mots(m.group(0))
        # évite de coller le mot à une lettre voisine : H100 -> H cent, CO2 -> CO deux
        if m.start() > 0 and text[m.start() - 1].isalpha():
            w = " " + w
        if m.end() < len(text) and text[m.end()].isalpha():
            w = w + " "
        return w

    text = _DECIMAL_RE.sub(_num, text)
    text = _INT_RE.sub(_num, text)
    return text