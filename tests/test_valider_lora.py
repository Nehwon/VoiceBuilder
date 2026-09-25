"""M18.3 - Tests validation LoRA."""
import json
import tools.valider_lora as v
import numpy as np
import soundfile as sf


def _wav(path, seed):
    rng = np.random.RandomState(seed)
    sf.write(str(path), rng.uniform(-0.1, 0.1, 16000).astype(np.float32), 16000)
def test_reference_non_vide():
    assert len(v.TEXTE_REFERENCE_FR) > 50


def test_decider_exige_votes_et_seuil():
    ok, _ = v.decider(0.9, 2, 0, 2, 0.85, 2)
    assert ok is True
    assert v.decider(0.5, 2, 0, 2, 0.85, 2)[0] is False
    assert v.decider(0.9, 1, 1, 2, 0.85, 2)[0] is False
    assert v.decider(0.9, 2, 0, 1, 0.85, 2)[0] is False
def test_aveugle_mapping_inversible(tmp_path):
    z = tmp_path / "z.wav"
    l = tmp_path / "l.wav"
    _wav(z, 1)
    _wav(l, 2)
    out = tmp_path / "out"
    mapping = v.preparer_aveugle(str(z), str(l), out, seed=7)
    assert set(mapping.values()) == {"zero", "lora"}
    assert (out / "A.wav").exists() and (out / "B.wav").exists()


def test_compter_votes_nuls():
    m = {"A": "zero", "B": "lora"}
    c = v.compter_votes({"a1": "B", "a2": "X"}, m)
    assert (c["lora"], c["nuls"]) == (1, 1)
def test_main_gagnant_enregistre(tmp_path, monkeypatch):
    z = tmp_path / "z.wav"
    l = tmp_path / "l.wav"
    _wav(z, 1)
    _wav(l, 2)
    votes = tmp_path / "votes.json"
    import random as _r; _c=["zero","lora"]; _r.Random(7).shuffle(_c); _l="A" if _c[0]=="lora" else "B"; votes.write_text(json.dumps({"a1": _l, "a2": _l}))
    monkeypatch.setattr(v.verifier, "coverage", lambda t, a, s: 0.9)
    out = tmp_path / "out"
    out = tmp_path / "out"
    rc = v.main(["--voix", "vx", "--lora", "lora-dir", "--audio-zero", str(z), "--audio-lora", str(l), "--out", str(out), "--votes", str(votes), "--seed", "7", "--dataset-racine", str(tmp_path / "ds"), "--enregistrer"])
    assert rc == 0
    rap = json.loads((out / "validation.json").read_text())
    assert rap["decision"]["gagnant"] is True
    assert (tmp_path / "ds" / "lora_registry.json").exists()
def test_main_perdant_sans_registre(tmp_path, monkeypatch):
    z = tmp_path / "z.wav"
    l = tmp_path / "l.wav"
    _wav(z, 1)
    _wav(l, 2)
    monkeypatch.setattr(v.verifier, "coverage", lambda t, a, s: 0.5)
    out = tmp_path / "out"
    out = tmp_path / "out2"
    rc = v.main(["--voix", "vx", "--lora", "lora-dir", "--audio-zero", str(z), "--audio-lora", str(l), "--out", str(out), "--dataset-racine", str(tmp_path / "ds"), "--enregistrer"])
    assert rc == 0
    rap = json.loads((out / "validation.json").read_text())
    assert rap["decision"]["gagnant"] is False
    assert not (tmp_path / "ds" / "lora_registry.json").exists()
