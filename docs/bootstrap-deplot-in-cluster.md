# Bootstrap Deplot into AKS (`DGCUSUSSBXAKS01`)

This runbook deploys the Deplot backend + frontend into the `deplot-system`
namespace on the sandbox AKS cluster, replacing the laptop `uvicorn` +
`docker-compose` local setup.

## Endpoints (after bootstrap)

- Frontend: `https://deplot.internal.sbx.degreed.com` (VPN required)
- Backend:  `https://deplot-api.internal.sbx.degreed.com/api/v1`

## Prerequisites

- Corp VPN
- `az` CLI, logged in against the sandbox subscription
  (`az account show`)
- `kubectl` with context on `DGCUSUSSBXAKS01`:
  ```
  az aks get-credentials -g DGCUSUSSBXRG01 -n DGCUSUSSBXAKS01 --overwrite-existing
  ```
- Docker (with `buildx`)
- `python3` (used for URL rewriting and password generation)
- ACR push perms on `dgscucorecr01`
- Cluster prerequisites already installed:
  - CNPG operator in `cnpg-system`
  - Envoy Gateway with `internal-gateway/internal-gateway`, listener `https-degreed-com`
  - Azure Workload Identity mutating webhook

## One-time: federated credential

The `deplot` ServiceAccount federates into managed identity `DGSCUPRMI01`
(`clientId=943f4f75-24ce-41a6-b9ea-c1c59e96a5a4`). If the bootstrap script
exits with `Missing federated credential`, run:

```
az identity federated-credential create \
  --name deplot-system-deplot \
  --identity-name DGSCUPRMI01 \
  --resource-group DGSCUPRRG01 \
  --issuer https://centralus.oic.prod-aks.azure.com/729a6328-2a2c-4a5e-a619-b292fe7edede/aefe1130-c046-47f7-b812-4def7ceb54ea/ \
  --subject system:serviceaccount:deplot-system:deplot \
  --audiences api://AzureADTokenExchange
```

Requires Owner / User Access Admin on `DGSCUPRRG01`.

## Run the bootstrap

From the repo root:

```
export GEMINI_API_KEY=...              # optional but recommended
export GITHUB_TOKEN=ghp_...            # optional
bash scripts/bootstrap-deplot.sh
```

The script:

1. Sanity-checks tooling and kube context.
2. Verifies the federated credential exists (prints the `az` command if not).
3. `az acr login` + `docker buildx build --push` for backend and frontend,
   baking `NEXT_PUBLIC_API_URL=https://deplot-api.internal.sbx.degreed.com/api/v1`
   into the frontend image.
4. `kubectl apply -f k8s/deplot-system/` — namespace, quota, RBAC, CNPG
   `deplot-db`, Redis, backend/frontend Deployments + Services + HTTPRoutes,
   ConfigMap, Secrets.
5. Rotates the Redis password.
6. Waits for CNPG to be healthy, reads its `deplot-db-app.uri`, rewrites
   `postgres://` → `postgresql+asyncpg://`, and stores it as
   `deplot-runtime-secrets.DATABASE_URL`.
7. Restarts backend/frontend and prints the endpoints.

## Rotating the Gemini key

```
kubectl -n deplot-system create secret generic deplot-secrets \
  --from-literal=GEMINI_API_KEY=NEW \
  --from-literal=GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n deplot-system rollout restart deployment/deplot-backend
```

## Teardown

```
kubectl delete -f k8s/deplot-system/           # keep the ACR images
kubectl delete namespace deplot-system         # nukes PVCs too
```

CNPG PVCs are namespace-scoped; deleting the namespace deletes them.

## Notes / gotchas

- The `ClusterRole` is cluster-scoped on purpose — Deplot creates
  per-tenant namespaces at runtime. See `k8s/deplot-system/20-rbac.yaml`.
- Redis auth uses a Secret file mounted at `/etc/redis/password`, matching
  `backend/app/services/deps/redis.py`.
- The frontend image is not read-only-root; Next.js writes cache under
  `.next/cache` at runtime.
- Local dev (`docker/docker-compose.yml`, `uvicorn`) is unchanged.
