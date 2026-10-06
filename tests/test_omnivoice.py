"""Tests M19.1 — moteur OmniVoice : voix.txt, engine (mock), routage multi."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import config, multi, omnivoice_engine, voix


# ═══════════════════════════════════════════════════════════════════════════
# voix.txt — colonne moteur
# ═══════════════════════════════════════════════════════════════════════════

def _projet_voix(tmp_path: Path, lignes: str):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....")
    (tmp_path / "a.txt").write_text("bonjour", encoding="utf-8")
    vf = tmp_path / "voix.txt"
    vf.write_text(lignes, encoding="utf-8")
    return vf


class TestColonneMoteur:
    def test_defaut_cosyvoice(self, tmp_path):
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt\n")
        v = voix.load_voix(vf, voix_dir=tmp_path).get("A")
        assert v.moteur == "cosyvoice" == config.MOTEUR_DEFAUT

    def test_omnivoice_explicite(self, tmp_path):
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt, , , , omnivoice\n")
        v = voix.load_voix(vf, voix_dir=tmp_path).get("A")
        assert v.moteur == "omnivoice"

    def test_casse_insensible(self, tmp_path):
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt, , , , OmniVoice\n")
        v = voix.load_voix(vf, voix_dir=tmp_path).get("A")
        assert v.moteur == "omnivoice"

    def test_moteur_inconnu_rejete(self, tmp_path):
        import pytest
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt, , , , xtts\n")
        with pytest.raises(ValueError, match="Moteur inconnu"):
            voix.load_voix(vf, voix_dir=tmp_path)


class TestEcrireVoixTxt:
    def test_sans_moteur_pas_de_suffixe(self, tmp_path):
        out = voix.ecrire_voix_txt([("A", "a.wav", "a.txt")],
                                   out=tmp_path / "voix.txt")
        assert out.read_text(encoding="utf-8") == "[A], a.wav, a.txt\n"

    def test_omnivoice_suffixe_7e_colonne(self, tmp_path):
        out = voix.ecrire_voix_txt([("A", "a.wav", "a.txt", "omnivoice")],
                                   out=tmp_path / "voix.txt")
        ligne = out.read_text(encoding="utf-8").strip()
        assert ligne.endswith(", omnivoice")
        # Round-trip : la ligne relue donne moteur omnivoice.
        (tmp_path / "a.wav").write_bytes(b"RIFF....")
        (tmp_path / "a.txt").write_text("bonjour", encoding="utf-8")
        v = voix.load_voix(out, voix_dir=tmp_path).get("A")
        assert v.moteur == "omnivoice"

    def test_cosyvoice_explicite_pas_de_suffixe(self, tmp_path):
        out = voix.ecrire_voix_txt([("A", "a.wav", "a.txt", "cosyvoice")],
                                   out=tmp_path / "voix.txt")
        assert out.read_text(encoding="utf-8") == "[A], a.wav, a.txt\n"


# ═══════════════════════════════════════════════════════════════════════════
# Moteur par défaut (sélecteur Configuration, M19.1)
# ═══════════════════════════════════════════════════════════════════════════

class TestMoteurDefaut:
    def test_defaut_cosyvoice(self):
        assert config.MOTEUR_DEFAUT in config.MOTEURS

    def test_bascule_et_retour(self):
        avant = config.MOTEUR_DEFAUT
        try:
            config.set_moteur_defaut("omnivoice")
            assert config.MOTEUR_DEFAUT == "omnivoice"
        finally:
            config.set_moteur_defaut(avant)

    def test_inconnu_rejete(self):
        import pytest
        with pytest.raises(ValueError, match="Moteur inconnu"):
            config.set_moteur_defaut("xtts")

    def test_voix_sans_colonne_suit_le_defaut(self, tmp_path):
        avant = config.MOTEUR_DEFAUT
        try:
            config.set_moteur_defaut("omnivoice")
            vf = _projet_voix(tmp_path, "[A], a.wav, a.txt\n")
            v = voix.load_voix(vf, voix_dir=tmp_path).get("A")
            assert v.moteur == "omnivoice"
        finally:
            config.set_moteur_defaut(avant)


class TestDefinirMoteur:
    def test_ajout_colonne(self, tmp_path):
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt\n")
        assert voix.definir_moteur(vf, "A", "omnivoice") == "omnivoice"
        assert voix.load_voix(vf, voix_dir=tmp_path).get("A").moteur == "omnivoice"
        assert vf.read_text(encoding="utf-8").strip() == (
            "[A], a.wav, a.txt, , , , omnivoice")

    def test_retrait_colonne_defaut(self, tmp_path):
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt, , , , omnivoice\n")
        assert voix.definir_moteur(vf, "A", "defaut") == ""
        assert vf.read_text(encoding="utf-8").strip() == "[A], a.wav, a.txt"

    def test_preserve_autres_colonnes_et_commentaires(self, tmp_path):
        vf = _projet_voix(
            tmp_path,
            "# commentaire\n[A], a.wav, a.txt, 0.3, 1.0\n[B], a.wav, a.txt\n")
        voix.definir_moteur(vf, "A", "omnivoice")
        lignes = vf.read_text(encoding="utf-8").splitlines()
        assert lignes[0] == "# commentaire"
        assert lignes[1] == "[A], a.wav, a.txt, 0.3, 1.0, , omnivoice"
        assert lignes[2] == "[B], a.wav, a.txt"

    def test_voix_inconnue_et_moteur_invalide(self, tmp_path):
        import pytest
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt\n")
        with pytest.raises(KeyError):
            voix.definir_moteur(vf, "Z", "omnivoice")
        with pytest.raises(ValueError, match="Moteur inconnu"):
            voix.definir_moteur(vf, "A", "xtts")

# ═══════════════════════════════════════════════════════════════════════════
# omnivoice_engine.synthesize (modèle mock)
# ═══════════════════════════════════════════════════════════════════════════

class _FauxModele:
    """Imite OmniVoice.generate : capture les kwargs, renvoie 1 s à 24 kHz."""
    def __init__(self):
        self.appels = []
    def generate(self, **kwargs):
        self.appels.append(kwargs)
        return [np.zeros(24000, dtype=np.float32)]


class TestSynthesize:
    def test_normalisation_et_prompt_brut(self):
        faux = _FauxModele()
        out = omnivoice_engine.synthesize(
            "J'ai 3 chats.", "ref.wav", "référence.", model=faux)
        assert out.shape == (24000,)
        kw = faux.appels[0]
        assert kw["ref_text"] == "référence."  # brut, sans préfixe système
        assert "3" not in kw["text"] and "trois" in kw["text"]

    def test_marqueurs_langue_retires(self):
        faux = _FauxModele()
        omnivoice_engine.synthesize("[en]Hello[/en] monde.", "r.wav", "ref.",
                                   model=faux)
        assert "[en]" not in faux.appels[0]["text"]

    def test_resample_vers_sr_montage(self):
        faux = _FauxModele()
        out = omnivoice_engine.synthesize("Bonjour.", "r.wav", "ref.",
                                         model=faux, out_sr=22050)
        assert out.shape == (22050,)


# ═══════════════════════════════════════════════════════════════════════════
# Mode worker HTTP (M19.1-bis)
# ═══════════════════════════════════════════════════════════════════════════

class TestWorker:
    def test_load_worker_sans_import_local(self, monkeypatch):
        import engine.omnivoice_engine as oe
        monkeypatch.setattr(oe, "_direct_ok", False)
        monkeypatch.setattr(oe, "_model", None)
        model, sr = oe.load(worker_url="http://test:8100")
        assert model == {"worker_url": "http://test:8100"} and sr == 24000

    def test_synthesize_via_worker(self, monkeypatch):
        import io
        import engine.omnivoice_engine as oe
        wav = io.BytesIO()
        import soundfile as sf
        sf.write(wav, np.zeros(4800, dtype=np.float32), 24000, format="WAV")
        corps = wav.getvalue()

        class _Rep:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return corps

        vus = {}

        def _faux_open(req, timeout=None):
            vus["url"] = req.full_url
            vus["payload"] = req.data.decode()
            return _Rep()

        monkeypatch.setattr("urllib.request.urlopen", _faux_open)
        out = oe.synthesize("Bonjour.", "ref.wav", "reference.",
                            model={"worker_url": "http://test:8100"},
                            out_sr=24000)
        assert out.shape == (4800,)
        assert vus["url"] == "http://test:8100/synthesize"
        assert "Bonjour" in vus["payload"]

    def test_worker_injoignable_erreur_claire(self, monkeypatch):
        import engine.omnivoice_engine as oe
        import pytest

        def _ko(req, timeout=None):
            raise ConnectionRefusedError("refuse")
        monkeypatch.setattr("urllib.request.urlopen", _ko)
        with pytest.raises(RuntimeError, match="injoignable"):
            oe.synthesize("Bonjour.", "ref.wav", "reference.",
                          model={"worker_url": "http://test:8100"})

# ═══════════════════════════════════════════════════════════════════════════
# Routage multi._synthesize_for
# ═══════════════════════════════════════════════════════════════════════════

def _voix(nom: str, moteur: str) -> voix.Voice:
    return voix.Voice(name=nom, wav=Path(f"/tmp/{nom}.wav"),
                      txt=Path(f"/tmp/{nom}.txt"), moteur=moteur,
                      prompt_text="reference")


class TestRoutage:
    def test_omni_appelle_omni_avec_prompt_brut(self):
        with patch("engine.omnivoice_engine.synthesize",
                   return_value=np.zeros(24000, dtype=np.float32)) as m_omni, \
             patch("engine.cosyvoice_engine.synthesize") as m_cosy, \
             patch("engine.adaptive.synthesize_verified",
                   side_effect=lambda t, w, p, synth, sr, **kw: synth(t)):
            multi._synthesize_for("Texte.", {"omnivoice": (object(), 24000)},
                                  22050, _voix("A", "omnivoice"), 600, 1.0,
                                  False)
        assert m_omni.called and not m_cosy.called
        _, kw = m_omni.call_args
        assert kw.get("out_sr") == 22050

    def test_cosy_appelle_cosy_avec_system_prompt(self):
        with patch("engine.omnivoice_engine.synthesize") as m_omni, \
             patch("engine.cosyvoice_engine.synthesize",
                   return_value=np.zeros(22050, dtype=np.float32)) as m_cosy, \
             patch("engine.adaptive.synthesize_verified",
                   side_effect=lambda t, w, p, synth, sr, **kw: synth(t)):
            multi._synthesize_for("Texte.", {"cosyvoice": (object(), 22050)},
                                  22050, _voix("A", "cosyvoice"), 600, 1.0,
                                  False)
        assert m_cosy.called and not m_omni.called
        args, _ = m_cosy.call_args
        assert args[2].startswith(config.COSYVOICE3_SYSTEM_PROMPT)
