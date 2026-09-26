"""M18.4 - Tests switch LoRA par personnage."""
import numpy as np
import pytest
from engine.lora import chargeur, registre
class FauxB:
    def __init__(self):
        self.data = np.ones((4, 2), dtype=np.float32)
        self.weight = self
        self.zeroed = False
    def zero_(self):
        self.zeroed = True
        self.data = np.zeros_like(self.data)


class FauxModule:
    def __init__(self):
        self.lora_B = FauxB()
        self.charges = []
        self._etat = {"llm_decoder.w": np.ones(3, dtype=np.float32)}
    def load_state_dict(self, etat, strict=False):
        self.charges.append(dict(etat))
    def state_dict(self):
        return dict(self._etat)
    def modules(self):
        return [self]
class FauxModele:
    def __init__(self):
        self.llm = type("L", (), {"model": FauxModule()})()


def _dataset(tmp_path):
    racine = tmp_path / "ds"
    racine.mkdir(parents=True, exist_ok=True)
    for voix in ("alice", "bob"):
        registre.enregistrer(str(racine), voix, {"poids": f"/lora/{voix}.pt"})
    return str(racine)
def test_resoudre_erreur_liste_voix(tmp_path):
    racine = _dataset(tmp_path)
    with pytest.raises(KeyError, match="alice"):
        chargeur.resoudre(racine, "zoe")


def test_voix_servies(tmp_path):
    servi = chargeur.voix_servies(_dataset(tmp_path))
    assert set(servi) == {"alice", "bob"}
    assert servi["alice"]["poids"] == "/lora/alice.pt"
def test_basculer_cache(tmp_path, monkeypatch):
    racine = _dataset(tmp_path)
    appels = {"wrap": 0, "disque": 0}
    import engine.lora.modele as modele
    monkeypatch.setattr(modele, "appliquer_lora", lambda m, c: appels.__setitem__("wrap", 1))
    monkeypatch.setattr(chargeur, "charger_etat", lambda p: (appels.__setitem__("disque", appels["disque"] + 1), {"llm_decoder.w": np.zeros(3)})[1])
    com = chargeur.Commutateur()
    m = FauxModele()
    assert com.basculer(m, "alice", racine) == "charge-disque"
    assert com.basculer(m, "alice", racine) == "deja-actif"
    assert com.basculer(m, "bob", racine) == "charge-disque"
    assert com.basculer(m, "alice", racine) == "charge-cache"
    assert appels == {"wrap": 1, "disque": 2}
    assert com.actif == "alice"
def test_zero_shot_restaure(tmp_path, monkeypatch):
    racine = _dataset(tmp_path)
    import engine.lora.modele as modele
    monkeypatch.setattr(modele, "appliquer_lora", lambda m, c: None)
    monkeypatch.setattr(chargeur, "charger_etat", lambda p: {"llm_decoder.w": np.zeros(3)})
    com = chargeur.Commutateur()
    m = FauxModele()
    assert com.zero_shot(m) == "deja-zero"
    com.basculer(m, "alice", racine)
    assert com.zero_shot(m) == "zero-shot"
    assert com.actif is None
    assert m.llm.model.lora_B.zeroed is True


def test_fusionner_etat():
    base = {"blk.q_proj.weight": np.zeros((4, 3), dtype=np.float32)}
    lora = {"blk.q_proj.lora_A.weight": np.ones((2, 3), dtype=np.float32),
            "blk.q_proj.lora_B.weight": np.ones((4, 2), dtype=np.float32),
            "llm_decoder.w": np.full(3, 7, dtype=np.float32)}
    f = chargeur.fusionner_etat(base, lora, 16, 8)
    assert f["blk.q_proj.weight"].tolist() == [[4.0] * 3] * 4
    assert f["llm_decoder.w"].tolist() == [7.0] * 3
