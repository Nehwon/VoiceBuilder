# VoiceBuilder — image de base stable (GPU/NVIDIA).
#
# Contient TOUT ce qui ne bouge pratiquement jamais pendant le développement :
#   - Ubuntu système à jour + dépendances système
#   - venv Python
#   - torch / torchaudio / torchvision / torchcodec + packages nvidia-* (cu130)
#   - le snapshot complet requirements-lock.txt (--no-deps)
#   - Matcha-TTS (paquet pip des `third_party` du sous-module)
#
# Cette base est construite RAREMENT (uniquement quand requirements.txt ou
# requirements-lock.txt changent) et poussée vers le registre Gitea. L'image
# finale `voicebuilder` la référence via FROM, ce qui évite de re-télécharger
# torch (plusieurs Go) à chaque build du code applicatif.
#
# Construction (la première fois, puis à chaque changement de requirements) :
#   docker build -f docker/base/Dockerfile -t voicebuilder-base:cu130 \
#     --build-arg MATCHA_TTS_DIR=third_party/Matcha-TTS .
#   docker push gitea.lamachere.fr/fabrice/voicebuilder-base:cu130

# Base épurée : les libs CUDA/GPU viennent des wheels pip (torch cu130 +
# packages nvidia-*). Une base nvidia/cuda embarquerait un NCCL système
# incompatible avec torch cu130.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

# --- Dépendances système ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3.10-dev \
        python3-pip \
        git ffmpeg libsndfile1 \
        build-essential g++ \
        sox \
    && rm -rf /var/lib/apt/lists/*

# --- Environnement Python : tout le lourd (torch, nvidia, lock) ---
# L'index cu130 fournit les wheels CUDA (torch, torchaudio, torchvision,
# torchcodec + paquets nvidia-*), indisponibles sur PyPI standard.
# NB : Matcha-TTS N'EST PAS installé ici — il est chargé par source depuis
# vendor/CosyVoice/third_party/Matcha-TTS dans l'image finale (voir
# engine/config.py MATCHA_TTS_DIR + engine/cosyvoice_engine.py setup_cosyvoice_paths).
COPY requirements.txt requirements-lock.txt /tmp/requirements/
RUN python3.10 -m venv /opt/venv \
    && pip install --upgrade pip setuptools wheel \
    && pip install --extra-index-url https://download.pytorch.org/whl/cu130 -r /tmp/requirements/requirements.txt \
    # Snapshot complet de l'environnement validé : tout est listé explicitement.
    && pip install --no-deps --extra-index-url https://download.pytorch.org/whl/cu130 -r /tmp/requirements/requirements-lock.txt \
    && rm -rf /tmp/requirements

# La couche du venv est figée ici : l'image finale n'installera plus jamais
# torch ni les packages nvidia, seulement les dépendances du code applicatif
# (généralement déjà présentes via le lock).
CMD ["bash"]