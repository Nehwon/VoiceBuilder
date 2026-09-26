# VoiceBuilder — image Stable Diffusion WebUI Forge Neo (GPU NVIDIA).
#
# Fork Neo de sd-webui-forge (branche neo) : WebUI stable diffusion optimisée.
# Base : nvidia/cuda:12.6.3-runtime-ubuntu22.04 + Python 3.13 via uv + PyTorch cu126.
#
# Les données persistantes (modèles, sorties, extensions, config) sont des volumes
# montés par docker-compose ; le conteneur lui-même est éphémère et reconstruit
# quand le code du fork évolue.
#
# Construction :
#   docker compose build forge
#   docker compose up -d forge
#
# Selon le README docker officiel du projet (Haoming02/sd-webui-forge-classic@neo).

# syntax=docker/dockerfile:1
ARG CUDA_VERSION=12.6.3

FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04

# Index PyTorch (cu126 = build CUDA du fork officiel).
ARG TORCH_INDEX=cu126

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=automatic \
    UV_NO_CACHE=1 \
    TORCH_INDEX_URL=https://download.pytorch.org/whl/${TORCH_INDEX}

# binaire uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libtcmalloc-minimal4 \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root (UID 99 / GID 100 = nobody:users, comme l'officiel)
RUN groupadd -g 100 users 2>/dev/null || true \
    && useradd -u 99 -g 100 -d /home/forge -m -s /bin/bash forge

WORKDIR /home/forge/sd-webui

# Invalide le cache quand le fork (branche neo) évolue
ADD https://api.github.com/repos/Haoming02/sd-webui-forge-classic/commits/neo /tmp/neo-rev.json

# Clone au build
RUN git clone --branch neo --depth 1 --filter blob:none \
        https://github.com/Haoming02/sd-webui-forge-classic.git . \
    && chown -R 99:100 /home/forge

USER forge

# Venv Python 3.13 via uv
RUN uv venv venv --python 3.13 --seed

ENV VIRTUAL_ENV="/home/forge/sd-webui/venv" \
    PATH="/home/forge/sd-webui/venv/bin:$PATH" \
    PYTHON="/home/forge/sd-webui/venv/bin/python3.13"

# PyTorch pré-installé (cu126)
RUN uv pip install torch torchvision \
    --index-url "https://download.pytorch.org/whl/${TORCH_INDEX}"

# Répertoires persistants (survolés par les volumes compose)
RUN mkdir -p \
        models/Stable-diffusion \
        models/VAE \
        models/Lora \
        models/ControlNet \
        extensions \
        config \
        output

# Entrypoint
COPY --chown=99:100 entrypoint.sh /home/forge/sd-webui/entrypoint.sh
RUN chmod +x /home/forge/sd-webui/entrypoint.sh

EXPOSE 7860

# prepare_environment() s'exécute au premier démarrage (peut être long)
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=15 \
    CMD curl -f http://localhost:7860/ || exit 1

ENTRYPOINT ["/home/forge/sd-webui/entrypoint.sh"]