#!/bin/bash
set -euo pipefail

# TCMalloc réduit la fragmentation mémoire sous charge de gros modèles
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4

# Arguments de ligne de commande (via env COMMANDLINE_ARGS, puis "$@")
RAW_ARGS="${COMMANDLINE_ARGS:-}"
unset COMMANDLINE_ARGS

EXTRA_ARGS=()
if [[ -n "$RAW_ARGS" ]]; then
    read -ra EXTRA_ARGS <<< "$RAW_ARGS"
fi

cd /home/forge/sd-webui

# --- Mapping des modèles partagés -------------------------------------------
# /home/fabrice/partages/models (structure ComfyUI) est monté sur models/.
# On crée les liens attendus par Forge Neo vers les dossiers existants.
MODELS_DIR=/home/forge/sd-webui/models
map_models() {
    local target=$1 dir=$2
    if [[ -d "$MODELS_DIR/$dir" && ! -e "$MODELS_DIR/$target" ]]; then
        ln -sfn "$dir" "$MODELS_DIR/$target"
    fi
}
map_models Stable-diffusion stable_diffusion
map_models Lora lora
map_models ControlNet controlnet
map_models VAE vae
map_models text_encoder text_encoders
map_models embeddings embeddings
map_models ESRGAN upscale_models

# --- Persistance de la config ------------------------------------------------
CONFIG_DIR=/home/forge/sd-webui/config
for f in config.json ui-config.json styles.csv user.css; do
    ln -sf "$CONFIG_DIR/$f" "/home/forge/sd-webui/$f"
done

exec python /home/forge/sd-webui/launch.py \
    --listen \
    "${EXTRA_ARGS[@]}" \
    "$@"
