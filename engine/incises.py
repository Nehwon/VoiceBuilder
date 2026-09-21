"""Détection et nettoyage des incises de dialogue (M20).

Une *incise* est la proposition qui attribue une réplique à son locuteur
dans un roman : « …, dit-il », « — Viens, murmura-t-elle en se levant »,
« … s'exclama Lambda ».

Rôles :
  - ``detecter_incises`` : repère les incises dans une ligne.
  - ``resoudre_locuteur`` : nom propre > pronom (dernier locuteur / Narrateur).
  - ``nettoyer`` : deux modes — ``import_roman`` (roman brut avec —/«» →
    texte taggé ``[Nom]:``) et ``nettoyer_tagge`` (texte déjà taggé, on
    retire les incises faibles) ; les incises d'action basculent en
    ``[Narrateur]:`` par défaut (``keep_action="narration"``).
  - ``synchroniser_map`` : ajoute les personnages détectés manquant au
    mapping ``{personnage: voix}`` (fichier ``.map``, jamais ``voix.txt``).

Verbes *de parole purs* (sans intérêt vocal : la voix porte déjà
l'attribution) → retirés. Verbes d'*action* (se lever, sourire, …) →
basculés en narration pour ne pas les faire dire par le personnage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Verbes de parole purs (retirés car redondants à la synthèse)
# ---------------------------------------------------------------------------
# Formes conjuguées courantes à l'inversion (présent / passé simple /
# imparfait / conditionnel, 3e pers. + 1re pers. pour « dis-je »).
_VERBES_PAROLE_FORMES = {
    # dire
    "dis", "dit", "disent", "disait", "disent", "dirait", "disaient",
    # répondre / demander / répliquer / ajouter / déclarer & co
    "répond", "répondit", "répondait", "répondrait",
    "demande", "demanda", "demandait", "demanderait",
    "réplique", "répliqua", "répliquait",
    "ajoute", "ajouta", "ajoutait",
    "déclare", "déclara", "déclarait",
    "affirme", "affirma", "affirmait",
    "annonce", "annonça", "annonçait",
    "avoue", "avoua", "avouait",
    "explique", "expliqua", "expliquait",
    "conclut", "concluait",
    "poursuit", "poursuivit", "poursuivait",
    "reprend", "reprit", "reprenait",
    "rétorque", "rétorqua", "rétorquait",
    "lance", "lança", "lançait",
    # murmurer / chuchoter / susurrer / marmonner / grommeler / bredouiller
    "murmure", "murmura", "murmurait", "murmurerait",
    "chuchote", "chuchota", "chuchotait",
    "susurre", "susurra", "susurrait",
    "marmonne", "marmonna", "marmonnait",
    "grommelle", "grommela", "grommelait",
    "bredouille", "bredouilla", "bredouillait",
    "balbutie", "balbutia", "balbutiait",
    "bafouille", "bafouilla", "bafouillait",
    "bégaye", "bégaya", "bégayait",
    # crier / hurler / s'exclamer / s'écrier / soupirer / souffler / geindre
    "crie", "cria", "criait",
    "hurle", "hurla", "hurlait",
    "exclame", "exclama", "exclamait",
    "écrie", "écria", "écriait",
    "soupire", "soupira", "soupirait",
    "souffle", "souffla", "soufflait",
    "geint", "geignit", "geignait",
    "grogne", "grogna", "grognat", "grognait",
    "ricane", "ricana", "ricanait",
    "râle", "râla", "râlait",
    "sanglote", "sanglota", "sanglotait",
    "chantonne", "chantonna", "chantonnait",
    "fredonne", "fredonna", "fredonnait",
    # faire (fit-il) / redire…
    "fit", "fait", "faisait", "ferait", "font",
    "redit", "redis", "redemand", "redemanda",
    "interroge", "interrogea", "interrogeait",
    "interrompt", "interrompit", "interrompait",
    "corrige", "corrigea", "corrigeait",
    "insiste", "insista", "insistait",
    "avertit", "avertit", "avertissait",
    "prévient", "prévint", "prévenait",
    "ordonne", "ordonna", "ordonnait",
    "supplie", "supplia", "suppliait",
    "implore", "implora", "implorait",
    "proteste", "protesta", "protestait",
    "ironise", "ironisa", "ironisait",
    "plaisante", "plaisanta", "plaisantait",
    "souligne", "souligna", "soulignait",
    "résume", "résuma", "résumait",
    "termine", "termina", "terminait",
    "conclue", "concluait",
}

# Radicaux distinctifs (repli si une forme fléchie manque ci-dessus).
_VERBES_PAROLE_RADICAUX = (
    "murmur", "chuchot", "susurr", "marmonn", "grommel", "bredouill",
    "balbuti", "bafouill", "bégay", "exclam", "écri", "répliqu",
    "rétorqu", "interromp", "interrog", "poursuiv", "soupir", "sanglot",
    "chantonn", "fredonn", "ironis", "plaisant", "protest", "suppli",
    "implor", "averti", "prévien", "ordonn", "insist",
)

_PRONOMS_INVERSION = ("il", "elle", "on", "ils", "elles", "je", "tu", "nous", "vous")

# verbe(-t)?-pronom : « dit-il », « murmura-t-elle », « dis-je »
_RE_INVERSION = re.compile(
    r"\b([A-Za-zÀÂÄÉÈÊËÎÏÔÖÙÛÜàâäéèêëîïôöùûüçÇ']+(?:-[A-Za-zÀ-ÿ']+)?)"
    r"(?:-t)?-(" + "|".join(_PRONOMS_INVERSION) + r")\b",
    re.IGNORECASE,
)

# verbe + Nom propre : « dit Lambda », « murmura Jean », « s'exclama Marie »
_RE_VERBE_NOM = re.compile(
    r"\b([A-Za-zÀ-ÿ']+)\s+([A-ZÀÂÉÈÊËÎÏÔÙÛÜÇ][\w\-']*(?:\s+[A-ZÀÂÉÈÊËÎÏÔÙÛÜÇ][\w\-']*){0,2})\b"
)

# Complément d'incise usuel : « en riant », « en se levant », « d'une voix… »
_RE_COMPLEMENT = re.compile(
    r"^(?:\s*,?\s*(?:en\s+[a-zà-ÿ' ]+?|d'une?\s+[a-zà-ÿ' ]+?|de\s+[a-zà-ÿ' ]+?|"
    r"avec\s+[a-zà-ÿ' ]+?|sans\s+[a-zà-ÿ' ]+?|tout\s+[a-zà-ÿ' ]+?))?"
    r"(?=[,.;:!?…]|\s+[—–-]\s*|\s*«|\s*»|$)",
    re.IGNORECASE,
)

_TAG_RE = re.compile(r"^\s*\[([^\]]+)\]\s*:?\s*(.*)$", re.MULTILINE)
_DIALOGUE_RE = re.compile(r"^\s*(?:—|–|-|\u00ab|\"|')")


def _nettoyer_verbe(token: str) -> str:
    """Normalise un token verbal (réfléchi/apostrophe retirés, minuscules)."""
    t = token.strip().lower().lstrip("«»\"' ").rstrip("«»\"' ")
    for prefixe in ("s'exclama", "s'écria"):
        if t.startswith(prefixe[:6]):
            pass
    # « s'exclama » → « exclama », « s'écria » → « écria »
    if t.startswith("s'"):
        t = t[2:]
    elif t.startswith("se "):
        t = t[3:]
    # euphonique « -t- » capté par gourmandise de la regex (« murmura-t »)
    if t.endswith("-t"):
        t = t[:-2]
    # que le dernier segment en cas de trait d'union verbal (« se-… »)
    if "-" in t and not t.startswith(("exclama", "écria")):
        t = t.split("-")[-1]
    return t.strip(".,;:!?… ")


def _est_verbe_parole(token: str) -> bool:
    t = _nettoyer_verbe(token)
    if t in _VERBES_PAROLE_FORMES:
        return True
    return any(rad in t for rad in _VERBES_PAROLE_RADICAUX)


@dataclass
class Incise:
    debut: int
    fin: int
    texte: str
    verbe: str
    locuteur_brut: Optional[str]  # nom propre ou pronom (« il », « je »…)
    est_parole: bool
    confiance: str = "haute"  # haute | faible


@dataclass
class LigneNettoyee:
    lignes: List[str] = field(default_factory=list)
    nouveaux: List[str] = field(default_factory=list)
    incises: int = 0
    parole_retirees: int = 0
    actions_narration: int = 0


@dataclass
class ResultatNettoyage:
    texte: str
    nouveaux_personnages: List[str]
    stats: Dict[str, int]


def detecter_incises(corps: str) -> List[Incise]:
    """Repère les incises dans un corps de ligne (dialogue ou taggé)."""
    trouvees: List[Incise] = []
    for m in _RE_INVERSION.finditer(corps):
        verbe, pronom = m.group(1), m.group(2).lower()
        debut = m.start()
        # recule sur une virgule / tiret d'incise ouvrant collé
        while debut > 0 and corps[debut - 1] in " ,":
            debut -= 1
        # absorbe le réfléchi préverbal (« se leva-t-il », « s'exclama-t-il »)
        refl = _RE_REFL.search(corps[:debut])
        if refl:
            debut -= len(refl.group(0))
            while debut > 0 and corps[debut - 1] in " ,":
                debut -= 1
        fin = m.end()
        # absorbe le complément (« en riant », « d'une voix basse »…)
        comp = _RE_COMPLEMENT.match(corps[fin:fin + 80])
        if comp and comp.group(0).strip(" ,"):
            fin += len(comp.group(0))
        # absorbe la ponctuation fermante de l'incise
        while fin < len(corps) and corps[fin] in " ,":
            fin += 1
        trouvees.append(Incise(
            debut=debut, fin=fin, texte=corps[debut:fin].strip(" ,"),
            verbe=_nettoyer_verbe(verbe), locuteur_brut=pronom,
            est_parole=_est_verbe_parole(verbe),
        ))
    for m in _RE_VERBE_NOM.finditer(corps):
        verbe, nom = m.group(1), m.group(2).strip(".,;:!?… ")
        # évite les doublons avec une inversion déjà trouvée au même endroit
        if any(abs(m.start() - t.debut) < 4 for t in trouvees):
            continue
        if not _est_verbe_parole(verbe) and not _ressemble_action(verbe):
            continue
        # le « nom » doit ressembler à un prénom/nom (pas un début de phrase)
        mots = nom.split()
        if not mots or len(nom) > 40:
            continue
        debut = m.start()
        while debut > 0 and corps[debut - 1] in " ,":
            debut -= 1
        fin = m.end()
        comp = _RE_COMPLEMENT.match(corps[fin:fin + 80])
        if comp and comp.group(0).strip(" ,"):
            fin += len(comp.group(0))
        while fin < len(corps) and corps[fin] in " ,":
            fin += 1
        # borne le nom au premier mot capitalisé (le reste = complément)
        premier = mots[0].strip(".,;:!?… ")
        trouvees.append(Incise(
            debut=debut, fin=fin, texte=corps[debut:fin].strip(" ,"),
            verbe=_nettoyer_verbe(verbe), locuteur_brut=premier,
            est_parole=_est_verbe_parole(verbe),
        ))
    trouvees.sort(key=lambda i: i.debut)
    return trouvees


def _ressemble_action(verbe: str) -> bool:
    """Un verbe d'action à l'inversion (ex. « se leva-t-il », « sourit-elle »)."""
    t = _nettoyer_verbe(verbe)
    if not t or _est_verbe_parole(t):
        return False
    # forme verbale + pronom déjà validée par la regex d'appel ; on exige
    # une terminaison verbale plausible pour limiter les faux positifs.
    return bool(re.search(r"(a|ait|e|it|t|nt|ra|rait)$", t))


def resoudre_locuteur(incise: Incise, locuteur_courant: Optional[str],
                      dernier_locuteur: Optional[str],
                      narrateur_je: Optional[str] = None) -> Tuple[str, str]:
    """Renvoie ``(nom, confiance)`` pour une incise.

    - nom propre (``dit Lambda``) → le nom, confiance haute ;
    - ``je`` → ``narrateur_je`` (ex. ``--narrateur-je Michel``) sinon le
      locuteur courant, confiance faible (sauf ``narrateur_je`` donné) ;
    - ``il/elle/on/ils/elles/tu/nous/vous`` → dernier locuteur connu sinon
      locuteur courant, confiance faible si repli.
    """
    brut = (incise.locuteur_brut or "").strip()
    if not brut:
        repli = locuteur_courant or dernier_locuteur or "Narrateur"
        return repli, "faible"
    if brut.lower() not in _PRONOMS_INVERSION:
        return brut, "haute"
    if brut.lower() == "je":
        if narrateur_je:
            return narrateur_je, "haute"
        repli = locuteur_courant or dernier_locuteur or "Narrateur"
        return repli, "faible"
    if dernier_locuteur:
        return dernier_locuteur, "haute"
    repli = locuteur_courant or "Narrateur"
    return repli, "faible"


_RE_REFL = re.compile(r"(?:^|[\s,«»\"'—–\-])(?:se|s'|s’|me|m'|te|t'|nous|vous)\s*$", re.IGNORECASE)


def _recoller(replique: str) -> str:
    """Nettoie ponctuation/espaces après excision d'une incise."""
    t = re.sub(r"\s{2,}", " ", replique).strip()
    # bords de dialogue résiduels : « », tirets, virgules orphelines
    t = re.sub(r"^[«»\"'—–\-\s,;]+", "", t)
    t = re.sub(r"[«»\"'—–\-\s,;]+$", "", t)
    # les guillemets ne portent rien à la TTS : on les retire partout
    t = t.replace("«", "").replace("»", "").replace('"', "")
    t = re.sub(r"\s{2,}", " ", t).strip()
    # virgule orpheline devant une ponctuation finale (« ici », . → « ici ».)
    t = re.sub(r",\s*([.!?…])", r"\1", t)
    # « Bonjour , . » → « Bonjour. » ; « dit… , suite » → sans trou
    t = re.sub(r"\s+([,.;:!?…»])", r"\1", t)
    t = re.sub(r"([«—–-])\s+", r"\1 ", t)
    t = re.sub(r"[.]{4,}", "...", t)
    return t.strip()


