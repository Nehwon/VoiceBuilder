# VoiceBuilder — image applicative finale (GPU/NVIDIA).
#
# Construit l'environnement : moteur CosyVoice3 (sous-module vendor/CosyVoice)
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
ARG VB_IMAGE=gitea.lamachere.fr/fabrice/voicebuilder-vb:cu130
FROM ${VB_IMAGE}

# --- Copie du projet (sans venv/modèles, voir .dockerignore) ---
WORKDIR /app
COPY . .

# --- Nettoyage des voix : filet de sécurité si l'image vb ne contient pas déjà
# Demucs + DeepFilterNet (vb quotidienne pouvant être périmée au moment du build).
# Normalement présents (docker/vb/Dockerfile) → ce bloc ne fait rien.
COPY scripts/patch_deepfilternet.py /tmp/patch_deepfilternet.py
RUN python -c "import demucs, df, libdf" 2>/dev/null \
    || { echo "==> Ajout Demucs + DeepFilterNet (vb périmée)…" \
         && pip install "demucs==4.1.0" \
         && pip install --no-deps --ignore-installed "deepfilternet==0.5.6" \
         && pip install --no-deps "deepfilterlib==0.5.6" \
         && pip install --quiet loguru appdirs requests icecream omegaconf rich resampy pystoi \
         && python /tmp/patch_deepfilternet.py; }
RUN rm -f /tmp/patch_deepfilternet.py

# --- Patches locaux du moteur ---
# L'image vb n'a PAS les patches (elle ne contient que les dépendances pip).
# On applique ici les patches CosyVoice (fix load_wav, etc.) au code du
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