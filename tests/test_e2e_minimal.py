"""M11 — Test bout en bout minimal.

Couvre le scénario : une phrase par balise, une voix par balise,
génération de la voix et ouverture de l'espace de montage.

Le moteur CosyVoice (GPU + modèle ~11 Go) est mocké ; seules les couches
pures (tagging, adaptive, voix, multi orchestration) tournent pour de vrai.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from engine import config
from engine.tagging import parse_texte, regrouper, TaggingError
from engine.adaptive import build_blocks, split_sentences
from engine.voix import load_voix, Voices
from engine import multi


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1 — Parsing pur (pas de mock)
# ═══════════════════════════════════════════════════════════════════════════

class TestParsing:
    """Vérifie le parsing d'un texte tagué + regroupement."""

    VOIX_NAMES = ["Narrateur", "Personnage"]

    def test_parse_minimal(self):
        text = (
            "[Narrateur]: Il était une fois.\n"
            "[Personnage]: Bonjour !\n"
        )
        segs = parse_texte(text, self.VOIX_NAMES)
        assert len(segs) == 2
        assert segs[0] == ("Narrateur", "Il était une fois.")
        assert segs[1] == ("Personnage", "Bonjour !")

    def test_regroupe_consecutifs(self):
        text = (
            "[Narrateur]: Phrase une.\n"
            "[Narrateur]: Phrase deux.\n"
            "[Personnage]: Autre chose.\n"
        )
        segs = parse_texte(text, self.VOIX_NAMES)
        blocs = regrouper(segs)
        assert len(blocs) == 2
        assert blocs[0][0] == "Narrateur"
        assert "Phrase une." in blocs[0][1]
        assert "Phrase deux." in blocs[1][1] or "Phrase deux." in blocs[0][1]

    def test_lignes_nues_attribuees(self):
        text = (
            "[Narrateur]: Début.\n"
            "Suite du narrateur.\n"
            "[Personnage]: Toi.\n"
        )
        segs = parse_texte(text, self.VOIX_NAMES)
        assert len(segs) == 3
        assert segs[1] == ("Narrateur", "Suite du narrateur.")

    def test_tag_inline_conserves(self):
        text = (
            "[Narrateur]: Bonjour [sigh] monde.\n"
        )
        segs = parse_texte(text, self.VOIX_NAMES)
        assert len(segs) == 1
        assert "[sigh]" in segs[0][1]

    def test_stop_interrompt(self):
        text = (
            "[Narrateur]: Avant.\n"
            "[stop]\n"
            "[Personnage]: Après (ignoré).\n"
        )
        segs = parse_texte(text, self.VOIX_NAMES)
        assert len(segs) == 1

    def test_texte_vide_erreur(self):
        with pytest.raises(TaggingError, match="vide"):
            parse_texte("", self.VOIX_NAMES)

    def test_personnage_inconnu_traite_comme_tag_non_verbal(self):
        """Un nom inconnu est traité comme tag non-verbal ([sigh]) — pas d'erreur parsing."""
        text = "[Inconnu]: Salut.\n"
        # parse_texte le traite comme tag inline, pas comme personnage
        # Si c'est la première ligne et aucun locuteur courant → TaggingError
        with pytest.raises(TaggingError):
            parse_texte(text, self.VOIX_NAMES)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1 — Découpage adaptatif
# ═══════════════════════════════════════════════════════════════════════════

class TestAdaptive:
    def test_split_sentences(self):
        sents = split_sentences("Bonjour. Comment ? Ça va ! Oui.")
        assert len(sents) == 4

    def test_build_blocks_short(self):
        blocks = build_blocks("Phrase courte.", max_chars=600)
        assert len(blocks) == 1

    def test_build_blocks_long(self):
        long = "Ceci est une phrase. " * 50  # ~1050 chars
        blocks = build_blocks(long, max_chars=200)
        assert len(blocks) >= 2
        for b in blocks:
            assert len(b) <= 220  # marge pour la dernière phrase


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1 — Chargement de voix (fixtures temporaires)
# ═══════════════════════════════════════════════════════════════════════════

