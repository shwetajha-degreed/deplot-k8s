#!/usr/bin/env bash
set -euo pipefail

# Bootstrap Deplot into the DGCUSUSSBXAKS01 cluster.
# Run from the repo root.

ACR_NAME="dgscucorecr01"
ACR_REGISTRY="${ACR_NAME}.azurecr.io"
CLUSTER_NAME="DGCUSUSSBXAKS01"
CLUSTER_RG="DGCUSUSSBXRG01"
NAMESPACE="deplot-system"

MI_NAME="DGSCUPRMI01"
MI_RG="DGSCUPRRG01"
MI_CLIENT_ID="943f4f75-24ce-41a6-b9ea-c1c59e96a5a4"
FED_CRED_NAME="deplot-system-deplot"
OIDC_ISSUER="https://centralus.oic.prod-aks.azure.com/729a6328-2a2c-4a5e-a619-b292fe7edede/aefe1130-c046-47f7-b812-4def7ceb54ea/"
FED_SUBJECT="system:serviceaccount:${NAMESPACE}:deplot"

BACKEND_IMAGE="${ACR_REGISTRY}/deplot-backend:latest"
FRONTEND_IMAGE="${ACR_REGISTRY}/deplot-frontend:latest"

FRONTEND_HOST="deplot.internal.sbx.degreed.com"
BACKEND_HOST="deplot-api.internal.sbx.degreed.com"
NEXT_PUBLIC_API_URL="https://${BACKEND_HOST}/api/v1"

log()  { printf '\n\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31m[fatal]\033[0m %s\n' "$*" >&2; exit 1; }

command -v az       >/dev/null || die "az CLI not found"
command -v kubectl  >/dev/null || die "kubectl not found"
command -v docker   >/dev/null || die "docker not found"

[[ -f backend/Dockerfile  ]] || die "run from repo root (backend/Dockerfile missing)"
[[ -f frontend/Dockerfile ]] || die "run from repo root (frontend/Dockerfile missing)"

log "Checking kube-context points at ${CLUSTER_NAME}"
CURRENT_CTX="$(kubectl config current-context 2>/dev/null || true)"
if [[ "${CURRENT_CTX}" != *"${CLUSTER_NAME}"* ]]; then
  warn "current context '${CURRENT_CTX}' does not include '${CLUSTER_NAME}'"
  warn "run: az aks get-credentials -g ${CLUSTER_RG} -n ${CLUSTER_NAME} --overwrite-existing"
  read -r -p "Continue anyway? [y/N] " ans; [[ "${ans:-N}" =~ ^[Yy]$ ]] || exit 1
fi

log "Verifying federated credential ${FED_CRED_NAME} on ${MI_NAME}"
if ! az identity federated-credential show \
      --identity-name "${MI_NAME}" \
      --resource-group "${MI_RG}" \
      --name "${FED_CRED_NAME}" >/dev/null 2>&1; then
  cat >&2 <<EOF

Missing federated credential for ${FED_SUBJECT}.
Run the following (needs Owner/UAA on ${MI_RG}), then re-run this script:

  az identity federated-credential create \\
    --name ${FED_CRED_NAME} \\
    --identity-name ${MI_NAME} \\
    --resource-group ${MI_RG} \\
    --issuer ${OIDC_ISSUER} \\
    --subject ${FED_SUBJECT} \\
    --audiences api://AzureADTokenExchange

EOF
  exit 2
fi

log "az acr login ${ACR_NAME}"
az acr login --name "${ACR_NAME}" >/dev/null

log "Building & pushing backend image -> ${BACKEND_IMAGE}"
docker buildx build \
  --platform linux/amd64 \
  -f backend/Dockerfile \
  -t "${BACKEND_IMAGE}" \
  --push .

log "Building & pushing frontend image -> ${FRONTEND_IMAGE}"
docker buildx build \
  --platform linux/amd64 \
  -f frontend/Dockerfile \
  --build-arg "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}" \
  -t "${FRONTEND_IMAGE}" \
  --push .

log "Applying manifests from k8s/deplot-system/"
kubectl apply -f k8s/deplot-system/

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  log "Patching deplot-secrets from env"
  kubectl -n "${NAMESPACE}" patch secret deplot-secrets --type=merge \
    -p "$(python3 -c 'import json,os;print(json.dumps({"stringData":{"GEMINI_API_KEY":os.environ["GEMINI_API_KEY"],"GITHUB_TOKEN":os.environ.get("GITHUB_TOKEN","")}}))')"
else
  warn "GEMINI_API_KEY not set in env; deplot-secrets left with REPLACE_ME."
  warn "Set it later with: kubectl -n ${NAMESPACE} create secret generic deplot-secrets --from-literal=GEMINI_API_KEY=... --dry-run=client -o yaml | kubectl apply -f -"
fi

log "Rotating Redis password"
REDIS_PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
REDIS_URL="redis://:${REDIS_PW}@deplot-redis:6379/0"
kubectl -n "${NAMESPACE}" patch secret deplot-redis-auth --type=merge \
  -p "$(P="${REDIS_PW}" U="${REDIS_URL}" python3 -c 'import json,os;print(json.dumps({"stringData":{"password":os.environ["P"],"REDIS_URL":os.environ["U"]}}))')"
kubectl -n "${NAMESPACE}" rollout restart deployment/deplot-redis || true

log "Waiting for CNPG Cluster deplot-db to become ready (up to 5m)"
for _ in $(seq 1 60); do
  phase="$(kubectl -n "${NAMESPACE}" get cluster.postgresql.cnpg.io deplot-db -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  if [[ "${phase}" == "Cluster in healthy state" ]]; then break; fi
  sleep 5
done
kubectl -n "${NAMESPACE}" wait --for=jsonpath='{.status.phase}=Cluster in healthy state' \
  cluster.postgresql.cnpg.io/deplot-db --timeout=180s || warn "CNPG cluster not yet healthy; proceeding"

log "Deriving DATABASE_URL from deplot-db-app (postgres:// -> postgresql+asyncpg://)"
RAW_URI="$(kubectl -n "${NAMESPACE}" get secret deplot-db-app -o jsonpath='{.data.uri}' | base64 -d)"
[[ -n "${RAW_URI}" ]] || die "deplot-db-app.uri is empty"
ASYNC_URI="${RAW_URI/postgresql:\/\//postgresql+asyncpg://}"
ASYNC_URI="${ASYNC_URI/postgres:\/\//postgresql+asyncpg://}"
kubectl -n "${NAMESPACE}" patch secret deplot-runtime-secrets --type=merge \
  -p "$(U="${ASYNC_URI}" python3 -c 'import json,os;print(json.dumps({"stringData":{"DATABASE_URL":os.environ["U"]}}))')"

log "Restarting backend & frontend to pick up new images/secrets"
kubectl -n "${NAMESPACE}" rollout restart deployment/deplot-backend
kubectl -n "${NAMESPACE}" rollout restart deployment/deplot-frontend
kubectl -n "${NAMESPACE}" rollout status  deployment/deplot-backend  --timeout=180s || true
kubectl -n "${NAMESPACE}" rollout status  deployment/deplot-frontend --timeout=180s || true

cat <<EOF

==================================================================
Deplot bootstrap complete.

  Frontend : https://${FRONTEND_HOST}
  Backend  : https://${BACKEND_HOST}/api/v1
  Namespace: ${NAMESPACE}

Quick checks:
  kubectl -n ${NAMESPACE} get pods
  kubectl -n ${NAMESPACE} logs deploy/deplot-backend --tail=100
  curl -sS https://${BACKEND_HOST}/api/v1/health   # via VPN
==================================================================
EOF
