#!/usr/bin/env bash
set -euo pipefail

# Si torch, torchaudio ou torchvision manquent, on les installe.
# NB : torch est déjà installé au build (requirements.txt) ; ce bloc ne sert
# de filet que si un des trois manque (ex. image allégée).
PYTHON="/opt/venv/bin/python"
PIP="${PYTHON%/bin/python}/bin/pip"

if ! "$PYTHON" -c "import torch, torchaudio, torchvision" 2>/dev/null; then
    echo "==> Installation de torch, torchvision, torchaudio (premiers lancements)..."
    "$PIP" install --upgrade pip
    "$PIP" install --extra-index-url https://download.pytorch.org/whl/cu130 \
        torch==2.13.0 torchaudio==2.11.0 torchvision==0.28.0
fi

exec "$@"