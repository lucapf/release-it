#!/usr/bin/env bash
#
# Build the ReleaseIT images and deploy the whole stack into a local minikube
# cluster with a single Helm release (the `release-it` umbrella chart).
#
#   ./deploy/minikube-deploy.sh
#
# What it does:
#   1. starts minikube (if needed) and enables the ingress addon
#   2. builds the three app images inside minikube's Docker daemon (no registry)
#   3. helm upgrade --install the umbrella chart (db + auth + backend + frontend)
#
set -euo pipefail

# --- locations --------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
UMBRELLA_DIR="${SCRIPT_DIR}/helm/release-it"

PROFILE="${MINIKUBE_PROFILE:-minikube}"
NAMESPACE="${NAMESPACE:-default}"
RELEASE="${RELEASE:-release-it}"
INGRESS_HOST="releaseit.local"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# --- 0. preflight -----------------------------------------------------------
for bin in minikube kubectl helm docker; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: '$bin' not found in PATH" >&2; exit 1; }
done

# --- 1. ensure the cluster is up + ingress available ------------------------
if ! minikube -p "$PROFILE" status >/dev/null 2>&1; then
  log "Starting minikube (profile: $PROFILE)"
  minikube -p "$PROFILE" start
fi
log "Ensuring the ingress addon is enabled"
minikube -p "$PROFILE" addons enable ingress >/dev/null

# --- 2. build images inside minikube's Docker daemon ------------------------
log "Building images inside minikube's Docker daemon"
build() {
  local name="$1" ctx="$2"
  log "Building image: ${name}:latest"
  minikube -p "$PROFILE" image build -t "${name}:latest" -t "docker.io/library/${name}:latest" "$ctx"
}
build releaseit-auth     "${ROOT_DIR}/auth"
build releaseit-backend  "${ROOT_DIR}/backend"
build releaseit-frontend "${ROOT_DIR}/frontend"

# --- 3. resolve subchart deps + deploy --------------------------------------
log "Resolving umbrella subchart dependencies"
helm dependency build "${UMBRELLA_DIR}"

log "Deploying the release-it umbrella chart"
helm upgrade --install "$RELEASE" "${UMBRELLA_DIR}" \
  --namespace "$NAMESPACE" --create-namespace --wait --timeout 5m

# A rebuilt :latest image won't restart pods on its own; roll the app
# Deployments to pick it up. The DB StatefulSet is left running to keep data.
log "Restarting app Deployments to pick up rebuilt images"
kubectl -n "$NAMESPACE" rollout restart \
  deployment/releaseit-auth deployment/releaseit-backend deployment/releaseit-frontend
for dep in releaseit-auth releaseit-backend releaseit-frontend; do
  kubectl -n "$NAMESPACE" rollout status "deployment/${dep}" --timeout 5m
done

# --- 4. access info ---------------------------------------------------------
IP="$(minikube -p "$PROFILE" ip)"
log "Deployment complete"
cat <<EOF

ReleaseIT is running in minikube (profile: $PROFILE, namespace: $NAMESPACE,
release: $RELEASE). One Postgres instance backs both services, each segregated
into its own schema/role.

Access via the ingress host '${INGRESS_HOST}'. Add this line to /etc/hosts:

    ${IP}  ${INGRESS_HOST}

Then open:  http://${INGRESS_HOST}/   (default login: admin / admin)

Or skip /etc/hosts and port-forward the frontend directly:

    kubectl -n ${NAMESPACE} port-forward svc/releaseit-frontend 8080:80
    # -> http://localhost:8080/

EOF
