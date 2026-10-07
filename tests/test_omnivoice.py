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
    def test_defaut_omnivoice(self, tmp_path):
        vf = _projet_voix(tmp_path, "[A], a.wav, a.txt\n")
        v = voix.load_voix(vf, voix_dir=tmp_path).get("A")
        assert v.moteur == "omnivoice" == config.MOTEUR_DEFAUT

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

    def test_omnivoice_defaut_pas_de_suffixe(self, tmp_path):
        # Branche omni : omnivoice = défaut -> pas de suffixe.
        out = voix.ecrire_voix_txt([("A", "a.wav", "a.txt", "omnivoice")],
                                   out=tmp_path / "voix.txt")
        ligne = out.read_text(encoding="utf-8").strip()
        assert ligne == "[A], a.wav, a.txt"
        # Round-trip : la ligne relue donne moteur omnivoice.
        (tmp_path / "a.wav").write_bytes(b"RIFF....")
        (tmp_path / "a.txt").write_text("bonjour", encoding="utf-8")
        v = voix.load_voix(out, voix_dir=tmp_path).get("A")
        assert v.moteur == "omnivoice"

    def test_cosyvoice_explicite_suffixe_inerte(self, tmp_path):
        # Branche omni : cosyvoice != défaut -> suffixe écrit mais sans effet.
        out = voix.ecrire_voix_txt([("A", "a.wav", "a.txt", "cosyvoice")],
                                   out=tmp_path / "voix.txt")
        assert out.read_text(encoding="utf-8").strip().endswith(", cosyvoice")


# ═══════════════════════════════════════════════════════════════════════════
# Moteur par défaut (sélecteur Configuration, M19.1)
# ═══════════════════════════════════════════════════════════════════════════

class TestMoteurDefaut:
    def test_defaut_omnivoice(self):
        assert config.MOTEUR_DEFAUT == "omnivoice" == config.MOTEURS[0]

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
# ═══════════════════════════════════════════════════════════════════════════
# Routage multi._synthesize_for
# ═══════════════════════════════════════════════════════════════════════════

def _voix(nom: str, moteur: str) -> voix.Voice:
    return voix.Voice(name=nom, wav=Path(f"/tmp/{nom}.wav"),
                      txt=Path(f"/tmp/{nom}.txt"), moteur=moteur,
                      prompt_text="reference")


class TestRoutage:
    def test_omni_force_meme_voix_cosy(self):
        # Branche omni : voice.moteur ignoré, toujours OmniVoice direct.
        with patch("engine.omnivoice_engine.synthesize",
                   return_value=np.zeros(24000, dtype=np.float32)) as m_omni, \
             patch("engine.adaptive.synthesize_verified",
                   side_effect=lambda t, w, p, synth, sr, **kw: synth(t)):
            multi._synthesize_for("Texte.", {}, 24000,
                                  _voix("A", "cosyvoice"), 600, 1.0, False)
        assert m_omni.called
        _, kw = m_omni.call_args
        assert kw.get("out_sr") == 24000
