#!/usr/bin/env bash
# VoiceBuilder — Lanceur (GUI).
#
# Démarre l'interface graphique sur le moteur CosyVoice3.
# Usage :
#   ./run.sh             # lance la GUI
#   ./run.sh --cli F     # (alternative) lance la CLI gen_multi_voix sur le texte F
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""

# Interpréteur : préfère le venv CosyVoice, sinon python du système.
for cand in "$HOME/Projets/CosyVoice/venv/bin/python" "python3"; do
    if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then
        PY="$cand"
        break
    fi
done

# Dossier des fichiers voix : réglable, pris de l'environnement sinon défaut.
export VOICEBUILDER_AUDIO_DIR="${VOICEBUILDER_AUDIO_DIR:-$HOME/Partages/voice}"

cd "$ROOT"

if [ "${1:-}" = "--cli" ]; then
    shift
    exec "$PY" -m tools.gen_multi_voix "$@"
fi

echo "Lancement de VoiceBuilder (GUI)… (venv: $PY)"
echo "Fichiers voix : $VOICEBUILDER_AUDIO_DIR"
exec "$PY" -m app.server "$@"