"""Chemins et valeurs par défaut du projet VoiceBuilder (moteur CosyVoice)."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]

# --- Moteur CosyVoice (repo voisin) ----------------------------------------------
COSYVOICE_ROOT = Path.home() / "Projets" / "CosyVoice"
COSYVOICE_VENV = COSYVOICE_ROOT / "venv"
MATCHA_TTS_DIR = COSYVOICE_ROOT / "third_party" / "Matcha-TTS"

# Modèle par défaut (multilingue : français, en, zh, ja...)
COSYVOICE_MODEL_DIR = COSYVOICE_ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B"
COSYVOICE2_MODEL_DIR = COSYVOICE_ROOT / "pretrained_models" / "CosyVoice2-0.5B"

# Prompt système requis par CosyVoice3 avant la transcription de référence.
COSYVOICE3_SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"

# --- Dossiers projet ---------------------------------------------------------------
VOIX_DIR = PROJECT_ROOT / "voix"
TEXTE_DIR = PROJECT_ROOT / "texte"
OUTPUT_DIR = PROJECT_ROOT / "output"
TOOLS_DIR = PROJECT_ROOT / "tools"

VOIX_FILE = VOIX_DIR / "voix.txt"

# --- Génération ---------------------------------------------------------------------
DEFAULT_DEVICE = "cuda:0"
DEFAULT_SPEED = 1.0
DEFAULT_PAUSE = 0.5          # silence (s) entre deux blocs de locuteurs
DEFAULT_FP16 = False

# Découpage adaptatif (validé expérimentalement) :
DEFAULT_MAX_BLOCK_CHARS = 260      # longueur max cible d'un bloc avant drop
DEFAULT_MIN_BLOCK_WORDS = 8        # en dessous, on ne re-split plus

# --- Vérification (Whisper) -----------------------------------------------------------
WHISPER_MODEL = "small"
WHISPER_LANG = "fr"
VERIFY_THRESHOLD = 0.85            # fraction des mots attendus retrouvés
VERIFY_ENABLED = True


def ensure_dirs() -> None:
    for d in (VOIX_DIR, TEXTE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)