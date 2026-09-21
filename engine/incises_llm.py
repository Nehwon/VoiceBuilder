"""Incises de dialogue via LLM local (M20.6, Ollama).

Remplace l'approche 100 % regex (``engine/incises.py``, fragile : fausse
attribution du locuteur, prose avec «» prise pour du dialogue, tirets
résiduels…) par une compréhension réelle du texte, avec garde-fous
déterministes :

- découpage en chunks (~2500 caractères, frontières de paragraphes) avec
  contexte (personnages connus, dernier locuteur) ;
- sortie JSON stricte (``format="json"`` Ollama) : segments
  ``{personnage, texte, type}`` + ``nouveaux_personnages`` ;
- validation : JSON valide, schéma conforme, **rappel lexical** sortie/entrée
  ≥ ``INCISES_RAPPEL_MIN`` (aucune perte de récit), **zéro incise de parole
  résiduelle** (revérifié par le détecteur regex en juge) ;
- 1 tentative de correction sur échec, sinon repli regex chunk par chunk
  (jamais de trou dans la sortie).

Dépendance : serveur Ollama joignable (``config.OLLAMA_URL``, modèle
``config.OLLAMA_MODELE_INCISES``). Stdlib uniquement (``urllib``).
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import config
from .incises import (
    FiltrePersonnages,
    ResultatNettoyage,
    detecter_incises,
    filtrer_nouveaux_personnages,
    nettoyer as nettoyer_regex,
    synchroniser_map,
)

SYSTEME = """Tu prépares un roman français pour une synthèse vocale multi-voix (livre audio).
Tu reçois un EXTRAIT entre <extrait> et </extrait>. Réponds UNIQUEMENT avec un objet JSON :
{"segments": [{"personnage": "Nom", "texte": "...", "type": "dialogue|narration"}], "nouveaux_personnages": ["..."]}