def _phrase_narration(incise: Incise, locuteur: str) -> str:
    """Reformule une incise d'action pour la voix du narrateur."""
    txt = incise.texte.strip(" ,.;:!?…")
    if not txt:
        return ""
    # « murmura-t-elle en se levant » → « murmura-t-elle en se levant. »
    # On préfixe le locuteur si l'incise portait un nom (« dit Lambda en
    # riant » → « dit Lambda en riant. ») pour garder l'info.
    phrase = txt[0].upper() + txt[1:] if txt[0].islower() else txt
    if not phrase.endswith((".", "!", "?", "…")):
        phrase += "."
    return phrase


def synchroniser_map(mapping: Dict[str, str], nouveaux: List[str],
                     voix_defaut: str = "Narrateur") -> Dict[str, str]:
    """Ajoute les personnages manquants au mapping (``.map`` seul).

    Ne touche jamais à ``voix.txt`` : chaque nouveau nom est mappé sur
    ``voix_defaut`` (à réassigner dans le panneau Personnages).
    """
    out = dict(mapping)
    for nom in nouveaux:
        nom = (nom or "").strip()
        if nom and nom not in out:
            out[nom] = voix_defaut
    return out


# ---------------------------------------------------------------------------
# Filtres anti faux positifs sur les nouveaux personnages (M20.7)
# ---------------------------------------------------------------------------
# Un nom détecté dans une incise (« dit X ») ou proposé par le LLM n'est pas
# forcément un personnage à créer : titres/fonctions (« Maître », « Madame »),
# noms simplement mentionnés dans la narration, coquilles du LLM, hapax…
# Ces filtres s'appliquent aux DEUX moteurs (regex et LLM), avant tout ajout
# au ``.map``. Chaque rejet est motivé (stats ``personnages_rejetes``).

