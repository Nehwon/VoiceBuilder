"""Chemins et valeurs par défaut du projet VoiceBuilder (moteur OmniVoice)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]

# Nettoyage des voix (Demucs + DeepFilterNet) : dossier où ranger les modèles
# téléchargés (poids Demucs via TORCH_HOME, poids DeepFilterNet via cache).
# Réglable via VOICEBUILDER_ENHANCE_DIR ; en Docker : /models/enhance_models.
ENHANCE_MODEL_DIR = Path(
    os.environ.get("VOICEBUILDER_ENHANCE_DIR")
    or (PROJECT_ROOT / "enhance_models")
)
# --- Moteur OmniVoice (M19.1) --------------------------------------------------
# Modèle HF "k2-fsa/OmniVoice" (fp16, 24 kHz natifs). Téléchargé au premier
# chargement dans le cache HuggingFace, sauf si OMNIVOICE_MODEL_DIR pointe
# vers un dossier local déjà rempli (ex. volume Docker /models/omnivoice).
OMNIVOICE_MODEL_ID = os.environ.get("OMNIVOICE_MODEL_ID", "k2-fsa/OmniVoice")
OMNIVOICE_MODEL_DIR = Path(
    os.environ.get("OMNIVOICE_MODEL_DIR")
    or OMNIVOICE_MODEL_ID
)

# Moteurs TTS disponibles et moteur par défaut des voix sans colonne moteur
# (voix.txt). Réglable via VOICEBUILDER_MOTEUR_DEFAUT.
MOTEURS = ("omnivoice",)  # branche omni : moteur unique
MOTEUR_DEFAUT = os.environ.get("VOICEBUILDER_MOTEUR_DEFAUT", "omnivoice")
if MOTEUR_DEFAUT not in MOTEURS:
    MOTEUR_DEFAUT = "omnivoice"

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

# --- Musique de fond (BGM, mixée sous les segments <|BGM|>) --------------------------
# Le moteur zero-shot ne génère pas de lit musical : on le mixe nous-mêmes.
MUSIQUE_DIR = PROJECT_ROOT / "musique"
BGM_VOLUME_DEFAUT = 0.15
BGM_LIT: Path | None = None      # lit actif (None = pas de musique)
BGM_VOLUME: float = BGM_VOLUME_DEFAUT


def set_bgm(lit: Path | str | None, volume: float | None = None) -> None:
    """Change au runtime le lit musical et son volume (GUI → persistance)."""
    global BGM_LIT, BGM_VOLUME
    BGM_LIT = Path(lit).expanduser() if lit else None
    if volume is not None:
        BGM_VOLUME = max(0.0, min(0.5, float(volume)))


def set_audio_dir(path) -> None:
    """Change au runtime le dossier des fichiers wav/txt des voix.

    Met à jour ``VOIX_AUDIO_DIR`` et ``VOIX_SEARCH_DIRS`` (utilisé par le GUI web
    pour rendre ce dossier réglable depuis l'interface).
    """
    global VOIX_AUDIO_DIR, VOIX_SEARCH_DIRS
    VOIX_AUDIO_DIR = Path(path).expanduser()
    VOIX_SEARCH_DIRS = (PROJECT_ROOT, VOIX_DIR, VOIX_AUDIO_DIR)


def set_moteur_defaut(nom: str) -> None:
    """Change au runtime le moteur par défaut (GUI → persistance).

    S'applique aux voix sans colonne moteur dans ``voix.txt``. Lève
    ``ValueError`` si le moteur est inconnu.
    """
    global MOTEUR_DEFAUT
    nom = (nom or "").strip().lower()
    if nom not in MOTEURS:
        raise ValueError(f"Moteur inconnu : {nom} (attendu : {', '.join(MOTEURS)})")
    MOTEUR_DEFAUT = nom


def set_model_dir(path) -> None:
    """Change au runtime le dossier du modèle TTS (legacy).

HF_TOKEN = clé HuggingFace (optionnelle mais recommandée : évite les
erreurs CAS/XetHub au téléchargement du modèle). Priorité : variable
d'environnement ``HF_TOKEN`` > valeur persistée via ``set_hf_token``.


    Utile quand le modèle est rangé hors du sous-module (volume Docker, autre
    disque, etc.) ou téléchargé depuis l'interface.
    """
    global COSYVOICE_MODEL_DIR
    COSYVOICE_MODEL_DIR = Path(path).expanduser()


# --- Clé HuggingFace (téléchargement modèle, anti-erreurs CAS) -----------------
HF_TOKEN: str | None = os.environ.get("HF_TOKEN") or None


def set_hf_token(token: str | None) -> None:
    """Mémorise la clé HuggingFace (GUI → persistance + ``os.environ``)."""
    global HF_TOKEN
    token = (token or "").strip() or None
    HF_TOKEN = token
    if token:
        os.environ["HF_TOKEN"] = token
    else:
        os.environ.pop("HF_TOKEN", None)


def hf_token() -> str | None:
    """Clé effective (env prioritaire, puis valeur persistée)."""
    return os.environ.get("HF_TOKEN") or HF_TOKEN

# --- Génération ---------------------------------------------------------------------
DEFAULT_DEVICE = "cuda:0"
DEFAULT_SPEED = 1.0
DEFAULT_PAUSE = 0.5          # silence (s) entre deux blocs de locuteurs
DEFAULT_FP16 = False

# Découpage adaptatif (validé par benchmark M4.x, 2026-09-04) :
DEFAULT_MAX_BLOCK_CHARS = 600      # sweet spot : 4 blocs, 95.7% couverture, 37 s
                                   # (< 200 → overhead Whisper ×3 ; > 800 → couverture baisse)
DEFAULT_MIN_BLOCK_WORDS = 8        # en dessous, on ne re-split plus

# --- Vérification (Whisper) -----------------------------------------------------------
WHISPER_MODEL = "small"            # validé : assez précis, pas trop lent
WHISPER_LANG = "fr"
VERIFY_THRESHOLD = 0.85            # conservative mais sûr (0.70 = 96.8% couv, +rapide)
VERIFY_ENABLED = True              # active = +rapide (RTF ×2.4) ET meilleure couverture

# --- Accélération (vLLM / TensorRT) -------------------------------------------------
DEFAULT_VLLM = False               # vLLM : accélère le LLM autoregressif (batch)
DEFAULT_TRT = False                # TensorRT : accélère le Flow (DiT, 10 pas Euler)

# --- LLM local : incises & compréhension (M20.6, Ollama sur GPU 2nd) -----------------
# Réglables via l'environnement (utile en Docker / multi-machine).
OLLAMA_URL = os.environ.get("VOICEBUILDER_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODELE_INCISES = os.environ.get("VOICEBUILDER_OLLAMA_MODELE", "qwen2.5:7b-instruct")
OLLAMA_TIMEOUT = float(os.environ.get("VOICEBUILDER_OLLAMA_TIMEOUT", "300"))
INCISES_CHUNK_CHARS = int(os.environ.get("VOICEBUILDER_INCISES_CHUNK", "2500"))
INCISES_RAPPEL_MIN = 0.88          # rappel lexical sortie/entrée sous lequel on retente


def ensure_dirs() -> None:
    for d in (VOIX_DIR, TEXTE_DIR, OUTPUT_DIR, MUSIQUE_DIR):
        d.mkdir(parents=True, exist_ok=True)