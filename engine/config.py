"""Chemins et valeurs par défaut du projet VoiceBuilder (moteur CosyVoice)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]

# --- Moteur CosyVoice (sous-module git) -------------------------------------
COSYVOICE_ROOT = PROJECT_ROOT / "vendor" / "CosyVoice"
COSYVOICE_VENV = COSYVOICE_ROOT / "venv"
MATCHA_TTS_DIR = COSYVOICE_ROOT / "third_party" / "Matcha-TTS"

# Modèle par défaut (multilingue : français, en, zh, ja...)
# Réglable via la variable d'environnement COSYVOICE_MODEL_DIR (utile si le
# modèle est rangé hors du sous-module, ex. un volume Docker dédié).
_COSYVOICE_MODEL_DIR_DEFAULT = COSYVOICE_ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B"
COSYVOICE_MODEL_DIR = Path(
    os.environ.get("COSYVOICE_MODEL_DIR")
    or _COSYVOICE_MODEL_DIR_DEFAULT
)
COSYVOICE2_MODEL_DIR = COSYVOICE_ROOT / "pretrained_models" / "CosyVoice2-0.5B"

# Source de téléchargement du modèle au premier lancement (engine/modeles.py).
#   - "modelscope" : FunAudioLLM/Fun-CosyVoice3-0.5B-2512 (défaut, source officielle)
#   - "huggingface": FunAudioLLM/Fun-CosyVoice3-0.5B-2512 (miroir, si réseau bloqué)
MODEL_SOURCE = os.environ.get("COSYVOICE_MODEL_SOURCE", "modelscope")
MODEL_ID_COSYVOICE3 = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"

# Prompt système requis par CosyVoice3 avant la transcription de référence.
COSYVOICE3_SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"

# --- Dossiers projet ---------------------------------------------------------------
VOIX_DIR = PROJECT_ROOT / "voix"
TEXTE_DIR = PROJECT_ROOT / "texte"
OUTPUT_DIR = PROJECT_ROOT / "output"
TOOLS_DIR = PROJECT_ROOT / "tools"

VOIX_FILE = VOIX_DIR / "voix.txt"

# Dossier des fichiers audio (wav) et de leurs transcriptions (txt) pour les voix.
# Réglable via la variable d'environnement VOICEBUILDER_AUDIO_DIR.
VOIX_AUDIO_DIR = Path(
    os.environ.get("VOICEBUILDER_AUDIO_DIR")
    or Path.home() / "Projets" / "Personnel (Fabrice)" / "vb-voice"
)

# Chemins de recherche, dans l'ordre, pour résoudre un wav/txt listé dans voix.txt :
#   1) relatif au projet (PROJECT_ROOT/…)
#   2) la racine des voix     (VOIX_DIR/…)
#   3) le dossier audio dédié (VOIX_AUDIO_DIR/…)
VOIX_SEARCH_DIRS = (PROJECT_ROOT, VOIX_DIR, VOIX_AUDIO_DIR)


def set_audio_dir(path) -> None:
    """Change au runtime le dossier des fichiers wav/txt des voix.

    Met à jour ``VOIX_AUDIO_DIR`` et ``VOIX_SEARCH_DIRS`` (utilisé par le GUI web
    pour rendre ce dossier réglable depuis l'interface).
    """
    global VOIX_AUDIO_DIR, VOIX_SEARCH_DIRS
    VOIX_AUDIO_DIR = Path(path).expanduser()
    VOIX_SEARCH_DIRS = (PROJECT_ROOT, VOIX_DIR, VOIX_AUDIO_DIR)


def set_model_dir(path) -> None:
    """Change au runtime le dossier du modèle CosyVoice3.

    Utile quand le modèle est rangé hors du sous-module (volume Docker, autre
    disque, etc.) ou téléchargé depuis l'interface.
    """
    global COSYVOICE_MODEL_DIR
    COSYVOICE_MODEL_DIR = Path(path).expanduser()

# --- Génération ---------------------------------------------------------------------
DEFAULT_DEVICE = "cuda:0"
DEFAULT_SPEED = 1.0
DEFAULT_PAUSE = 0.5          # silence (s) entre deux blocs de locuteurs
DEFAULT_FP16 = False

# Découpage adaptatif (validé expérimentalement) :
DEFAULT_MAX_BLOCK_CHARS = 600      # longueur max cible d'un bloc (fusionner plus de
                                   # texte par lot → moins de ruptures de ton)
DEFAULT_MIN_BLOCK_WORDS = 8        # en dessous, on ne re-split plus

# --- Vérification (Whisper) -----------------------------------------------------------
WHISPER_MODEL = "small"
WHISPER_LANG = "fr"
VERIFY_THRESHOLD = 0.85            # fraction des mots attendus retrouvés
VERIFY_ENABLED = True


def ensure_dirs() -> None:
    for d in (VOIX_DIR, TEXTE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)