class TestVoix:
    def test_load_two_voices(self, two_voices):
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        assert len(list(voices)) == 2
        assert "Narrateur" in voices
        assert "Personnage" in voices

    def test_voice_has_wav_and_txt(self, two_voices):
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        v = voices.get("Narrateur")
        assert v.wav.exists()
        assert v.txt.exists()
        assert len(v.prompt_text) > 0

    def test_voix_manquante_erreur(self, two_voices):
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        assert "Inexistant" not in voices


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — Pipeline complet multi.generate() avec mocks
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiGenerate:
    """Test bout en bout : texte tagué → parsing → génération → sortie WAV."""

    def test_generate_minimal(self, two_voices, minimal_text_file,
                               mock_cosyvoice, mock_verify, tmp_project):
        """Scénario M11 : 1 phrase/balise, 2 voix, sortie WAV valide."""
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        out = str(tmp_project["output_dir"] / "montage.wav")

        result = multi.generate(
            str(minimal_text_file),
            voices,
            out=out,
            verbose=False,
        )

        # 1) Le résultat contient les champs attendus
        assert "audio" in result
        assert "sample_rate" in result
        assert "duration" in result
        assert "blocs" in result
        assert result["out"] == out

        # 2) L'audio est un numpy array valide
        assert isinstance(result["audio"], np.ndarray)
        assert result["audio"].dtype == np.float32
        assert result["duration"] > 0

        # 3) Deux blocs (un par personnage)
        assert len(result["blocs"]) == 2
        pers = {b["personnage"] for b in result["blocs"]}
        assert pers == {"Narrateur", "Personnage"}

        # 4) Chaque bloc a les métadonnées attendues
        for b in result["blocs"]:
            assert "voix" in b
            assert "texte" in b
            assert "chars" in b
            assert "duree" in b
            assert b["chars"] > 0
            assert b["duree"] > 0

        # 5) Le fichier WAV existe et est lisible
        assert Path(out).exists()
        data, sr = sf.read(out)
        assert sr == result["sample_rate"]
        assert len(data) > 0

    def test_generate_with_progress_callback(self, two_voices, minimal_text_file,
                                              mock_cosyvoice, mock_verify, tmp_project):
        """Vérifie que le callback progress est appelé."""
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        out = str(tmp_project["output_dir"] / "montage.wav")
        calls = []

        result = multi.generate(
            str(minimal_text_file),
            voices,
            out=out,
            verbose=False,
            progress=lambda info: calls.append(info),
        )

        # Au moins 2 appels bloc + 1 appel final
        assert len(calls) >= 3
        # Le dernier appel contient la durée totale
        assert "duree" in calls[-1]
        assert "blocs" in calls[-1]

    def test_generate_sans_sortie(self, two_voices, minimal_text_file,
                                   mock_cosyvoice, mock_verify):
        """Pas de chemin de sortie → pas de fichier écrit."""
        voices = load_voix(two_voices, voix_dir=two_voices.parent)

        result = multi.generate(
            str(minimal_text_file),
            voices,
            out=None,
            verbose=False,
        )

        assert result["out"] is None
        assert result["duration"] > 0

    def test_generate_personnages_mapping(self, two_voices, mock_cosyvoice,
                                           mock_verify, tmp_project):
        """Mapping personnages → voix (M9) : le personnage « Héros » utilise la voix « Narrateur »."""
        vd = two_voices.parent
        # Texte avec un personnage qui n'est pas un nom de voix
        txt = tmp_project["textes_dir"] / "mapping.md"
        txt.write_text("[Héros]: Je suis le héros.\n", encoding="utf-8")
        voices = load_voix(two_voices, voix_dir=vd)
        out = str(tmp_project["output_dir"] / "montage.wav")

        result = multi.generate(
            str(txt),
            voices,
            personnages={"Héros": "Narrateur"},
            out=out,
            verbose=False,
        )

        assert len(result["blocs"]) == 1
        assert result["blocs"][0]["personnage"] == "Héros"
        assert result["blocs"][0]["voix"] == "Narrateur"

    def test_generate_voix_introuvable_erreur(self, two_voices,
                                               mock_cosyvoice, mock_verify,
                                               tmp_project):
        """Personnage mappé vers une voix inexistante → ValueError."""
        txt = tmp_project["textes_dir"] / "test.md"
        txt.write_text(
            "[Narrateur]: Salut.\n"
            "[Personnage]: Hello.\n",
            encoding="utf-8",
        )
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        # On mappe les deux personnages mais vers une voix « Fantôme » inexistante
        with pytest.raises(ValueError, match="introuvable"):
            multi.generate(
                str(txt),
                voices,
                personnages={"Narrateur": "Fantôme", "Personnage": "Personnage"},
                verbose=False,
            )

    def test_generate_bloc_dir(self, two_voices, minimal_text_file,
                                mock_cosyvoice, mock_verify, tmp_project):
        """block_dir → chaque bloc est sauvegardé individuellement."""
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        block_dir = str(tmp_project["output_dir"] / "blocs")
        out = str(tmp_project["output_dir"] / "montage.wav")

        result = multi.generate(
            str(minimal_text_file),
            voices,
            out=out,
            block_dir=block_dir,
            verbose=False,
        )

        # Chaque bloc a un chemin wav
        for b in result["blocs"]:
            assert "wav" in b
            assert Path(b["wav"]).exists()

    def test_generate_no_verify(self, two_voices, minimal_text_file,
                                 mock_cosyvoice, tmp_project):
        """verify=False désactive la vérification Whisper."""
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        out = str(tmp_project["output_dir"] / "montage.wav")

        result = multi.generate(
            str(minimal_text_file),
            voices,
            out=out,
            verify=False,
            verbose=False,
        )

        assert result["duration"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2 — synth_bloc (régénération d'un bloc)
# ═══════════════════════════════════════════════════════════════════════════

class TestSynthBloc:
    def test_synth_bloc_single(self, two_voices, mock_cosyvoice, mock_verify):
        voices = load_voix(two_voices, voix_dir=two_voices.parent)
        voice = voices.get("Narrateur")

        audio = multi.synth_bloc(
            voice,
            "Bonjour le monde.",
            mock_cosyvoice["model"],
            mock_cosyvoice["sample_rate"],
            verify=False,
        )

        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32
        assert len(audio) > 0
