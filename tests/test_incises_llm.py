"""M20.6 — Tests du nettoyage d'incises via LLM (mock + live optionnel)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import incises_llm as llm


BONNE_REPONSE = {
    "segments": [
        {"personnage": "Lambda", "texte": "Salut, Michel.", "type": "dialogue"},
        {"personnage": "Narrateur", "texte": "Dit Lambda en riant.", "type": "narration"},
    ],
    "nouveaux_personnages": ["Lambda"],
}

CHUNK = "— Salut, Michel, dit Lambda en riant."


def _faux_appel_ok(prompt, systeme, modele=None, url=None):
    return json.dumps(BONNE_REPONSE)


class TestValidation:
    def test_sortie_valide(self):
        assert llm.valider_sortie(CHUNK, BONNE_REPONSE) == []

    def test_sans_segments(self):
        assert llm.valider_sortie(CHUNK, {"segments": []})

    def test_incise_residuelle_detectee(self):
        data = {"segments": [
            {"personnage": "X", "texte": "Salut, dit-il.", "type": "dialogue"}],
            "nouveaux_personnages": []}
        probs = llm.valider_sortie("— Salut, dit-il.", data)
        assert any("incise" in p for p in probs)

    def test_perte_texte_detectee(self):
        data = {"segments": [
            {"personnage": "X", "texte": "Bonjour.", "type": "dialogue"}],
            "nouveaux_personnages": []}
        probs = llm.valider_sortie(
            "Le premier paragraphe du chapitre avec beaucoup de mots uniques "
            "xylophone zoroastre quark juxtaposer", data)
        assert any("rappel" in p for p in probs)

    def test_rappel_lexical_parfait(self):
        assert llm.rappel_lexical("Salut Michel", [
            {"texte": "Salut, Michel."}]) == 1.0


class TestChunk:
    def test_traiter_chunk_ok(self):
        data = llm.traiter_chunk(CHUNK, ["Narrateur"], None, appeler=_faux_appel_ok)
        assert data["segments"][0]["personnage"] == "Lambda"

    def test_recadrage_apres_echec(self):
        appels = iter([json.dumps({"segments": []}), json.dumps(BONNE_REPONSE)])

        def appeler(prompt, systeme, modele=None, url=None):
            return next(appels)

        data = llm.traiter_chunk(CHUNK, ["Narrateur"], None, appeler=appeler)
        assert data["segments"][0]["personnage"] == "Lambda"

    def test_rejet_definitif(self):
        try:
            llm.traiter_chunk(CHUNK, [], None,
                              appeler=lambda *a, **k: "pas du json du tout {{{")
        except llm.ErreurLLM:
            return
        raise AssertionError("ErreurLLM attendue")

    def test_decoupage_frontieres(self):
        texte = "Para un.\n\nPara deux.\n\nPara trois."
        chunks = llm.decouper_chunks(texte, max_chars=15)
        assert len(chunks) == 3
        assert all("Para" in c for c in chunks)


class TestNettoyerLLM:
    def test_assemblage_et_nouveaux(self):
        res = llm.nettoyer_llm("— Salut, Michel, dit Lambda en riant.\n\nIl fait froid.\n",
                               mapping={"Narrateur": "Narrateur"},
                               appeler=_faux_appel_ok)
        assert "[Lambda]:" in res.texte
        assert "dit Lambda" not in res.texte.split("[Lambda]:")[1].split("\n")[0]
        assert "Lambda" in res.nouveaux_personnages

    def test_repli_regex_sans_trou(self):
        res = llm.nettoyer_llm("[A]: Bonjour, dit-il.\n",
                               appeler=lambda *a, **k: (_ for _ in ()).throw(
                                   llm.ErreurLLM("panne simulée")))
        assert "dit-il" not in res.texte
        assert "[A]:" in res.texte


REPLIQUE_OK = {"replique": "Viens ici.", "actions": ["Se leva-t-il."],
                 "nouveau": None}


def _faux_replique_ok(prompt, systeme, modele=None, url=None):
    return json.dumps(REPLIQUE_OK)


class TestReplique:
    def test_nettoyage_cible(self):
        data = llm.traiter_replique("Viens ici, murmura-t-il en se levant.",
                                    "Lambda", appeler=_faux_replique_ok)
        assert data["replique"] == "Viens ici."

    def test_chunk_tagge_conserve_tags(self):
        res = llm.nettoyer_llm("[Michel]: J'ouvris les yeux.\n\n[Lambda]: Salut !\n",
                               mapping={"Michel": "M", "Lambda": "L", "Narrateur": "N"},
                               appeler=_faux_replique_ok)
        assert res.texte.startswith("[Michel]:")
        assert "[Lambda]:" in res.texte
        assert "Narrateur" not in res.texte.split("[Lambda]")[0].split("\n")[0]

    def test_nouveau_filtre_mention(self):
        res = llm.nettoyer_llm("Il faisait froid.\n", mapping={},
                               appeler=lambda *a, **k: json.dumps({
                                   "segments": [{"personnage": "Narrateur",
                                                 "texte": "Il faisait froid.",
                                                 "type": "narration"}],
                                   "nouveaux_personnages": ["Kaël-An"]}))
        assert res.nouveaux_personnages == []


class TestFiltresLLM:
    def test_hapax_llm_rejete(self):
        from engine.incises import FiltrePersonnages
        res = llm.nettoyer_llm("— Salut, Michel, dit Lambda en riant.\n",
                               mapping={"Narrateur": "Narrateur"},
                               appeler=_faux_appel_ok,
                               filtre=FiltrePersonnages())
        assert "Lambda" not in res.nouveaux_personnages
        assert "Lambda" in res.stats["personnages_rejetes"]

    def test_sans_filtre_llm_historique(self):
        res = llm.nettoyer_llm("— Salut, Michel, dit Lambda en riant.\n",
                               mapping={"Narrateur": "Narrateur"},
                               appeler=_faux_appel_ok)
        assert "Lambda" in res.nouveaux_personnages


class TestCriteresLLM:
    def test_tagge_nouveau_ignore(self):
        import json as _json

        def appeler_nouveau(prompt, systeme, modele=None, url=None):
            return _json.dumps({"replique": "Viens ici.",
                                "actions": [], "nouveau": "Lambda"})

        res = llm.nettoyer_llm("[Michel]: Viens ici, dit Lambda.\n",
                               mapping={"Michel": "M", "Narrateur": "N"},
                               appeler=appeler_nouveau,
                               filtre=llm.FiltrePersonnages())
        assert res.nouveaux_personnages == []
        assert res.texte.startswith("[Michel]:")


class TestLive:
    """Ne tourne que si Ollama répond (sinon skip silencieux)."""

    def test_live_mini(self):
        if not llm.ollama_disponible():
            return
        res = llm.nettoyer_llm("— Salut, Michel, dit Lambda en riant.\n",
                               mapping={"Narrateur": "Narrateur"})
        assert "[Lambda]:" in res.texte
        assert "dit Lambda" not in res.texte
        assert "Lambda" in res.nouveaux_personnages
