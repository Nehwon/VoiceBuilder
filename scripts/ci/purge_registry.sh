#!/usr/bin/env bash
# CI — purge les versions obsolètes du registre container Gitea.
#
# Garde TOUJOURS les tags stables (latest, main, cu130, plus les tags de
# version vX.Y.Z / X.Y.Z des N dernières versions), et supprime les autres
# (ex. les tags <image>-<hash> générés par le mécanisme "skip si inchangé").
#
# Utilisation :
#   purge_registry <owner> <image> <keep>
#   keep : nombre de versions récentes (hors stables) à conserver
#
# Variables d'environnement requises :
#   GITEA_URL      ex. https://gitea.lamachere.fr
#   GITEA_TOKEN    token API (secret TOKEN)
set -euo pipefail

OWNER="${1:?owner manquant}"
IMAGE="${2:?image manquante}"
KEEP="${3:-5}"

if [ -z "${GITEA_URL:-}" ] || [ -z "${GITEA_TOKEN:-}" ]; then
    echo "ERREUR : GITEA_URL et GITEA_TOKEN sont requis." >&2
    exit 1
fi

AUTH=(-H "Authorization: token ${GITEA_TOKEN}")
API="${GITEA_URL}/api/v1/packages/${OWNER}/container/${IMAGE}"

# Tags toujours conservés, quoi qu'il arrive.
STABLE='^(latest|main|cu130)$'

echo "→ Purge du package ${OWNER}/${IMAGE} (keep=${KEEP})..."

# Liste des versions triées (le plus récent en premier).
mapfile -t VERSIONS < <(curl -s "${AUTH[@]}" "${API}?page=1&limit=100" \
    | python3 -c "
import json,sys
data=json.load(sys.stdin)
# data est une liste de versions {id, version, created_at}
data.sort(key=lambda v: v.get('created_at',''), reverse=True)
for v in data:
    print(v['id'], v['version'])
")

if [ "${#VERSIONS[@]}" -eq 0 ]; then
    echo "  Aucune version."
    exit 0
fi

echo "  Versions trouvées : ${#VERSIONS[@]}"

kept=0
for entry in "${VERSIONS[@]}"; do
    id="${entry%% *}"
    version="${entry#* }"
    echo "  -- ${version} (id=${id})"
done

# Supprime les versions : on garde les KEEP plus récentes, plus les stables,
# on supprime le reste.
removed=0
kept_non_stable=0
for entry in "${VERSIONS[@]}"; do
    id="${entry%% *}"
    version="${entry#* }"
    if [[ "$version" =~ $STABLE ]]; then
        echo "    garde (stable): ${version}"
        continue
    fi
    if [ "$kept_non_stable" -lt "$KEEP" ]; then
        echo "    garde (récent): ${version}"
        kept_non_stable=$((kept_non_stable + 1))
        continue
    fi
    code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
        "${AUTH[@]}" "${API}/${version}")
    echo "    supprime: ${version} (http ${code})"
    removed=$((removed + 1))
done

echo "→ Purge terminée : ${removed} version(s) supprimée(s)."