def _sans_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


# Titres, fonctions, liens de parenté, éléments et notions abstraites :
# jamais des personnages à créer (même capitalisés : « le Maître », « la
# Terre », « Maman »). Complétés par l'heuristique minuscule ci-dessous.
STOP_PERSONNAGES = frozenset({
    "maitre", "maitresse", "madame", "monsieur", "mademoiselle",
    "docteur", "docteure", "professeur", "professeure", "maitreesse",
    "capitaine", "lieutenant", "colonel", "general", "generale",
    "sergent", "officier", "soldat", "garde", "serviteur", "servante",
    "maman", "papa", "mere", "pere", "fils", "fille", "frere", "soeur",
    "oncle", "tante", "cousin", "cousine", "neveu", "niece",
    "ami", "amie", "voisin", "voisine", "patron", "patronne", "chef",
    "roi", "reine", "prince", "princesse", "dieu", "diable", "demon",
    "monsieur", "madame", "enfant", "homme", "femme", "vieillard",
    "inconnu", "inconnue", "voix", "ombre", "silhouette",
    "pilier", "terre", "eau", "feu", "air", "lumiere", "tenebres",
    "memoire", "partage", "destin", "silence", "nuit", "jour", "mort",
    "vie", "monde", "temps", "ciel", "soleil", "lune", "neant", "vide",
})

