"""M18.4 - Switch LoRA par personnage a l'inference."""
from pathlib import Path
from . import registre
ADAPTATEURS_CLE = "adaptateurs"


def resoudre(racine, voix):
    voix_map = registre.lire(racine).get("voix", {})
    try:
        return voix_map[voix]
    except KeyError:
        raise KeyError(f"voix {voix!r} sans LoRA ; voix servies : {sorted(voix_map)}")
def voix_servies(racine):
    voix_map = registre.lire(racine).get("voix", {})
    return {
        voix: {"poids": e.get("poids"), "etage": e.get("etage"),
               "gagnant": bool(e.get("validation", {}).get("decision", {}).get("gagnant", True))}
        for voix, e in voix_map.items()
    }


def charger_etat(poids):
    import torch
    contenu = torch.load(str(poids), map_location="cpu", weights_only=True)
    if isinstance(contenu, dict) and ADAPTATEURS_CLE in contenu:
        return contenu[ADAPTATEURS_CLE]
    return contenu
def _copie_cpu(v):
    cpu = getattr(v, "cpu", None)
    v = cpu() if callable(cpu) else v
    clone = getattr(v, "clone", None)
    return clone() if callable(clone) else v


def cle_base(cle_lora_a):
    return cle_lora_a.replace(".lora_A.weight", ".weight")


def fusionner_etat(etat_base, etat_lora, alpha, rang):
    echelle = alpha / rang
    fusion = dict(etat_base)
    for cle, a in etat_lora.items():
        if cle.endswith(".lora_A.weight"):
            b = etat_lora[cle.replace(".lora_A.", ".lora_B.")]
            fusion[cle_base(cle)] = etat_base[cle_base(cle)] + (b @ a) * echelle
        elif cle.startswith("llm_decoder."):
            fusion[cle] = a
    return fusion
class Commutateur:
    def __init__(self):
        self.cache = {}
        self.actif = None
        self._base_decodeur = None
        self._enveloppe = False
    def basculer(self, modele, voix, racine, cfg=None):
        from .modele import appliquer_lora
        entree = resoudre(racine, voix)
        if self.actif == voix:
            return "deja-actif"
        if not self._enveloppe:
            if cfg is None:
                cfg = self._cfg_defaut(entree)
            appliquer_lora(modele, cfg)
            self._figer_base(modele)
            self._enveloppe = True
        etat = self.cache.get(voix)
        if etat is None:
            etat = charger_etat(entree["poids"])
            self.cache[voix] = etat
            statut = "charge-disque"
        else:
            statut = "charge-cache"
        modele.llm.model.load_state_dict(etat, strict=False)
        self.actif = voix
        return statut
    def zero_shot(self, modele):
        if self._base_decodeur is None:
            return "deja-zero"
        modele.llm.model.load_state_dict(self._base_decodeur, strict=False)
        self._zero_lora(modele)
        self.actif = None
        return "zero-shot"
    def _figer_base(self, modele):
        etat = modele.llm.model.state_dict()
        self._base_decodeur = {k: _copie_cpu(v) for k, v in etat.items() if k.startswith("llm_decoder.")}
    def _zero_lora(self, modele):
        import torch
        with torch.no_grad():
            for m in modele.llm.model.modules():
                b = getattr(m, "lora_B", None)
                if b is not None and hasattr(b, "weight"):
                    b.weight.zero_()
    def _cfg_defaut(self, entree):
        from .presets import ConfigEntrainement
        conf = entree.get("config_dict") or {}
        return ConfigEntrainement(
            rang=conf.get("rang", 8), alpha=conf.get("alpha", 16),
            dropout=conf.get("dropout", 0.05),
            cibles=conf.get("cibles", ["q_proj", "v_proj"]))
    def fusionner(self, modele, voix, racine, sortie):
        import torch
        entree = resoudre(racine, voix)
        etat_lora = self.cache.get(voix) or charger_etat(entree["poids"])
        conf = entree.get("config_dict") or {}
        fusion = fusionner_etat(modele.llm.model.state_dict(), etat_lora,
                                conf.get("alpha", 16), conf.get("rang", 8))
        torch.save(fusion, str(sortie))
        return sortie
