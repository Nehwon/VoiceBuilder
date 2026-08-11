#!/usr/bin/env bash
# VoiceBuilder — Préparation de l'environnement (setup).
#
# 1. Initialise/récupère le sous-module CosyVoice (git submodule update).
# 2. Applique les patches locaux (scripts/apply_cosyvoice_patches.sh).
# 3. Affiche les chemins attendus (venv, modèle CosyVoice3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CV="$ROOT/vendor/CosyVoice"
VENV="$CV/venv"

cd "$ROOT"

echo "==> Sous-module CosyVoice"
if [ -d "$CV/.git" ]; then
    echo "    déjà présent ($(git -C "$CV" rev-parse --short HEAD))"
else
    git submodule update --init --recursive
fi

echo "==> Patches CosyVoice"
"$ROOT/scripts/apply_cosyvoice_patches.sh"

echo "==> Chemins attendus"
echo "    venv  : $VENV"
echo "    modèle: $CV/pretrained_models/Fun-CosyVoice3-0.5B"
if [ -x "$VENV/bin/python" ]; then
    "$VENV/bin/python" --version
else
    echo "    ⚠ venv absent — à créer :"
    echo "      uv venv \"$VENV\" --python 3.10"
    echo "      uv pip install --python \"$VENV/bin/python\" -r \"$ROOT/requirements.txt\""
fi

echo "Setup terminé."
