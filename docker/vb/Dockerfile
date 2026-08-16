# VoiceBuilder — image "vb" : pré-requis spécifiques au projet.
#
# FROM l'image de base générique (torch/CUDA, voir docker/base/Dockerfile) et
# ajoute TOUT ce qui est propre à VoiceBuilder mais ne dépend pas du code
# applicatif :
#   - venv Python (/opt/venv)
#   - requirements.txt (dépendances directes)
#   - requirements-lock.txt (snapshot complet, --no-deps)
#
# Ne contient PAS le code applicatif ni les patches CosyVoice : c'est le rôle
# de l'image finale (Dockerfile racine). Ainsi, une modification du code ne
# force PAS la réinstallation des dépendances Python.
#
# Fréquence de compilation : ~1 fois par jour (les requirements bougent plus
# souvent que torch). Poussée sur le registre Gitea.
#
# Construction :
#   docker build -f docker/vb/Dockerfile -t voicebuilder-vb:cu130 .
#   docker push gitea.lamachere.fr/fabrice/voicebuilder-vb:cu130

ARG BASE_IMAGE=gitea.lamachere.fr/fabrice/voicebuilder-base:cu130
FROM ${BASE_IMAGE}

ENV PATH="/opt/venv/bin:$PATH"

# --- venv + requirements du projet ---
# Matcha-TTS N'EST PAS installé ici : il est chargé par source depuis
# vendor/CosyVoice/third_party/Matcha-TTS dans l'image finale (voir
# engine/config.py MATCHA_TTS_DIR + engine/cosyvoice_engine.py setup_cosyvoice_paths).
COPY requirements.txt requirements-lock.txt /tmp/requirements/
RUN python3.10 -m venv /opt/venv \
    && pip install --upgrade pip setuptools wheel \
    && pip install --extra-index-url https://download.pytorch.org/whl/cu130 -r /tmp/requirements/requirements.txt \
    # Snapshot complet de l'environnement validé : tout est listé explicitement.
    && pip install --no-deps --extra-index-url https://download.pytorch.org/whl/cu130 -r /tmp/requirements/requirements-lock.txt \
    && rm -rf /tmp/requirements

# La couche du venv est figée ici : l'image finale n'installera plus jamais
# les dépendances Python, seulement le code applicatif + patches.
CMD ["bash"]