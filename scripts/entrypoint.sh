#!/usr/bin/env bash
set -euo pipefail

# Install torch, torchvision, torchaudio at runtime if not already installed.
# This allows the Docker image to remain slim (no heavy deps during build),
# and these are downloaded only on first launch.
PYTHON="/opt/venv/bin/python"
PIP="${PYTHON%/bin/python}/bin/pip"

# Si torch n'est pas déjà importable, on l'installe
if ! "$PYTHON" -c "import torch" 2>/dev/null; then
    echo "==> Installation de torch, torchvision, torchaudio (premiers lancements)..."
    "$PIP" install --upgrade pip
    "$PIP" install --extra-index-url https://download.pytorch.org/whl/cu130 \
        torch==2.13.0 torchaudio==2.11.0 torchvision==0.28.0
fi

exec "$@"