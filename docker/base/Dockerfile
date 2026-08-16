# VoiceBuilder — image de base système générique (GPU/NVIDIA).
#
# Contient UNIQUEMENT le socle réutilisable par n'importe quel projet torch/CUDA :
#   - Ubuntu 22.04 à jour + dépendances système
#   - Python 3.10
#   - torch / torchaudio / torchvision / torchcodec (cu130)
#   - packages nvidia-* (cu130) fournis par les wheels pip
#
# C'est une image "réutilisable ailleurs" : PAS de requirements spécifiques au
# projet, PAS de venv dédié. Le venv et les requirements sont le rôle de l'image
# `voicebuilder-vb` (docker/vb/Dockerfile).
#
# Fréquence de compilation : ~1 fois par semaine (les versions torch/cu130
# bougent peu). Poussée sur le registre Gitea.
#
# Construction :
#   docker build -f docker/base/Dockerfile -t voicebuilder-base:cu130 .
#   docker push gitea.lamachere.fr/fabrice/voicebuilder-base:cu130

# Base épurée : les libs CUDA/GPU viennent des wheels pip (torch cu130 +
# packages nvidia-*). Une base nvidia/cuda embarquerait un NCCL système
# incompatible avec torch cu130.
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

# --- Socle torch + CUDA (générique, réutilisable) ---
# L'index cu130 fournit les wheels CUDA (torch, torchaudio, torchvision,
# torchcodec + paquets nvidia-*), indisponibles sur PyPI standard.
# torchcodec est requis par torchaudio 2.11 pour load()/save() (load_with_torchcodec).
RUN pip install --upgrade pip setuptools wheel \
    && pip install --extra-index-url https://download.pytorch.org/whl/cu130 \
        torch==2.13.0 torchaudio==2.11.0 torchvision==0.28.0 torchcodec==0.16.0

CMD ["bash"]