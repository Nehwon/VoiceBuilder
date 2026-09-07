"""Tests pour engine/audio_extract.py (M13 — extraction audio, waveform, segment)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from engine import audio_extract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav(path: Path, duration: float = 5.0, sr: int = 24000,
              freq: float = 440.0) -> None:
    """Génère un fichier WAV test (onde sinusoïdale)."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    audio = 0.5 * np.sin(2 * np.pi * freq * t)
    sf.write(str(path), audio, sr)


def _make_video(path: Path) -> None:
    """Crée un fichier vidéo minimal via ffmpeg (skip si ffmpeg absent)."""
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=3",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3",
        "-shortest", "-c:v", "libx264", "-c:a", "aac",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        pytest.skip("ffmpeg non disponible ou ne fonctionne pas")


# ---------------------------------------------------------------------------
# Tests : extraire_audio
# ---------------------------------------------------------------------------

class TestExtraireAudio:
    def test_extrait_piste_audio_depuis_video(self, tmp_path):
        video = tmp_path / "test.mp4"
        _make_video(video)
        out_wav = tmp_path / "out.wav"
        result = audio_extract.extraire_audio(str(video), str(out_wav))
        assert out_wav.exists()
        assert result["sr"] == 24000
        assert result["duree"] > 2.5
        assert result["duree"] < 3.5

    def test_fichier_inexistant_retourne_erreur(self, tmp_path):
        out = tmp_path / "out.wav"
        with pytest.raises(RuntimeError, match="ffmpeg"):
            audio_extract.extraire_audio("/chemin/inexistant.mp4", str(out))

    def test_fichier_deja_wav_fonctionne(self, tmp_path):
        src = tmp_path / "source.wav"
        _make_wav(src, duration=2.0)
        out = tmp_path / "out.wav"
        result = audio_extract.extraire_audio(str(src), str(out))
        assert out.exists()
        assert result["duree"] > 1.5


# ---------------------------------------------------------------------------
# Tests : waveform_data
# ---------------------------------------------------------------------------

class TestWaveformData:
    def test_retourne_bonne_quantite_de_points(self, tmp_path):
        wav = tmp_path / "test.wav"
        _make_wav(wav, duration=3.0, sr=24000)
        peaks = audio_extract.waveform_data(str(wav), num_points=100)
        assert len(peaks) == 100
        for p in peaks:
            assert len(p) == 2

    def test_pic_dans_bornes(self, tmp_path):
        wav = tmp_path / "test.wav"
        _make_wav(wav, duration=1.0, sr=24000)
        peaks = audio_extract.waveform_data(str(wav), num_points=50)
        for vmin, vmax in peaks:
            assert -1.0 <= vmin <= 1.0
            assert -1.0 <= vmax <= 1.0
            assert vmin <= vmax

    def test_fichier_vide_retourne_zeros(self, tmp_path):
        wav = tmp_path / "empty.wav"
        sf.write(str(wav), np.array([], dtype=np.float32), 24000)
        peaks = audio_extract.waveform_data(str(wav), num_points=10)
        assert len(peaks) == 10
        for p in peaks:
            assert p == [0.0, 0.0]


# ---------------------------------------------------------------------------
# Tests : decouper_segment
# ---------------------------------------------------------------------------

class TestDecouperSegment:
    def test_decoupe_segment_valide(self, tmp_path):
        wav = tmp_path / "source.wav"
        _make_wav(wav, duration=5.0, sr=24000)
        result = audio_extract.decouper_segment(str(wav), 1.0, 3.0)
        assert result["duree"] == pytest.approx(2.0, abs=0.05)
        assert result["sr"] == 24000
        assert Path(result["wav"]).exists()

    def test_decoupe_depuis_debut(self, tmp_path):
        wav = tmp_path / "source.wav"
        _make_wav(wav, duration=5.0, sr=24000)
        result = audio_extract.decouper_segment(str(wav), 0.0, 2.0)
        assert result["duree"] == pytest.approx(2.0, abs=0.05)

    def test_segment_hors_bornes_erreur(self, tmp_path):
        wav = tmp_path / "source.wav"
        _make_wav(wav, duration=3.0, sr=24000)
        with pytest.raises(ValueError, match="hors bornes"):
            audio_extract.decouper_segment(str(wav), 10.0, 15.0)

    def test_segment_inversé_erreur(self, tmp_path):
        wav = tmp_path / "source.wav"
        _make_wav(wav, duration=3.0, sr=24000)
        with pytest.raises(ValueError):
            audio_extract.decouper_segment(str(wav), 3.0, 1.0)

    def test_sortie_personnalisee(self, tmp_path):
        wav = tmp_path / "source.wav"
        _make_wav(wav, duration=4.0, sr=24000)
        out = tmp_path / "custom_out.wav"
        result = audio_extract.decouper_segment(str(wav), 0.5, 2.5, out=str(out))
        assert Path(result["wav"]) == out
        assert out.exists()

    def test_segment_mono_depuis_stereo(self, tmp_path):
        sr = 24000
        duration = 3.0
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
        stereo = np.column_stack([0.5 * np.sin(2 * np.pi * 440 * t)] * 2)
        wav = tmp_path / "stereo.wav"
        sf.write(str(wav), stereo, sr)
        result = audio_extract.decouper_segment(str(wav), 0.5, 1.5)
        assert result["duree"] == pytest.approx(1.0, abs=0.05)


# ---------------------------------------------------------------------------
# Tests : _duree_wav
# ---------------------------------------------------------------------------

class TestDureeWav:
    def test_duree_exacte(self, tmp_path):
        wav = tmp_path / "test.wav"
        _make_wav(wav, duration=4.0, sr=24000)
        duree = audio_extract._duree_wav(str(wav))
        assert duree == pytest.approx(4.0, abs=0.05)