_NOM_PROPRE_RE = re.compile(
    r"^[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ][a-zàâäéèêëîïôöùûüçœæ'\-’]*"
    r"(?:\s+[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ][a-zàâäéèêëîïôöùûüçœæ'\-’]*"
    r"|\s+[a-zàâäéèêëîïôöùûüçœæ'\-’]+){0,3}$"
)


# Le tiret cadratin ouvre un dialogue anonyme : seule une réplique qui en
# commence par un peut révéler un NOUVEAU personnage (« dit X »). Une ligne
# déjà taggée ``[Nom]:`` n'en révèle jamais (critère M20.8).
TIRET_CADRATIN = "—"


def _est_replique_cadratin(ligne: str) -> bool:
    return ligne.strip().startswith(TIRET_CADRATIN)


@dataclass
class FiltrePersonnages:
    """Seuils de validation d'un candidat personnage.

    - ``min_repliques`` : répliques « dialogue » attribuées au nom dans la
      sortie (défaut 2 : un hapax ne justifie pas une voix à créer).
    - ``preuve_incise`` : exige une incise explicite « dit X » portée par une
      réplique en tiret cadratin dans la source — coupe les hallucinations
      du LLM et les noms mentionnés.
    - ``verif_minuscule`` : rejette le candidat si sa forme minuscule existe
      dans la source (« Terre » vs « terre » = nom commun, pas un locuteur).
    - ``stop_mots`` : génériques supplémentaires (minuscules, sans accents).
    """
    min_repliques: int = 2
    preuve_incise: bool = True
    verif_minuscule: bool = True
    stop_mots: frozenset = frozenset()


