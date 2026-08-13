# Day 0 — Zerops checklist

## Account setup
1. Register: https://www.wemakedevs.org/hackathons/zerops#register
2. Create Zerops account ($15 free credits)
3. Copy API token to `.env` as `ZEROPS_API_TOKEN`
4. Set `ZEROPS_PROJECT_ID` to your **Deplot platform** project ID
5. Create a **deploy sandbox** project — see [deploy-sandbox.md](./deploy-sandbox.md) and run `.\scripts\setup-deploy-sandbox.ps1`
6. Set `ZEROPS_DEPLOY_PROJECT_ID` to the sandbox project (wizard deploys only)

## Manual Zerops spike (do once)
```bash
# Install zcli — see https://docs.zerops.io/references/zcli
zcli login
zcli project service-import zerops/import-deplot-services.yaml -P YOUR_PROJECT_ID
```

## Curated showcase repositories

| Repo | Stack | Demo use |
|------|-------|----------|
| [maannaan/Deplot](https://github.com/maannaan/Deplot) | Next.js + FastAPI monorepo | Dogfood — 5-service import (postgres, valkey, typesense, web, api) |
| [vercel/next.js](https://github.com/vercel/next.js) | Next.js (large) | Stack detection stress test — use subfolder or fork |
| Any Next.js + Prisma app | nextjs, postgres, search | Brownfield onboarding demo |

**Recommended live demo:** Paste `https://github.com/maannaan/Deplot` with Demo Mode **off**. Deplot generates slug-prefixed services in **`ZEROPS_DEPLOY_PROJECT_ID`** (sandbox), not the platform project.

See [differentiation-plan.md](./differentiation-plan.md) for the full roadmap vs Zeroth.

## Multi-service stack (real prototype)

Deplot provisions into your existing project:

| Service | Zerops type | Hostname pattern |
|---------|-------------|------------------|
| PostgreSQL | `postgresql@16` | `{slug}-postgres` |
| Valkey cache | `valkey@7` | `{slug}-cache` |
| Typesense search | `typesense@30` | `{slug}-search` |
| API | `python@3.12` / `nodejs@22` | `{slug}-api` |
| Web | `nodejs@22` | `{slug}-web` |

After import, **enable Zerops subdomain access** on `{slug}-web` and `{slug}-api` routing pages (502 otherwise).

## Deplot on Zerops
Deploy using files in `zerops/` and **`zerops.yaml` at repo root** (required for GitHub CI/CD):
- `zerops.yaml` — build config for **web** + **api** (must be at repository root)
- `import-deplot.yaml` — provisions postgres, valkey, api, web
- `import-deplot-services.yaml` — service shells for existing project

## Environment variables

```bash
ZEROPS_API_TOKEN=...
ZEROPS_PROJECT_ID=...          # Deplot platform (web, api, postgres)
ZEROPS_DEPLOY_PROJECT_ID=...   # Wizard deploy sandbox (real testing)
GEMINI_API_KEY=...          # Real AIOps diagnosis
GITHUB_TOKEN=...            # Optional — higher GitHub API rate limits
DATABASE_URL=postgresql://...  # Deplot persistence (postgres service)
```
