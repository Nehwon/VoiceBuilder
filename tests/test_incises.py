"""M20 — Tests du plugin incises (engine/incises.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.incises import (
    FiltrePersonnages,
    detecter_incises,
    filtrer_nouveaux_personnages,
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


class TestFiltres:
    DEUX = ("— Salut, Michel, dit Lambda.\n\n"
            "— Te tue pas, ajouta Lambda.\n")

    def test_sans_filtre_historique(self):
        r = nettoyer("— Salut, Michel, dit Lambda.\n", mode="import_roman")
        assert "Lambda" in r.nouveaux_personnages  # 1 réplique, pas de filtre

    def test_hapax_rejete(self):
        r = nettoyer("— Salut, Michel, dit Lambda.\n", mode="import_roman",
                     filtre=FiltrePersonnages())
        assert "Lambda" not in r.nouveaux_personnages
        assert "Lambda" in r.stats["personnages_rejetes"]

    def test_deux_repliques_accepte(self):
        r = nettoyer(self.DEUX, mode="import_roman", filtre=FiltrePersonnages())
        assert "Lambda" in r.nouveaux_personnages
        assert r.stats["personnages_rejetes"] == {}

    def test_titre_rejete(self):
        src = "— Viens ici, dit Maître.\n\n— Reste là, ajouta Maître.\n"
        r = nettoyer(src, mode="import_roman", filtre=FiltrePersonnages())
        assert "Maître" not in r.nouveaux_personnages
        assert "générique" in r.stats["personnages_rejetes"]["Maître"]

    def test_mention_sans_dialogue_rejetee(self):
        acc, rej = filtrer_nouveaux_personnages(
            ["Kaël-An"], "Je pensais à Kaël-An.\n",
            ["[Narrateur]: Je pensais à Kaël-An."], {},
            "Narrateur", FiltrePersonnages())
        assert acc == [] and "Kaël-An" in rej

    def test_pronom_rejete(self):
        acc, rej = filtrer_nouveaux_personnages(
            ["il"], "— Viens, dit-il.\n", ["[Narrateur]: Viens."],
            {}, "Narrateur", FiltrePersonnages())
        assert acc == [] and "il" in rej

    def test_sans_preuve_rejete(self):
        acc, rej = filtrer_nouveaux_personnages(
            ["Lambda"], "— Salut !\n",
            ["[Lambda]: Salut !", "[Lambda]: Te tue pas !"],
            {}, "Narrateur", FiltrePersonnages())
        assert acc == [] and "dit X" in rej["Lambda"]

    def test_sans_preuve_accepte_si_desactive(self):
        acc, rej = filtrer_nouveaux_personnages(
            ["Lambda"], "— Salut !\n",
            ["[Lambda]: Salut !", "[Lambda]: Te tue pas !"],
            {}, "Narrateur",
            FiltrePersonnages(preuve_incise=False))
        assert acc == ["Lambda"] and rej == {}

    def test_stop_mots_supp(self):
        acc, rej = filtrer_nouveaux_personnages(
            ["Gamin"], "— Viens, dit Gamin.\n",
            ["[Gamin]: Viens.", "[Gamin]: Reste."],
            {}, "Narrateur", FiltrePersonnages(stop_mots=frozenset({"gamin"})))
        assert acc == [] and "Gamin" in rej

    def test_voix_defaut_et_deja_connu(self):
        acc, rej = filtrer_nouveaux_personnages(
            ["Narrateur", "Lambda"], "— Salut, dit Lambda.\n",
            ["[Lambda]: Salut.", "[Lambda]: Reste."],
            {"Lambda": "VoixX"}, "Narrateur", FiltrePersonnages())
        assert acc == []
        assert "Narrateur" in rej and "Lambda" in rej

    def test_tagge_ne_cree_jamais(self):
        # Ligne déjà taggée [Nom]: → aucun candidat, avec ou sans filtre.
        src = "[Michel]: Viens ici, dit Lambda.\n"
        assert nettoyer(src, mode="nettoyer_tagge").nouveaux_personnages == []
        r = nettoyer(src, mode="nettoyer_tagge", filtre=FiltrePersonnages())
        assert r.nouveaux_personnages == []

    def test_guillemet_ne_cree_pas(self):
        # Pas de tiret cadratin en tête → pas de nouveau personnage.
        src = "« Viens », dit Lambda.\n\n« Reste », ajouta Lambda.\n"
        r = nettoyer(src, mode="import_roman", filtre=FiltrePersonnages())
        assert r.nouveaux_personnages == []

    def test_variante_map_rejetee(self):
        # « Kaël-An » déjà au .map sous « Kael-An » (accents/casse).
        src = "— Viens, dit Kaël-An.\n\n— Reste, ajouta Kaël-An.\n"
        r = nettoyer(src, mode="import_roman", mapping={"Kael-An": "VoixX"},
                     filtre=FiltrePersonnages())
        assert r.nouveaux_personnages == []
        assert "Kaël-An" in r.stats["personnages_rejetes"]
        assert "Kael-An" in r.stats["personnages_rejetes"]["Kaël-An"]

    def test_nom_commun_minuscule_rejete(self):
        # « Forêt » n'est pas en stop-list : c'est l'heuristique minuscule
        # (« forêt » ailleurs dans le texte) qui l'écarte.
        src = ("— Viens, dit Forêt.\n\n— Reste, ajouta Forêt.\n\n"
               "La forêt bruissait sous le vent.\n")
        r = nettoyer(src, mode="import_roman", filtre=FiltrePersonnages())
        assert r.nouveaux_personnages == []
        assert "minuscule" in r.stats["personnages_rejetes"]["Forêt"]

    def test_vrai_nom_sans_minuscule_accepte(self):
        src = "— Salut, dit Lambda.\n\n— Reste, ajouta Lambda.\n"
        r = nettoyer(src, mode="import_roman", filtre=FiltrePersonnages())
        assert r.nouveaux_personnages == ["Lambda"]

    def test_verif_minuscule_desactivable(self):
        src = ("— Viens, dit Terre.\n\n— Reste, ajouta Terre.\n\n"
               "La terre tremblait.\n")
        r = nettoyer(src, mode="import_roman",
                     filtre=FiltrePersonnages(verif_minuscule=False,
                                             stop_mots=frozenset()))
        # « terre » reste en stop-list : on vérifie juste que ce n'est plus
        # le motif minuscule qui rejette.
        assert "Terre" in r.stats["personnages_rejetes"]
        assert "minuscule" not in r.stats["personnages_rejetes"]["Terre"]


class TestMap:
    def test_sync_ajoute_defaut(self):
        out = synchroniser_map({"Narrateur": "Narrateur"}, ["Lambda"])
        assert out["Lambda"] == "Narrateur"

    def test_sync_necrase_pas(self):
        out = synchroniser_map({"Lambda": "VoixX"}, ["Lambda"])
        assert out["Lambda"] == "VoixX"