def _normaliser_nom(nom: str) -> str:
    """Clé de comparaison floue : « Kaël-An » == « Kael-An » == « kaelan »."""
    return re.sub(r"[^a-z0-9]", "", _sans_accents(nom.lower()))


def noms_incises_source(texte: str) -> set:
    """Noms propres portés par une incise explicite dans la source.

    Seules comptent les répliques en tiret cadratin : une ligne déjà taggée
    ``[Nom]:`` ne révèle jamais un nouveau personnage (critère M20.8).
    """
    preuves = set()
    for raw in (texte or "").splitlines():
        if _TAG_RE.match(raw):
            continue
        if not _est_replique_cadratin(raw):
            continue
        for inc in detecter_incises(raw.strip()):
            brut = (inc.locuteur_brut or "").strip()
            if brut and brut.lower() not in _PRONOMS_INVERSION:
                preuves.add(brut)
    return preuves


def _forme_minuscule_presente(nom: str, texte_source: str) -> bool:
    """Vrai si un mot du candidat existe en minuscules dans la source.

    « Pilier » + « pilier » ailleurs = nom commun capitalisé en début de
    phrase ou par emphase, pas un locuteur. Un vrai prénom n'apparaît
    jamais en minuscules (hors coquille).
    """
    for mot in nom.split():
        if len(mot) < 3:
            continue
        if re.search(r"\b" + re.escape(mot.lower()) + r"\b", texte_source or ""):
            return True
    return False


def _compter_dialogues(lignes_sortie: List[str]) -> Dict[str, int]:
    """Nombre de segments attribués à chaque nom dans la sortie taggée."""
    comptes: Dict[str, int] = {}
    for ligne in lignes_sortie:
        m = re.match(r"^\s*\[([^\]]+)\]", ligne)
        if m:
            nom = m.group(1).strip()
            comptes[nom] = comptes.get(nom, 0) + 1
    return comptes


