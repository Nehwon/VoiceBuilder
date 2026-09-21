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

# --- Nettoyage des voix : Demucs (séparation vocale) + DeepFilterNet (débruitage) ---
# NB : deepfilternet==0.5.6 exige packaging<24 (l'image a packaging 24.x) →
# installé en --no-deps --ignore-installed, puis ses dépendances d'exécution à
# la main. Demucs s'installe normalement (torch>=2.1, aucun conflit).
COPY scripts/patch_deepfilternet.py /tmp/patch_deepfilternet.py
RUN pip install "demucs==4.1.0" \
    && pip install --no-deps --ignore-installed "deepfilternet==0.5.6" \
    && pip install --no-deps "deepfilterlib==0.5.6" \
    && pip install --quiet loguru appdirs requests icecream omegaconf rich resampy pystoi tqdm \
    && python /tmp/patch_deepfilternet.py \
    && rm -f /tmp/patch_deepfilternet.py

# --- Accélération vLLM + TensorRT (optionnel) ---
# TensorRT (Flow/DiT) est déjà installé via requirements.txt (ligne dédiée).
# vLLM N'EST PAS installé ici (2026-09-21) : incompatible avec torch==2.13.0
# + fastapi==0.141.1, et un `pip install vllm || echo` best-effort est
# DANGEREUX (pip downgraderait torch/fastapi en silence, exit 0, image
# corrompue). CosyVoice tourne en PyTorch pur (repli automatique des flags
# --vllm/--trt). Réactiver quand vllm supportera torch 2.13.
RUN echo "vLLM volontairement absent (incompatible torch 2.13) — PyTorch pur"

# La couche du venv est figée ici : l'image finale n'installera plus jamais
# les dépendances Python, seulement le code applicatif + patches.
CMD ["bash"]