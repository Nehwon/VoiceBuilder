"""Tests du lexique de prononciation par document (engine/lexique.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import lexique
from engine.lexique import analyser, appliquer
from engine.text_fr import normalize


class TestAnalyser:
    def test_valide(self):
        regles, erreurs = analyser("Ben => Bène\n")
        assert erreurs == []
        assert regles == [("Ben", "Bène")]

    def test_commentaires_et_vides_ignores(self):
        regles, erreurs = analyser("# commentaire\n\n  \nBen => Bène\n")
        assert erreurs == []
        assert regles == [("Ben", "Bène")]

    def test_sans_separateur(self):
        regles, erreurs = analyser("Ben Bène\n")
        assert regles == []
        assert len(erreurs) == 1 and "L1" in erreurs[0]

    def test_mot_ou_remplacement_vide(self):
        regles, erreurs = analyser("=> Bène\nBen =>\n")
        assert regles == []
        assert len(erreurs) == 2

    def test_vide(self):
        assert analyser("") == ([], [])
        assert analyser("  \n# rien\n") == ([], [])


class TestAppliquer:
    REGLES = [("Ben", "Bène")]

    def test_substitution_simple(self):
        assert appliquer("Ben est là.", self.REGLES) == "Bène est là."

    def test_insensible_casse(self):
        assert appliquer("ben est là.", self.REGLES) == "Bène est là."
        assert appliquer("BEN est là.", self.REGLES) == "Bène est là."

    def test_mots_entiers_uniquement(self):
        # « Benoît » et les inclusions ne doivent pas être touchés.
        assert appliquer("Benoît est là.", self.REGLES) == "Benoît est là."
        assert appliquer("Le benêt rit.", self.REGLES) == "Le benêt rit."

    def test_plus_long_gagne(self):
        regles = [("York", "Iorque"), ("New York", "Nou-Yorque")]
        assert appliquer("New York", regles) == "Nou-Yorque"

    def test_sans_regle(self):
        assert appliquer("Ben est là.", []) == "Ben est là."
        assert appliquer("Ben est là.", None) == "Ben est là."

    def test_une_passe_sans_chaine(self):
        # A => B puis B => C ne doit pas donner C.
        regles = [("Ben", "Bède"), ("Bède", "C")]
        assert appliquer("Ben", regles) == "Bède"


class TestNormalizeAvecLexique:
    def test_normalize_applique_en_premier(self):
        res = normalize("Ben est arrivé.", lexique=[("Ben", "Bène")])
        assert "Bène" in res

    def test_normalize_sans_lexique_inchange(self):
        assert normalize("Ben est arrivé.") == normalize(
            "Ben est arrivé.", lexique=[])

    def test_normalize_multilangue_fr_seulement(self):
        from engine.text_fr import normalize_multilangue
        res = normalize_multilangue("Ben dit [en]Ben[/en].",
                                    lexique=[("Ben", "Bène")])
        # le passage français est substitué, le passage anglais est intact
        assert res.startswith("Bène")


class TestFichier:
    def test_ecrire_lire_roundtrip(self, tmp_path, monkeypatch):
        import engine.config as config
        monkeypatch.setattr(config, "TEXTE_DIR", tmp_path)
        regles = lexique.ecrire("chapitre.md", "Ben => Bène\n")
        assert regles == [("Ben", "Bène")]
        contenu, relues, erreurs = lexique.lire("chapitre.md")
        assert erreurs == []
        assert relues == [("Ben", "Bène")]
        assert "Ben => Bène" in contenu

    def test_ecrire_vide_supprime(self, tmp_path, monkeypatch):
        import engine.config as config
        monkeypatch.setattr(config, "TEXTE_DIR", tmp_path)
        lexique.ecrire("chapitre.md", "Ben => Bène\n")
        assert lexique.chemin_pour("chapitre.md").exists()
        assert lexique.ecrire("chapitre.md", "  \n") == []
        assert not lexique.chemin_pour("chapitre.md").exists()

    def test_lire_absent(self, tmp_path, monkeypatch):
        import engine.config as config
        monkeypatch.setattr(config, "TEXTE_DIR", tmp_path)
        assert lexique.lire("inexistant.md") == ("", [], [])