def filtrer_nouveaux_personnages(
    candidats: List[str],
    texte_source: str,
    lignes_sortie: List[str],
    mapping: Optional[Dict[str, str]] = None,
    voix_defaut: str = "Narrateur",
    filtre: Optional[FiltrePersonnages] = None,
) -> tuple:
    """Sépare les candidats en ``(acceptes, rejetes)``.

    ``rejetes`` : dict ``{nom: motif}`` pour affichage (CLI, GUI, stats).
    ``filtre=None`` : comportement historique (aucun filtrage).
    """
    if filtre is None:
        return list(candidats), {}
    mapping = mapping or {}
    stop = STOP_PERSONNAGES | {_sans_accents(s.lower()) for s in filtre.stop_mots}
    connus_norm = {_normaliser_nom(k): k for k in mapping}
    preuves = noms_incises_source(texte_source) if filtre.preuve_incise else set()
    dialogues = _compter_dialogues(lignes_sortie)
    acceptes: List[str] = []
    rejetes: Dict[str, str] = {}
    for brut in candidats:
        nom = (brut or "").strip()
        if not nom:
            continue
        if nom.lower() == (voix_defaut or "").lower():
            rejetes[nom] = "voix par défaut, pas un personnage"
            continue
        deja = connus_norm.get(_normaliser_nom(nom))
        if deja is not None:
            rejetes[nom] = f"déjà au .map (référence : {deja})"
            continue
        if nom.lower() in _PRONOMS_INVERSION:
            rejetes[nom] = "pronom, pas un nom"
            continue
        if _sans_accents(nom.lower()) in stop:
            rejetes[nom] = "titre/fonction ou nom générique"
            continue
        if len(nom) < 2 or not _NOM_PROPRE_RE.match(nom):
            rejetes[nom] = "ne ressemble pas à un nom propre"
            continue
        if (filtre.verif_minuscule
                and _forme_minuscule_presente(nom, texte_source)):
            rejetes[nom] = "nom commun (forme minuscule présente dans le texte)"
            continue
        if filtre.preuve_incise and nom not in preuves:
            rejetes[nom] = "aucune incise « dit X » en réplique cadratin"
            continue
        nb = dialogues.get(nom, 0)
        if nb < filtre.min_repliques:
            rejetes[nom] = (f"une seule réplique ({nb} < {filtre.min_repliques})"
                            if nb <= 1 else
                            f"pas assez de répliques ({nb} < {filtre.min_repliques})")
            continue
        acceptes.append(nom)
    return acceptes, rejetes


