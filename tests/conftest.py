"""Fixtures partagées pour les tests VoiceBuilder."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf


# ---------------------------------------------------------------------------
# Fixture : répertoire temporaire nettoyé après chaque test
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path):
    """Crée un mini-projet temporaire avec voix + texte tagué."""
    voices_dir = tmp_path / "voix"
    voices_dir.mkdir()
    textes_dir = tmp_path / "texte"
    textes_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return {
        "root": tmp_path,
        "voices_dir": voices_dir,
        "textes_dir": textes_dir,
        "output_dir": output_dir,
    }


# ---------------------------------------------------------------------------
# Fixture : deux voix temporaires (fichiers wav + txt)
# ---------------------------------------------------------------------------

def _make_voice_wav(path: Path, duration: float = 2.0, sr: int = 22050):
    """Génère un fichier WAV minuscule (onde sinusoïdale)."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    audio = 0.3 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(path), audio, sr)


@pytest.fixture()
def two_voices(tmp_project):
    """Crée 2 voix (Narrateur, Personnage) et retourne le chemin voix.txt."""
    vd = tmp_project["voices_dir"]
    for name, freq in [("Narrateur", 440), ("Personnage", 660)]:
        wav = vd / f"{name.lower()}.wav"
        txt = vd / f"{name.lower()}.txt"
        _make_voice_wav(wav, duration=2.0)
        txt.write_text(f"Ceci est la transcription de {name}.\n", encoding="utf-8")
    voix_txt = vd / "voix.txt"
    voix_txt.write_text(
        "[Narrateur], narrateur.wav, narrateur.txt\n"
        "[Personnage], personnage.wav, personnage.txt\n",
        encoding="utf-8",
    )
    return voix_txt


# ---------------------------------------------------------------------------
# Fixture : texte tagué minimal (2 personnages, 1 phrase chacun)
# ---------------------------------------------------------------------------

MINIMAL_TAGGED_TEXT = """\
[Narrateur]: Il était une fois, dans un pays lointain.
[Personnage]: Bonjour, comment allez-vous ?
"""


@pytest.fixture()
def minimal_text_file(tmp_project):
    """Écrit le texte tagué minimal et retourne le chemin."""
    p = tmp_project["textes_dir"] / "test_minimal.md"
    p.write_text(MINIMAL_TAGGED_TEXT, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixture : mock du moteur CosyVoice (pas de GPU requis)
# ---------------------------------------------------------------------------

_SAMPLE_RATE = 22050


def _fake_synthesize(text: str, prompt_wav: str, prompt_text: str,
                     model=None, sample_rate=None, speed=1.0) -> np.ndarray:
    """Retourne une onde sinusoïdale factice dont la durée dépend de la longueur du texte."""
    sr = sample_rate or _SAMPLE_RATE
    duration = max(0.5, len(text) * 0.05)  # ~50 ms par caractère
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    return 0.3 * np.sin(2 * np.pi * 440 * t)


def _fake_save(audio: np.ndarray, sample_rate: int, path: str) -> None:
    """Écrit le fichier WAV réellement (pour vérification dans les tests)."""
    sf.write(path, audio, sample_rate)


@pytest.fixture()
def mock_cosyvoice():
    """Mock le moteur CosyVoice : load + synthesize (save écrit pour de vrai)."""
    mock_model = MagicMock(name="CosyVoiceModel")

    with patch("engine.cosyvoice_engine.load", return_value=(mock_model, _SAMPLE_RATE)) as m_load, \
         patch("engine.cosyvoice_engine.synthesize", side_effect=_fake_synthesize) as m_synth, \
         patch("engine.cosyvoice_engine.save", side_effect=_fake_save) as m_save:
        yield {
            "load": m_load,
            "synthesize": m_synth,
            "save": m_save,
            "model": mock_model,
            "sample_rate": _SAMPLE_RATE,
        }


# ---------------------------------------------------------------------------
# Fixture : mock de la vérification Whisper (toujours passe)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_verify():
    """Mock verifier.verify_text → True (pas de GPU requis)."""
    with patch("engine.verifier.verify_text", return_value=True) as m:
        yield m
