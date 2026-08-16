# VoiceBuilder — image applicative finale (GPU/NVIDIA).
#
# Construit l'environnement : moteur CosyVoice3 (sous-module vendor/CosyVoice)
# + pipeline engine/ + GUI FastAPI.
#
# La base (torch + nvidia + deps système + venv) est fournie par l'image
# `voicebuilder-base` (voir docker/base/Dockerfile), construite rarement et
# poussée vers le registre Gitea. Cette image-ci ne réinstalle jamais torch :
# elle ne fait que copier le code applicatif et appliquer les patches, d'où
# des builds quotidiens en quelques minutes au lieu de ~21 min.
#
# Build :
#   docker compose build          # tire voicebuilder-base du registre ou cache local
# Usage :
#   docker compose up             # GUI sur http://127.0.0.1:8000
#   docker compose run --rm cli gen_multi_voix texte/x.md -o /app/output/x.wav

# Nom de l'image de base (réglable) : registre Gitea par défaut, ou tag local.
ARG BASE_IMAGE=gitea.lamachere.fr/fabrice/voicebuilder-base:cu130
FROM ${BASE_IMAGE}

# --- Copie du projet (sans venv/modèles, voir .dockerignore) ---
WORKDIR /app
COPY . .

# --- Patches locaux du moteur ---
# La base n'a PAS les patches (elle ne contient que les wheels pip). On
# applique ici les patches CosyVoice (fix load_wav, etc.) au code du
# sous-module copié ci-dessus.
RUN bash /app/scripts/apply_cosyvoice_patches.sh

# --- Volumes (dossier des voix réglable) ---
# Le modèle CosyVoice3 est volontairement HORS image : téléchargé au premier
# lancement depuis l'interface dans /models (volume inscriptible), ou monté
# depuis un volume/dossier pré-rempli. Voir docker-compose.yml (COSYVOICE_MODEL_DIR).
ENV VOICEBUILDER_AUDIO_DIR=/app/voix \
    COSYVOICE_MODEL_DIR=/models \
    COSYVOICE_MODEL_SOURCE=modelscope
VOLUME ["/app/output", "/app/texte", "/app/voix", "/models"]

EXPOSE 8000

# GUI FastAPI par défaut ; `docker compose run --rm cli …` pour la CLI.
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--port", "8000"]