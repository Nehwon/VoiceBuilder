"""Le listage des voix suit le dossier des voix (volume), pas l'image.

Régression : ``voix.txt`` vivait dans l'image (``/app/voix/voix.txt``), donc
toute voix ajoutée par l'interface disparaissait à la recréation du conteneur
et la liste revenait à celle gravée dans l'image — il fallait « Réglages →
Appliquer le dossier » pour retrouver un état cohérent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import config, voix


def _isoler(monkeypatch) -> None:
    """Restaure l'état global de ``config`` à la fin du test."""
    for nom in ("VOIX_FILE", "VOIX_AUDIO_DIR", "VOIX_SEARCH_DIRS"):
        monkeypatch.setattr(config, nom, getattr(config, nom))


def test_listage_migre_vers_le_dossier_des_voix(tmp_path, monkeypatch):
    _isoler(monkeypatch)
    image = tmp_path / "image"
    image.mkdir()
    (image / "voix.txt").write_text("[A], a.wav, a.txt\n", encoding="utf-8")
    audio = tmp_path / "data_voice"
    audio.mkdir()
    config.VOIX_FILE = image / "voix.txt"
    config.VOIX_AUDIO_DIR = image

    config.set_audio_dir(audio)

    assert config.VOIX_FILE == audio / "voix.txt"
    assert config.VOIX_FILE.read_text(encoding="utf-8") == "[A], a.wav, a.txt\n"


def test_listage_du_volume_prioritaire_apres_migration(tmp_path, monkeypatch):
    """Une fois migré, le fichier du volume n'est plus écrasé par celui de l'image."""
    _isoler(monkeypatch)
    image = tmp_path / "image"
    image.mkdir()
    legacy = image / "voix.txt"
    legacy.write_text("[A], a.wav, a.txt\n", encoding="utf-8")
    audio = tmp_path / "data_voice"
    audio.mkdir()
    config.VOIX_FILE = legacy
    config.VOIX_AUDIO_DIR = image
    config.set_audio_dir(audio)

    config.VOIX_FILE.write_text("[A]\n[B]\n", encoding="utf-8")
    legacy.write_text("[vieux]\n", encoding="utf-8")
    config.set_audio_dir(audio)          # appel suivant (toutes les 2 s via /api/etat)

    assert config.VOIX_FILE.read_text(encoding="utf-8") == "[A]\n[B]\n"


def test_generation_ecrit_dans_le_dossier_des_voix(tmp_path, monkeypatch):
    _isoler(monkeypatch)
    image = tmp_path / "image"
    image.mkdir()
    audio = tmp_path / "data_voice"
    audio.mkdir()
    (audio / "Lina.wav").write_bytes(b"RIFF")
    (audio / "Lina.txt").write_text("Bonjour.\n", encoding="utf-8")
    config.VOIX_FILE = image / "voix.txt"      # absent : rien à migrer
    config.VOIX_AUDIO_DIR = image

    config.set_audio_dir(audio)
    produit = voix.generer_voix_txt()

    assert produit == audio / "voix.txt"
    assert produit.exists()
    assert "[Lina], Lina.wav, Lina.txt" in produit.read_text(encoding="utf-8")


def test_chargement_depuis_le_volume(tmp_path, monkeypatch):
    """``load_voix`` sans argument suit le listage migré."""
    _isoler(monkeypatch)
    image = tmp_path / "image"
    image.mkdir()
    audio = tmp_path / "data_voice"
    audio.mkdir()
    (audio / "Lina.wav").write_bytes(b"RIFF")
    (audio / "Lina.txt").write_text("Bonjour.\n", encoding="utf-8")
    (audio / "voix.txt").write_text("[Lina], Lina.wav, Lina.txt\n", encoding="utf-8")
    config.VOIX_FILE = image / "voix.txt"
    config.VOIX_AUDIO_DIR = image

    config.set_audio_dir(audio)
    voix_chargees = voix.load_voix()

    assert voix_chargees.names() == ["Lina"]