def nettoyer(texte: str, mode: str = "auto",
             keep_action: str = "narration",
             mapping: Optional[Dict[str, str]] = None,
             voix_defaut: str = "Narrateur",
             narrateur_je: Optional[str] = None,
             filtre: Optional[FiltrePersonnages] = None) -> ResultatNettoyage:
    """Nettoie les incises d'un texte, tous modes.

    - ``import_roman`` : roman brut (—/«») → lignes taggées ``[Nom]:`` ;
      la prose hors dialogue va au ``Narrateur``.
    - ``nettoyer_tagge`` : texte déjà taggé, on retire les incises faibles.
    - ``auto`` : taggé si une ligne ``[Nom]:`` existe, sinon import.
    - ``keep_action`` : ``narration`` (incise d'action → ``[Narrateur]:``),
      ``garder`` (laissée dans la réplique), ``supprimer`` (retirée aussi).
    - ``filtre`` : ``FiltrePersonnages`` anti faux positifs sur les nouveaux
      noms (``None`` = comportement historique, aucun filtrage).
    """
    if mode not in ("auto", "import_roman", "nettoyer_tagge"):
        raise ValueError(f"Mode inconnu : {mode}")
    if keep_action not in ("narration", "garder", "supprimer"):
        raise ValueError(f"keep_action inconnu : {keep_action}")
    if mode == "auto":
        mode = "nettoyer_tagge" if _TAG_RE.search(texte or "") else "import_roman"

    mapping = dict(mapping or {})
    sortie: List[str] = []
    nouveaux: List[str] = []
    stats = {"lignes": 0, "incises": 0, "parole_retirees": 0,
             "actions_narration": 0, "personnages_ajoutes": 0}
    dernier: Optional[str] = None

    for raw in (texte or "").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if raw.strip() == "[stop]":
            sortie.append("[stop]")
            continue
        stats["lignes"] += 1
        m = _TAG_RE.match(raw)
        if m and mode == "nettoyer_tagge":
            loc, corps = m.group(1).strip(), m.group(2)
            loc_effectif = loc
            incises = detecter_incises(corps)
            if not incises:
                sortie.append(f"[{loc}]: {corps}" if corps else f"[{loc}]:")
                dernier = dernier if dernier else loc
                if loc_effectif and loc_effectif not in mapping and loc_effectif not in nouveaux:
                    pass  # tag explicite : pas un « nouveau » du plugin
                dernier = loc
                continue
            stats["incises"] += len(incises)
            # le locuteur des pronoms = le tag courant (ou le dernier)
            loc_resolu = loc
            for inc in incises:
                nom, _conf = resoudre_locuteur(inc, loc, dernier, narrateur_je)
                if inc.locuteur_brut and inc.locuteur_brut.lower() not in _PRONOMS_INVERSION:
                    loc_resolu = nom
            # Ligne déjà taggée [Nom]: → jamais de nouveau personnage
            # (critère M20.8 : seul un dialogue en tiret cadratin révèle).
            # excise de droite à gauche pour garder les offsets
            replique = corps
            narrations: List[str] = []
            for inc in sorted(incises, key=lambda i: i.debut, reverse=True):
                if inc.est_parole:
                    stats["parole_retirees"] += 1
                else:
                    if keep_action == "garder":
                        continue
                    if keep_action == "supprimer":
                        stats["parole_retirees"] += 1
                    else:
                        stats["actions_narration"] += 1
                        phrase = _phrase_narration(inc, loc_resolu)
                        if phrase:
                            narrations.append(phrase)
                replique = (replique[:inc.debut] + " " + replique[inc.fin:]).strip()
            replique = _recoller(replique)
            # si l'incise nommait un autre personnage, la réplique lui revient
            if loc_resolu != loc and replique:
                sortie.append(f"[{loc_resolu}]: {replique}")
            elif replique:
                sortie.append(f"[{loc}]: {replique}")
            for phrase in reversed(narrations):
                sortie.append(f"[{voix_defaut}]: {phrase}")
            dernier = loc_resolu
            continue

        # --- mode import (ou ligne non taggée) : dialogue ? ---
        corps = raw.strip()
        est_dialogue = bool(_DIALOGUE_RE.match(corps) or "—" in corps or "«" in corps)
        if mode == "import_roman" or not m:
            if not est_dialogue:
                # prose → narrateur (explicite pour la TTS)
                if mode == "nettoyer_tagge":
                    sortie.append(raw.strip())
                    continue
                sortie.append(f"[{voix_defaut}]: {corps}")
                dernier = dernier or voix_defaut
                continue
            incises = detecter_incises(corps)
            loc_courant = dernier
            loc_resolu: Optional[str] = None
            candidat_cadratin = _est_replique_cadratin(corps)
            for inc in incises:
                nom, _conf = resoudre_locuteur(inc, loc_courant, dernier, narrateur_je)
                if inc.locuteur_brut and inc.locuteur_brut.lower() not in _PRONOMS_INVERSION:
                    loc_resolu = nom
                    # Nouveau personnage : seulement sur réplique en tiret
                    # cadratin (critère M20.8).
                    if (candidat_cadratin and nom not in mapping
                            and nom not in nouveaux):
                        nouveaux.append(nom)
                elif loc_resolu is None:
                    loc_resolu = nom
            if loc_resolu is None:
                loc_resolu = dernier or voix_defaut
            stats["incises"] += len(incises)
            replique = corps
            narrations = []
            for inc in sorted(incises, key=lambda i: i.debut, reverse=True):
                if inc.est_parole:
                    stats["parole_retirees"] += 1
                else:
                    if keep_action == "garder":
                        continue
                    if keep_action == "supprimer":
                        stats["parole_retirees"] += 1
                    else:
                        stats["actions_narration"] += 1
                        phrase = _phrase_narration(inc, loc_resolu)
                        if phrase:
                            narrations.append(phrase)
                replique = (replique[:inc.debut] + " " + replique[inc.fin:]).strip()
            replique = _recoller(replique.strip("«»\"' "))
            if replique:
                sortie.append(f"[{loc_resolu}]: {replique}")
            for phrase in reversed(narrations):
                sortie.append(f"[{voix_defaut}]: {phrase}")
            dernier = loc_resolu
            continue

    if filtre is not None:
        acceptes, rejetes = filtrer_nouveaux_personnages(
            nouveaux, texte or "", sortie, mapping, voix_defaut, filtre)
        nouveaux = acceptes
        stats["personnages_rejetes"] = rejetes
    stats["personnages_ajoutes"] = len(nouveaux)
    return ResultatNettoyage(texte="\n\n".join(sortie) + ("\n" if sortie else ""),
                             nouveaux_personnages=nouveaux, stats=stats)
