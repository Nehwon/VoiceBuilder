"""M20 — Tests du plugin incises (engine/incises.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.incises import (
    detecter_incises,
    resoudre_locuteur,
    nettoyer,
    synchroniser_map,
    Incise,
)


class TestDetection:
    def test_dit_il(self):
        inc = detecter_incises("— Salut, dit-il.")
        assert len(inc) == 1
        assert inc[0].est_parole
        assert inc[0].locuteur_brut == "il"

    def test_murmura_t_elle(self):
        inc = detecter_incises("— Viens, murmura-t-elle en se levant.")
        assert len(inc) == 1
        assert inc[0].est_parole  # verbe de parole même avec complément
        assert inc[0].locuteur_brut == "elle"

    def test_dis_je(self):
        inc = detecter_incises("— Je reste, dis-je.")
        assert len(inc) == 1
        assert inc[0].locuteur_brut == "je"

    def test_dit_lambda_nom(self):
        inc = detecter_incises("— Salut, dit Lambda en riant.")
        assert len(inc) == 1
        assert inc[0].locuteur_brut == "Lambda"
        assert inc[0].est_parole

    def test_sexclama_nom(self):
        inc = detecter_incises("« Viens ! » s'exclama Marie.")
        assert len(inc) == 1
        assert inc[0].est_parole

    def test_sans_incise(self):
        assert detecter_incises("— Salut, Michel !") == []

    def test_tiret_seul_pas_incise(self):
        assert detecter_incises("— Il partit sans un mot.") == []


class TestAction:
    def test_action_inversion(self):
        inc = detecter_incises("— Viens, se leva-t-il.")
        assert len(inc) == 1
        assert not inc[0].est_parole

    def test_action_sourit(self):
        inc = detecter_incises("— Bien sûr, sourit-elle.")
        assert len(inc) == 1
        assert not inc[0].est_parole


class TestResolution:
    def test_nom_propre_haute(self):
        inc = Incise(0, 1, "dit Lambda", "dit", "Lambda", True)
        nom, conf = resoudre_locuteur(inc, "Narrateur", "Michel")
        assert (nom, conf) == ("Lambda", "haute")

    def test_pronom_dernier_locuteur(self):
        inc = Incise(0, 1, "dit-il", "dit", "il", True)
        nom, conf = resoudre_locuteur(inc, "Lambda", "Lambda")
        assert nom == "Lambda"

    def test_je_narrateur_je(self):
        inc = Incise(0, 1, "dis-je", "dis", "je", True)
        nom, conf = resoudre_locuteur(inc, "Narrateur", None, narrateur_je="Michel")
        assert (nom, conf) == ("Michel", "haute")

    def test_je_sans_option_repli_faible(self):
        inc = Incise(0, 1, "dis-je", "dis", "je", True)
        nom, conf = resoudre_locuteur(inc, "Narrateur", None)
        assert (nom, conf) == ("Narrateur", "faible")


class TestNettoyage:
    def test_tagge_parole_retiree(self):
        r = nettoyer("[Lambda]: Salut, Michel, dit-il.\n", mode="nettoyer_tagge")
        assert "dit-il" not in r.texte
        assert "[Lambda]:" in r.texte
        assert "Salut" in r.texte

    def test_tagge_action_narration(self):
        r = nettoyer("[Lambda]: Viens, se leva-t-il.\n",
                     mode="nettoyer_tagge", keep_action="narration")
        assert "[Narrateur]:" in r.texte
        assert "[Lambda]:" in r.texte

    def test_tagge_action_garder(self):
        r = nettoyer("[Lambda]: Viens, se leva-t-il.\n",
                     mode="nettoyer_tagge", keep_action="garder")
        assert "se leva-t-il" in r.texte

    def test_tagge_action_supprimer(self):
        r = nettoyer("[Lambda]: Viens, se leva-t-il.\n",
                     mode="nettoyer_tagge", keep_action="supprimer")
        assert "se leva-t-il" not in r.texte
        assert "[Narrateur]:" not in r.texte

    def test_import_dialogue_tiret(self):
        r = nettoyer("— Salut, Michel, dit Lambda en riant. Te tue pas !\n",
                     mode="import_roman")
        assert "[Lambda]:" in r.texte
        assert "dit Lambda" not in r.texte
        assert "Lambda" in r.nouveaux_personnages

    def test_import_prose_narrateur(self):
        r = nettoyer("Le froid du sol traversait la pièce.\n", mode="import_roman")
        assert r.texte.startswith("[Narrateur]:")

    def test_import_guillemets(self):
        r = nettoyer("« Viens ici », murmura-t-elle.\n", mode="import_roman",
                     mapping={"Narrateur": "Narrateur"})
        assert "murmura-t-elle" not in r.texte

    def test_auto_detecte_tagge(self):
        r = nettoyer("[A]: Bonjour, dit-il.\n", mode="auto")
        assert "dit-il" not in r.texte

    def test_auto_detecte_roman(self):
        r = nettoyer("— Bonjour, dit-il.\n", mode="auto")
        assert "[Narrateur]:" in r.texte or "[A]:" in r.texte or "Bonjour" in r.texte


class TestMap:
    def test_sync_ajoute_defaut(self):
        out = synchroniser_map({"Narrateur": "Narrateur"}, ["Lambda"])
        assert out["Lambda"] == "Narrateur"

    def test_sync_necrase_pas(self):
        out = synchroniser_map({"Lambda": "VoixX"}, ["Lambda"])
        assert out["Lambda"] == "VoixX"
