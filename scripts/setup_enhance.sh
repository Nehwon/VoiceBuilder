#!/usr/bin/env bash
# Installe les dépendances du nettoyage des voix (Demucs + DeepFilterNet) dans
# le venv courant, puis applique le patch DeepFilterNet.
#
# NB : deepfilternet==0.5.6 exige `packaging<24` (incompatible avec l'image où
# packaging==24.x). On l'installe donc en `--no-deps --ignore-installed` puis on
# installe ses dépendances d'exécution réellement utilisées à la main. Demucs,
# lui, s'installe normalement (aucun conflit avec torch >= 2.1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIP="${PIP:-pip}"

echo "==> Installation de Demucs (séparation vocale)…"
"$PIP" install "demucs==4.1.0"

echo "==> Installation de DeepFilterNet (débruitage) — no-deps + libs runtime…"
"$PIP" install --no-deps --ignore-installed "deepfilternet==0.5.6"
"$PIP" install --no-deps "deepfilterlib==0.5.6"
# Dépendances réellement importées à l'exécution de df.enhance / df.*
"$PIP" install --quiet loguru appdirs requests icecream omegaconf rich resampy pystoi

echo "==> Patch DeepFilterNet (torchaudio >= 2.9)…"
python "$ROOT/scripts/patch_deepfilternet.py"

echo "Dépendances d'amélioration : OK"
