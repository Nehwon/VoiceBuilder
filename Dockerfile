# VoiceBuilder-omni — image applicative finale (GPU/NVIDIA, branche omni).
#
# Construit l'environnement : moteur OmniVoice (transformers 5.x, direct)
# + pipeline engine/ + GUI FastAPI.
#
# FROM l'image `voicebuilder-vb` (docker/vb/Dockerfile) qui apporte déjà le
# venv + requirements + lock. Cette image-ci copie le code applicatif, applique
# les patches CosyVoice et (filet de sécurité) installe Demucs/DeepFilterNet si
# une image vb périmée ne les contient pas encore. Elle ne réinstalle JAMAIS ni
# torch ni les dépendances principales.
#
# Build :
#   docker compose build          # tire voicebuilder-vb du registre ou cache local
# Usage :
#   docker compose up             # GUI sur http://127.0.0.1:8000
#   docker compose run --rm cli gen_multi_voix texte/x.md -o /app/output/x.wav

# Nom de l'image "vb" (réglable) : registre Gitea par défaut, ou tag local.
ARG VB_IMAGE=ghcr.io/nehwon/voicebuilder-vb:cu130
FROM ${VB_IMAGE}

# --- Copie du projet (sans venv/modèles, voir .dockerignore) ---
WORKDIR /app
COPY . .

# --- Nettoyage des voix : filet de sécurité si l'image vb ne contient pas déjà
# Demucs + DeepFilterNet (vb quotidienne pouvant être périmée au moment du build).
# Normalement présents (docker/vb/Dockerfile) → ce bloc ne fait rien.
COPY scripts/patch_deepfilternet.py /tmp/patch_deepfilternet.py
RUN python -c "import demucs, df, libdf, tqdm" 2>/dev/null \
    || { echo "==> Ajout Demucs + DeepFilterNet + tqdm (vb périmée)…" \
         && pip install "demucs==4.1.0" \
         && pip install --no-deps --ignore-installed "deepfilternet==0.5.6" \
         && pip install --no-deps "deepfilterlib==0.5.6" \
         && pip install --quiet loguru appdirs requests icecream omegaconf rich resampy pystoi tqdm \
         && python /tmp/patch_deepfilternet.py; }
RUN rm -f /tmp/patch_deepfilternet.py

# --- Moteur OmniVoice (branche omni : transformers 5.x, incompatible
# CosyVoice — aucun code CosyVoice dans cette image) ---
RUN pip install "omnivoice==0.2.1" "transformers==5.18.0" "tokenizers==0.23.2" \
    "accelerate==1.15.0" "tensorboardx==2.6.5" "webdataset==1.0.2"

# --- Volumes (dossier des voix réglable) ---
# Le modèle OmniVoice (3,3 Go) est téléchargé au premier lancement dans le
# cache HuggingFace (volume dédié, conservé entre recréations). Les modèles
# enhance (Demucs/DeepFilterNet) restent dans /models (volume-model).
ENV VOICEBUILDER_AUDIO_DIR=/app/voix
VOLUME ["/app/output", "/app/texte", "/app/voix", "/models",
        "/root/.cache/huggingface"]

EXPOSE 8000

# GUI FastAPI par défaut ; `docker compose run --rm cli …` pour la CLI.
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--port", "8000"]