Règles strictes :
1. Chaque réplique parlée devient un segment "dialogue" avec son VRAI locuteur, JAMAIS "%s" pour une réplique entre tirets/guillemets. Résous les pronoms avec le contexte : "dit-il/elle" = le dernier homme/femme qui parle ou est présent ; "dis-je" = le narrateur indiqué ("je" vaut : %s), segment "dialogue" avec ce personnage ; "dit X / s'exclama Y" = X / Y. En cas d'ambiguïté, préfère le dernier locuteur au Narrateur.
2. SUPPRIME totalement les incises de parole pures : dit-il/elle/on, murmura-t-elle, chuchota-t-il, s'exclama Marie, répondit-il, demanda-t-elle, dis-je, dit-on... Elles ne doivent apparaître NULLE PART dans les textes (ni le verbe, ni le pronom, ni le nom). Une réplique "dialogue" ne contient JAMAIS de proposition du type verbe-pronom ("-t-il", "-t-elle", "-je") : si tu en vois une, c'est une incise à traiter (règles 2-3), pas du dialogue.
3. Incise avec ACTION réelle (se leva-t-il, sourit-elle, en se levant, haussa les épaules, en riant...) : ne la mets JAMAIS dans la bouche du personnage. Crée un segment "narration" séparé avec le personnage "%s", en reformulant à la 3e personne si besoin ("Sourit-elle." / "Dit Lambda en riant.").
4. Prose et narration : un ou plusieurs segments "narration" avec "%s". Ne fusionne pas des paragraphes distincts en un seul segment.
5. Ne perds AUCUN mot du récit, n'en invente AUCUN (hors reformulation minimale de la règle 3). Retire seulement les incises de parole et les tirets/guillemets d'ouverture en tête de réplique.
6. "nouveaux_personnages" : avec une parcimonie extrême — UNIQUEMENT un nom qui PARLE au moins deux fois dans l'extrait (deux segments "dialogue" portent son nom), porté par une incise explicite ("dit X") sur une réplique commençant par un tiret cadratin —, ET qui NE figure PAS dans la liste des connus (ni en variante d'accent/casse : "Kaël-An" = "Kael-An"). Jamais "Narrateur", jamais un pronom, jamais un titre, une fonction, un élément ou une notion ("Maître", "Madame", "Pilier", "Terre", "Eau", "Mémoire"...), jamais un nom simplement mentionné dans la narration. En cas de doute : liste vide.
7. Si l'extrait contient déjà des balises [Nom]:, CONSERVE le locuteur indiqué tel quel (ne le remplace ni par Narrateur ni par un autre), sauf si une incise nomme explicitement un autre personnage ("dit X" contradictoire).
7. Noms propres tels quels (accents et casse d'origine). Pas de commentaire, pas de markdown, que le JSON.

Exemple :
<extrait>— Salut, Michel, dit Lambda en riant. Te tue pas au travail !
Le froid traversait la pièce.
« Viens », murmura-t-elle en se levant.
— Je reste, dis-je.</extrait>
{"segments": [{"personnage": "Lambda", "texte": "Salut, Michel. Te tue pas au travail !", "type": "dialogue"}, {"personnage": "Narrateur", "texte": "Dit Lambda en riant.", "type": "narration"}, {"personnage": "Narrateur", "texte": "Le froid traversait la pièce.", "type": "narration"}, {"personnage": "Lambda", "texte": "Viens.", "type": "dialogue"}, {"personnage": "Narrateur", "texte": "Murmura-t-elle en se levant.", "type": "narration"}, {"personnage": "Narrateur", "texte": "Je reste.", "type": "dialogue"}], "nouveaux_personnages": ["Lambda"]}
"""

RECADRAGE = """Ta réponse précédente pour cet extrait est INUTILISABLE (%s). Recommence : réponds UNIQUEMENT avec le JSON demandé, sans texte autour, en respectant toutes les règles. Extrait :
<extrait>%s</extrait>
"""

SYSTEME_REPLIQUE = """Tu nettoies UNE réplique de roman pour une synthèse vocale. Le locuteur est "%s" (déjà connu, ne le change JAMAIS). Réponds UNIQUEMENT avec un objet JSON :
{"replique": "...", "actions": ["..."], "nouveau": null}

Règles :
1. "replique" = le texte PARLÉ, sans les incises de parole (dit-il/elle/on, murmura-t-elle, dis-je, répondit-il...) : ni verbe, ni pronom, ni nom d'incise.
2. "actions" = chaque incise à ACTION réelle (se leva-t-il, sourit-elle, en se levant...) reformulée en phrase pour le narrateur ("%s"). Liste vide si aucune.
3. "nouveau" = TOUJOURS null : une réplique déjà attribuée ne révèle jamais un nouveau personnage.
4. Ne perds aucun mot du récit, n'en invente aucun. Pas de commentaire, que le JSON.

Exemple : {"replique": "Viens ici.", "actions": ["Se leva-t-il."], "nouveau": null} pour « Viens ici », murmura-t-il en se levant.
"""

_RECADRAGE_REPLIQUE = """Réponse INUTILISABLE (%s). Recommence : UNIQUEMENT le JSON {"replique", "actions", "nouveau"}, sans texte autour. Réplique de %s :
<replique>%s</replique>
"""


class ErreurLLM(Exception):
    pass


def appeler_ollama(prompt: str, systeme: str, modele: Optional[str] = None,
                   url: Optional[str] = None,
                   timeout: Optional[float] = None) -> str:
    """Un appel ``/api/generate`` non-streamé, sortie JSON (``format="json"``)."""
    modele = modele or config.OLLAMA_MODELE_INCISES
    url = (url or config.OLLAMA_URL).rstrip("/")
    timeout = timeout or config.OLLAMA_TIMEOUT
    payload = json.dumps({
        "model": modele, "prompt": prompt, "system": systeme,
        "format": "json", "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192},
    }).encode()
    req = urllib.request.Request(f"{url}/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rep:
            return json.loads(rep.read().decode()).get("response", "")
    except Exception as exc:
        raise ErreurLLM(f"Ollama injoignable ({url}, modèle {modele}) : {exc}")


def ollama_disponible(url: Optional[str] = None) -> bool:
    """Vrai si le serveur Ollama répond (modèle non vérifié)."""
    url = (url or config.OLLAMA_URL).rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=5) as rep:
            return rep.status == 200
    except Exception:
        return False


def decouper_chunks(texte: str, max_chars: Optional[int] = None) -> List[str]:
    """Découpe aux frontières de paragraphes (jamais au milieu d'une phrase)."""
    max_chars = max_chars or config.INCISES_CHUNK_CHARS
    paras = [p.strip() for p in re.split(r"\n\s*\n", texte or "") if p.strip()]
    chunks, courant = [], ""
    for p in paras:
        if courant and len(courant) + len(p) + 2 > max_chars:
            chunks.append(courant)
            courant = ""
        courant = f"{courant}\n\n{p}" if courant else p
    if courant:
        chunks.append(courant)
    return chunks


def _tokens(texte: str) -> List[str]:
    return re.findall(r"[a-zàâäéèêëîïôöùûüçœæ']+", texte.lower())


def rappel_lexical(entree: str, segments: List[dict]) -> float:
    """Part des mots de l'entrée retrouvés dans la sortie (garde anti-perte).

    Les mots situés dans les incises détectées (regex) sont exclus du
    dénominateur : leur suppression est exactement le travail demandé.
    """
    from collections import Counter
    amovibles = Counter()
    for inc in detecter_incises(entree):
        amovibles.update(_tokens(entree[inc.debut:inc.fin]))
    attendus = list((Counter(_tokens(entree)) - amovibles).elements())
    if not attendus:
        return 1.0
    vocab_out = set(_tokens(" ".join(s.get("texte", "") for s in segments)))
    # le nom du locuteur compte comme « retrouvé » (attribution, pas perte)
    for s in segments:
        vocab_out.update(_tokens(s.get("personnage", "")))
    return sum(1 for w in attendus if w in vocab_out) / len(attendus)


def incises_residuelles(segments: List[dict]) -> List[str]:
    """Dialogues contenant encore une incise (parole ou action : juge regex).

    Un segment "dialogue" ne doit jamais porter de proposition en
    verbe-pronom (« dit-il », « se leva-t-il »...) : une telle forme est
    toujours une incise à traiter, jamais du texte parlé.
    """
    residus = []
    for s in segments:
        if s.get("type") != "dialogue":
            continue
        for inc in detecter_incises(s.get("texte", "")):
            residus.append(inc.texte)
    return residus


def valider_sortie(entree: str, data: dict) -> List[str]:
    """Renvoie la liste des problèmes (vide = valide)."""
    problemes = []
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        return ["JSON sans liste 'segments'"]
    if not data["segments"]:
        return ["aucun segment produit"]
    for i, s in enumerate(data["segments"]):
        if not isinstance(s, dict) or not (s.get("personnage") or "").strip():
            problemes.append(f"segment {i} : personnage vide")
        if not (s.get("texte") or "").strip():
            problemes.append(f"segment {i} : texte vide")
        if s.get("type") not in ("dialogue", "narration"):
            problemes.append(f"segment {i} : type invalide")
    rappel = rappel_lexical(entree, data["segments"])
    if rappel < config.INCISES_RAPPEL_MIN:
        problemes.append(f"rappel lexical {rappel:.0%} < {config.INCISES_RAPPEL_MIN:.0%} (perte de texte ?)")
    residus = incises_residuelles(data["segments"])
    if residus:
        problemes.append(f"incises de parole restantes : {residus[:3]}")
    return problemes


def traiter_chunk(chunk: str, connus: List[str], dernier: Optional[str],
                  narrateur: str = "Narrateur", narrateur_je: Optional[str] = None,
                  modele: Optional[str] = None, url: Optional[str] = None,
                  appeler: Callable[..., str] = appeler_ollama) -> dict:
    """Traite un chunk : appel LLM + 1 recadrage si invalide (lève sinon)."""
    je = narrateur_je or narrateur
    systeme = SYSTEME % (narrateur, je, narrateur, narrateur)
    entete = (f"Personnages connus : {', '.join(connus) if connus else '(aucun, tout locuteur nommé est nouveau)'}. "
              f"Dernier locuteur : {dernier or '(aucun)'}. "
              f"Narrateur : {narrateur}.\n<extrait>{chunk}</extrait>")
    reponse = appeler(entete, systeme, modele, url)
    data = _extraire_json(reponse)
    problemes = valider_sortie(chunk, data) if data is not None else ["réponse non-JSON"]
    if problemes:
        reponse2 = appeler(RECADRAGE % (" ; ".join(problemes), chunk), systeme, modele, url)
        data2 = _extraire_json(reponse2)
        problemes2 = valider_sortie(chunk, data2) if data2 is not None else ["réponse non-JSON"]
        if problemes2:
            raise ErreurLLM(f"chunk rejeté ({len(chunk)} car.) : {'; '.join(problemes2)}")
        return data2
    return data


def _extraire_json(reponse: str) -> Optional[dict]:
    try:
        return json.loads(reponse)
    except Exception:
        pass
    m = re.search(r"\{.*\}", reponse, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def traiter_replique(replique: str, locuteur: str, narrateur: str = "Narrateur",
                     modele: Optional[str] = None, url: Optional[str] = None,
                     appeler: Callable[..., str] = appeler_ollama) -> dict:
    """Nettoie UNE réplique au locuteur connu (lève ``ErreurLLM`` si rejetée)."""
    from .incises import _TAG_RE as _TRE
    corps = replique
    m = _TRE.match(replique)
    if m:
        corps = m.group(2)
    systeme = SYSTEME_REPLIQUE % (locuteur, narrateur)
    prompt = f"Locuteur : {locuteur}.\n<replique>{corps}</replique>"
    for tentative in range(2):
        reponse = appeler(prompt if tentative == 0
                          else _RECADRAGE_REPLIQUE % (" ; ".join(problemes), locuteur, corps),
                          systeme, modele, url)
        data = _extraire_json(reponse)
        problemes = _valider_replique(corps, data)
        if not problemes:
            return data
    raise ErreurLLM(f"réplique rejetée ({locuteur}) : {'; '.join(problemes)}")


def _valider_replique(corps: str, data: Optional[dict]) -> List[str]:
    if not isinstance(data, dict) or not (data.get("replique") or "").strip():
        return ["JSON sans 'replique'"]
    if not isinstance(data.get("actions", []), list):
        return ["'actions' n'est pas une liste"]
    problemes = []
    rappel = rappel_lexical(corps, [{"texte": data["replique"] + " " +
                                     " ".join(data.get("actions", []))}])
    if rappel < config.INCISES_RAPPEL_MIN:
        problemes.append(f"rappel {rappel:.0%} < {config.INCISES_RAPPEL_MIN:.0%}")
    for inc in detecter_incises(data["replique"]):
        problemes.append(f"incise restante dans la réplique : {inc.texte}")
        break
    return problemes


def _action_valide(act: str, loc: str, narrateur: str) -> bool:
    """Une action narration doit être une vraie phrase, pas un nom lâché."""
    mots = _tokens(act)
    if len(mots) < 2:
        return False
    normalise = re.sub(r"\s+", " ", act.strip().lower().strip(".,;:!?… "))
    if normalise in (loc.lower(), narrateur.lower()):
        return False
    return True


def _nettoyer_marques_dialogue(texte: str) -> str:
    """Retire les marques de dialogue en bords (tirets, guillemets : rien en TTS)."""
    t = re.sub(r"^[—–\-«»\"'\s,;]+", "", texte)
    return re.sub(r"[«»\"'—–\-\s,;]+$", "", t).strip()


def nettoyer_llm(texte: str, mapping: Optional[Dict[str, str]] = None,
                 voix_defaut: str = "Narrateur",
                 narrateur_je: Optional[str] = None,
                 modele: Optional[str] = None, url: Optional[str] = None,
                 repli_regex: bool = True,
                 appeler: Callable[..., str] = appeler_ollama,
                 progress: Optional[Callable[[int, int], None]] = None,
                 filtre: Optional[FiltrePersonnages] = None) -> ResultatNettoyage:
    """Nettoie les incises via LLM, chunk par chunk, avec repli regex ciblé.

    ``mapping`` : personnages connus (clés). Tout nom hors mapping rencontré
    devient « nouveau » (à merger au ``.map`` via ``synchroniser_map``).
    ``filtre`` : ``FiltrePersonnages`` anti faux positifs (``None`` = garde
    historique « doit parler dans la sortie » uniquement).
    """
    mapping = dict(mapping or {})
    chunks = decouper_chunks(texte)
    if not chunks:
        return ResultatNettoyage(texte="", nouveaux_personnages=[], stats={})
    connus = list(mapping) or [voix_defaut]
    dernier: Optional[str] = None
    lignes: List[str] = []
    nouveaux: List[str] = []
    stats = {"lignes": 0, "chunks": len(chunks), "chunks_replis_regex": 0,
             "incises": 0, "parole_retirees": 0, "actions_narration": 0,
             "segments_dialogue": 0, "segments_narration": 0,
             "personnages_ajoutes": 0}
    from .incises import _TAG_RE as _TRE
    for i, chunk in enumerate(chunks):
        if progress:
            progress(i + 1, len(chunks))
        # Lignes déjà taggées [Nom]: → locuteur imposé (nettoyage ciblé,
        # jamais réattribué). Sinon : attribution complète par le LLM.
        if _TRE.search(chunk):
            dernier = _nettoyer_chunk_tagge(
                chunk, connus, dernier, voix_defaut, narrateur_je,
                modele, url, appeler, repli_regex,
                lignes, nouveaux, stats, _TRE)
            continue
        try:
            data = traiter_chunk(chunk, connus, dernier, voix_defaut,
                                 narrateur_je, modele, url, appeler)
        except ErreurLLM as exc:
            if not repli_regex:
                raise
            stats["chunks_replis_regex"] += 1
            data = _repli_chunk_regex(chunk, connus, dernier, voix_defaut,
                                      narrateur_je, lignes, nouveaux, stats)
            dernier = data.get("_dernier", dernier)
            continue
        for s in data["segments"]:
            texte_seg = s["texte"].strip()
            if s.get("type") == "dialogue":
                texte_seg = _nettoyer_marques_dialogue(texte_seg)
            elif not _action_valide(texte_seg, s["personnage"], voix_defaut):
                continue
            lignes.append(f"[{s['personnage'].strip()}]: {texte_seg}")
            if s.get("type") == "dialogue":
                dernier = s["personnage"].strip()
                stats["segments_dialogue"] += 1
            else:
                stats["segments_narration"] += 1
        for nom in data.get("nouveaux_personnages", []) or []:
            nom = (nom or "").strip()
            if nom and nom not in mapping and nom not in connus and nom not in nouveaux:
                nouveaux.append(nom)
                connus.append(nom)
    # garde-fou historique : un « nouveau » sans aucun segment à son nom =
    # nom mentionné, pas locuteur → on ne le propose pas.
    parleurs = {re.match(r"^\s*\[([^\]]+)\]", l).group(1).strip()
                for l in lignes if re.match(r"^\s*\[([^\]]+)\]", l)}
    nouveaux = [n for n in nouveaux if n in parleurs]
    if filtre is not None:
        nouveaux, rejetes = filtrer_nouveaux_personnages(
            nouveaux, texte or "", lignes, mapping, voix_defaut, filtre)
        stats["personnages_rejetes"] = rejetes
    stats["lignes"] = len(lignes)
    stats["personnages_ajoutes"] = len(nouveaux)
    return ResultatNettoyage(texte="\n\n".join(lignes) + ("\n" if lignes else ""),
                             nouveaux_personnages=nouveaux, stats=stats)


def _nettoyer_chunk_tagge(chunk: str, connus: List[str], dernier: Optional[str],
                          voix_defaut: str, narrateur_je: Optional[str],
                          modele: Optional[str], url: Optional[str],
                          appeler: Callable[..., str], repli_regex: bool,
                          lignes: List[str], nouveaux: List[str],
                          stats: Dict, tag_re) -> Optional[str]:
    """Chunk mixte/taggué : chaque ligne garde son locuteur imposé.

    - ligne ``[Nom]: corps`` → appel cibré (incises seules), tag conservé ;
    - ligne nue → reprend le locuteur courant (sémantique ``tagging.py``),
      texte verbatim (la prose ne porte pas d'incise) ;
    - ``[stop]`` / ``#`` / vide → conservé/ignoré comme le parser.
    """
    for raw in chunk.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "[stop]":
            lignes.append("[stop]")
            continue
        m = tag_re.match(raw)
        if m:
            loc, corps = m.group(1).strip(), m.group(2)
            if not corps:
                continue
            from .incises import _DIALOGUE_RE as _DRE, detecter_incises as _det
            # prose taggée sans marque de dialogue ni incise : verbatim
            # (l'appel ciblé ne sert que pour les répliques).
            if not _det(corps) and not _DRE.match(corps.strip()):
                lignes.append(f"[{loc}]: {corps.strip()}")
                stats["segments_narration"] += 1
                dernier = loc
                continue
            try:
                data = traiter_replique(corps, loc, voix_defaut, modele, url, appeler)
                # Ligne taggée : le locuteur imposé est conservé et aucun
                # nouveau personnage n'en sort (critère M20.8).
                loc_eff = loc
            except ErreurLLM:
                if not repli_regex:
                    raise
                stats["chunks_replis_regex"] += 1
                data = _repli_replique_regex(corps, loc, voix_defaut, stats)
                loc_eff = data["loc"]
            replique = _nettoyer_marques_dialogue(data["replique"].strip())
            if replique:
                lignes.append(f"[{loc_eff}]: {replique}")
                stats["segments_dialogue"] += 1
            for act in data.get("actions", []) or []:
                if act.strip() and _action_valide(act, loc_eff, voix_defaut):
                    lignes.append(f"[{voix_defaut}]: {act.strip()}")
                    stats["segments_narration"] += 1
            dernier = loc_eff
        else:
            loc = dernier or voix_defaut
            lignes.append(f"[{loc}]: {stripped}")
            stats["segments_narration"] += 1
            dernier = dernier or voix_defaut
    return dernier


def _repli_replique_regex(corps: str, loc: str, voix_defaut: str,
                          stats: Dict) -> dict:
    """Repli déterministe pour UNE réplique taggée rejetée."""
    res = nettoyer_regex(f"[{loc}]: {corps}", mode="nettoyer_tagge",
                         keep_action="narration",
                         mapping={loc: loc, voix_defaut: voix_defaut},
                         voix_defaut=voix_defaut)
    replique, actions, loc_eff = "", [], loc
    for raw in res.texte.splitlines():
        mm = re.match(r"^\s*\[([^\]]+)\]\s*:?\s*(.*)$", raw)
        if not mm:
            continue
        if mm.group(1).strip() == loc and not replique:
            replique, loc_eff = mm.group(2), loc
        elif mm.group(1).strip() == loc:
            loc_eff = loc
        else:
            actions.append(mm.group(2))
    stats["incises"] += res.stats.get("incises", 0)
    return {"replique": replique or corps, "actions": actions, "loc": loc_eff}


def _repli_chunk_regex(chunk: str, connus: List[str], dernier: Optional[str],
                       voix_defaut: str, narrateur_je: Optional[str],
                       lignes: List[str], nouveaux: List[str],
                       stats: Dict) -> dict:
    """Repli déterministe pour un chunk rejeté (jamais de trou en sortie)."""
    res = nettoyer_regex(chunk, mode="auto", keep_action="narration",
                         mapping={k: k for k in connus},
                         voix_defaut=voix_defaut, narrateur_je=narrateur_je)
    for raw in res.texte.splitlines():
        if raw.strip():
            lignes.append(raw.strip())
            m = re.match(r"^\s*\[([^\]]+)\]", raw)
            if m:
                stats_dernier = m.group(1).strip()
    for nom in res.nouveaux_personnages:
        if nom not in nouveaux:
            nouveaux.append(nom)
    stats["incises"] += res.stats.get("incises", 0)
    return {"_dernier": dernier}
