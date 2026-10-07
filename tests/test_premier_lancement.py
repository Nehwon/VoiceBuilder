"""Tests premier lancement : progression + clé HF (mockés, sans GPU)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import huggingface_hub

from engine import config
from engine import omnivoice_engine as oe


def test_tqdm_progression_bornes():
    g = oe._TqdmProgression(total=13, desc="Fetching 13 files")
    g.update(10)
    st = oe.progression_telechargement()
    assert st["pct"] == 77 and st["etape"] == "Fichiers : 10/13"
    g.close()
    f = oe._TqdmProgression(total=200, desc="poids/modele.safetensors")
    f.update(50)
    st = oe.progression_telechargement()
    assert st["pct_fichier"] == 25 and st["fichier"] == "modele.safetensors"
    f.update(300)  # dépasse : borné à 100
    assert oe.progression_telechargement()["pct_fichier"] == 100
    f.close()
    oe._maj_progression(0, en_cours=False)


def test_hf_token_set_et_masque():
    import os
    config.set_hf_token("  hf_test123  ")
    assert config.hf_token() == "hf_test123"
    assert os.environ.get("HF_TOKEN") == "hf_test123"
    config.set_hf_token(None)
    assert config.hf_token() is None
    assert "HF_TOKEN" not in os.environ


def test_modele_en_cache_mock(monkeypatch):
    def absent(**kw):
        raise RuntimeError("absent")
    monkeypatch.setattr(huggingface_hub, "snapshot_download",
                        lambda **kw: "/tmp/x" if kw.get("local_files_only") else absent(**kw))
    assert oe.modele_en_cache() is True
    monkeypatch.setattr(huggingface_hub, "snapshot_download", absent)
    assert oe.modele_en_cache() is False
