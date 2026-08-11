# VoiceBuilder — image avec prise en charge GPU (NVIDIA).
#
# Construit l'environnement complet : moteur CosyVoice3 (sous-module
# vendor/CosyVoice) + Matcha-TTS + pipeline engine/ + GUI FastAPI.
# Nécessite nvidia-container-toolkit côté hôte et un GPU NVIDIA (CUDA 13).
#
# Build :
#   docker compose build
# Usage :
#   docker compose up            # GUI sur http://127.0.0.1:8000
#   docker compose run --rm cli gen_multi_voix texte/x.md -o /app/output/x.wav

# Base épurée : les libs CUDA/GPU viennent des wheels pip (torch cu130 +
# packages nvidia-*), comme dans l'environnement local validé. Une base
# nvidia/cuda embarquerait un NCCL système incompatible avec torch cu130.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# --- Dépendances système ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3.10-dev \
        python3-pip \
        git ffmpeg libsndfile1 \
        build-essential g++ \
        sox \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

# --- Copie du projet (sans venv/modèles, voir .dockerignore) ---
WORKDIR /app
COPY . .

# --- Environnement Python ---
RUN python3.10 -m venv /opt/venv \
    && pip install --upgrade pip setuptools wheel \
    # torch/torchaudio/torchvision depuis l'index CUDA 13 (Blackwell sm_120)
    && pip install --extra-index-url https://download.pytorch.org/whl/cu130 \
        torch==2.13.0 torchaudio==2.11.0 torchvision==0.28.0 \
    && pip install -r /app/requirements.txt \
    # Snapshot complet de l'environnement validé : tout est listé explicitement.
    && pip install --no-deps -r /app/requirements-lock.txt \
    # Moteur CosyVoice : chargé via sys.path (setup_cosyvoice_paths), pas un
    # paquet pip. Matcha-TTS est un paquet pip (editable).
    && pip install --no-deps -e /app/vendor/CosyVoice/third_party/Matcha-TTS

# --- Patches locaux du moteur ---
RUN bash /app/scripts/apply_cosyvoice_patches.sh

# --- Volumes (dossier des voix réglable) ---
ENV VOICEBUILDER_AUDIO_DIR=/app/voix
VOLUME ["/app/output", "/app/texte", "/app/voix", "/app/vendor/CosyVoice/pretrained_models"]

EXPOSE 8000

# GUI FastAPI par défaut ; `docker compose run --rm cli …` pour la CLI.
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--port", "8000"]
