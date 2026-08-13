# Deploy sandbox — separate Zerops project for real testing

Deplot runs on one Zerops project. **All wizard deploys** (showcase repos, heal-loop tests) go to a **second project** so you never pollute or break the platform stack.

## Quick setup

### 1. Create the sandbox project

From repo root (requires `zcli login` and `ZEROPS_API_TOKEN` in `.env`):

```powershell
.\scripts\setup-deploy-sandbox.ps1
```

This runs:

```bash
zcli project project-import zerops/import-deploy-sandbox.yaml
```

Copy the printed **project ID** into `.env`:

```bash
ZEROPS_DEPLOY_PROJECT_ID=<sandbox-project-id>
```

Keep `ZEROPS_PROJECT_ID` as your **Deplot platform** project (where web/api/postgres live).

### 2. Verify configuration

```bash
curl http://localhost:8000/api/v1/health
```

Response includes:

```json
{
  "zerops": {
    "platform_project_configured": true,
    "deploy_project_configured": true,
    "deploy_project_isolated": true
  }
}
```

`deploy_project_isolated` is `true` when deploy project ≠ platform project (recommended).

### 3. Run a real test deploy

1. Start backend + frontend locally
2. Open wizard — **Demo Mode OFF**
3. Paste showcase repo: `https://github.com/maannaan/Deplot`
4. Walk through Analyze → Configure → **Deploy**
5. In Zerops GUI, open **deploy sandbox** project (not Deplot platform)
6. Confirm services: `{slug}-postgres`, `{slug}-cache`, `{slug}-search`, `{slug}-api`, `{slug}-web`
7. Enable subdomain access on `{slug}-web` and `{slug}-api` (routing pages)

### 4. Clean up test services (optional)

After demos, remove slug-prefixed services from the sandbox in Zerops GUI, or delete/recreate the sandbox project.

---

## Environment variables

| Variable | Example | Purpose |
|----------|---------|---------|
| `ZEROPS_API_TOKEN` | `...` | Same token for both projects (your account) |
| `ZEROPS_PROJECT_ID` | `bgrAmsBNTp...` | Deplot platform (web, api, db) |
| `ZEROPS_DEPLOY_PROJECT_ID` | `abc123...` | Wizard deploy target only |

If `ZEROPS_DEPLOY_PROJECT_ID` is unset, deploys fall back to `ZEROPS_PROJECT_ID` (not recommended for production demos).

---

## Manual import (alternative)

```bash
zcli login
zcli project project-import zerops/import-deploy-sandbox.yaml
# Note project ID from: zcli project list
```

---

## Real-test checklist

Use before recording demo video or judging:

- [ ] `ZEROPS_DEPLOY_PROJECT_ID` set and ≠ platform project
- [ ] `/api/v1/health` shows `deploy_project_isolated: true`
- [ ] Demo Mode **off** in wizard sidebar
- [ ] Deploy creates services in **sandbox** project only
- [ ] Subdomain access enabled on web + api
- [ ] Operate step shows logs/metrics from sandbox hostnames
- [ ] (Phase 1) Apply fix updates env on sandbox + redeploys — use Incidents → **Apply AI Fix & Redeploy** (Demo Mode off)

See [differentiation-plan.md](./differentiation-plan.md) for Phase 1–4 implementation roadmap.
