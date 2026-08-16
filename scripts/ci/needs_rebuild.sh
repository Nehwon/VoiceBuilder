#!/usr/bin/env bash
# CI — vérifie si une image existe déjà sur le registre Gitea avant de rebuild.
#
# Utilisation :
#   needs_rebuild <owner> <image> <tag>
#
# Renvoie 0 (true) si l'image <owner>/<image>:<tag> n'existe PAS encore sur le
# registre (il faut donc la reconstruire), 1 (false) si elle existe déjà
# (build à sauter).
#
# Variables d'environnement requises :
#   GITEA_URL      ex. https://gitea.lamachere.fr
#   GITEA_TOKEN    token API (secret TOKEN)
set -euo pipefail

OWNER="${1:?owner manquant}"
IMAGE="${2:?image manquante}"
TAG="${3:?tag manquant}"

if [ -z "${GITEA_URL:-}" ] || [ -z "${GITEA_TOKEN:-}" ]; then
    echo "ERREUR : GITEA_URL et GITEA_TOKEN sont requis." >&2
    exit 1
fi

# L'API Gitea liste les versions du package "container". On cherche la version
# correspondant au tag (la version du package container = le tag).
status=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token ${GITEA_TOKEN}" \
    "${GITEA_URL}/api/v1/packages/${OWNER}/container/${IMAGE}/${TAG}")

if [ "$status" = "200" ]; then
    echo "→ ${IMAGE}:${TAG} existe déjà sur le registre. Skip du build."
    exit 1
fi

echo "→ ${IMAGE}:${TAG} absente. Build nécessaire."
exit 0