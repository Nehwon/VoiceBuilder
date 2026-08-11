#!/usr/bin/env bash
# Applique les patches locaux au sous-module CosyVoice (vendor/CosyVoice).
#
# CosyVoice est un sous-module pointant vers l'upstream FunAudioLLM/CosyVoice.
# Ces patches ne sont pas (encore) upstream : ils doivent être ré-appliqués
# après chaque `git submodule update --init --recursive`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CV="$ROOT/vendor/CosyVoice"
PATCHES="$ROOT/patches/cosyvoice"

if [ ! -d "$CV" ]; then
    echo "ERREUR : $CV absent. Lance d'abord : git submodule update --init --recursive" >&2
    exit 1
fi

cd "$CV"

for patch in "$PATCHES"/*.patch; do
    [ -e "$patch" ] || continue
    echo "→ Application de $(basename "$patch")"
    if git apply --check "$patch" 2>/dev/null; then
        git apply "$patch"
    else
        echo "  (déjà appliqué ou incompatible — ignoré)"
    fi
done

echo "Patches CosyVoice : OK"
