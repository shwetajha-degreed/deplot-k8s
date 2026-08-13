# Deplot Differentiation Plan

**Goal:** Be clearly unique vs [Zeroth](https://web-2b21-8080.prg1.zerops.app/about.html) — not a second Pathfinder.

**Positioning:** Zeroth verifies configuration. Deplot is the AI platform engineer that **architects, deploys, watches, and heals** production on Zerops.

---

## Two Zerops projects (required)

| Project | Env var | Purpose |
|---------|---------|---------|
| **Deplot platform** | `ZEROPS_PROJECT_ID` | Hosts Deplot itself (web, api, postgres, cache) |
| **Deploy sandbox** | `ZEROPS_DEPLOY_PROJECT_ID` | `DrVB5HNbQXu3mAz3YchB8Q` (`deplot-deploy-sandbox`) |

Never import customer/showcase stacks into the platform project. See [deploy-sandbox.md](./deploy-sandbox.md).

---

## Phase 0 — Sandbox + safety (this week)

| # | Task | Files | Done when |
|---|------|-------|-----------|
| 0.1 | Separate deploy project config | `config.py`, `deploy.py`, `.env` | Wizard deploys target sandbox only |
| 0.2 | Setup script + import YAML | `zerops/import-deploy-sandbox.yaml`, `scripts/setup-deploy-sandbox.ps1` | One command creates sandbox project |
| 0.3 | Pass `project_id` through logs/metrics | `zerops.py`, `operations.py`, `aiops.py` | Observability reads sandbox services |
| 0.4 | Document real-test checklist | `docs/deploy-sandbox.md` | Team can run live demo without breaking Deplot |

---

## Phase 1 — Real self-heal (P0 differentiator)

Zeroth repairs **manifest before deploy**. Deplot repairs **running production**.

| # | Task | Files | Done when |
|---|------|-------|-----------|
| 1.1 | `apply_env_changes(service, env)` via zcli/REST | `zerops.py` | ✅ Env patch via service-import |
| 1.2 | Remediation flow: apply → redeploy → poll readiness | `aiops.py`, `operations.py` | ✅ Real + demo paths |
| 1.3 | Demo mode keeps simulated path | `aiops.py` | ✅ |
| 1.4 | Frontend: show remediation steps + diff | `incident-panel.tsx`, `page.tsx` | ✅ Timeline UI |
| 1.5 | E2E: demo heal + manual sandbox heal doc | `test_api_regression.py`, `deploy-sandbox.md` | ✅ API tests; manual sandbox checklist |

**Acceptance test (sandbox):**

1. Deploy showcase repo with Demo Mode **off**
2. Seed or trigger failure (missing env)
3. Diagnose → Apply fix
4. Verify env on Zerops GUI + service healthy + incident resolved

---

## Phase 2 — Living architecture (P1 visual differentiator)

| # | Task | Files | Done when |
|---|------|-------|-----------|
| 2.1 | Health from Zerops readiness + metrics, not incident flag | `operations.py` | ✅ Pipeline + logs + service info |
| 2.2 | Poll observability on Operate step | `page.tsx`, config interval | ✅ 30s poll on Operate + Incidents |
| 2.3 | Architecture step shows planned vs deployed hostnames | `architecture-graph.tsx` | ✅ Slug-prefixed hostnames on nodes |

---

## Phase 3 — Computed deployment score (P1 credibility)

| # | Task | Files | Done when |
|---|------|-------|-----------|
| 3.1 | Score from validation + incidents + observability gaps | `scoring.py`, `implementations.py` | ✅ Computed per deployment |
| 3.2 | Gemini score narrative when key set | `gemini.py` | ✅ Enhances recommendations |
| 3.3 | Score improves after successful remediation | `deploy.py` score endpoint | ✅ Reliability/overall delta in tests |

**Scoring inputs:**

- Validation warnings (−)
- Open incidents (−)
- Readiness failures (−)
- Routing checklist incomplete (−)
- All services healthy (+)
- Remediation succeeded (+)

---

## Phase 4 — Deploy experience (P2 polish)

| # | Task | Files | Done when |
|---|------|-------|-----------|
| 4.1 | SSE stream of build logs during Deploy | `deploy_stream.py`, `deploy.py`, `page.tsx` | ✅ Live log tail via EventSource |
| 4.2 | Ops timeline (deploy → incident → heal → score) | `timeline.py`, `ops-timeline.tsx` | ✅ Persisted + replay UI |
| 4.3 | LLM stack analysis (optional) | `gemini.py`, `domain.py`, `implementations.py` | ✅ When GEMINI_API_KEY set |

---

## Demo script (3 minutes)

1. **Connect** — `https://github.com/maannaan/Deplot` (or showcase repo)
2. **Architecture** — 5 nodes (web, api, postgres, valkey, typesense)
3. **Plan** — cost + build estimate
4. **Deploy** — sandbox project, show URLs + routing checklist
5. **Operate** — live metrics on graph
6. **Incidents** — diagnose → **Apply fix** (real on sandbox)
7. **Score** — computed readiness

**Say:** “We operate production on Zerops.”  
**Don’t say:** “We verify deployments.”

---

## What we intentionally skip (Zeroth’s lane)

- Public “verified runs” gallery
- Facts-only analysis privacy story as primary pitch
- Pre-deploy Pathfinder as hero feature

---

## Success metrics

| Metric | Target |
|--------|--------|
| Real sandbox deploy | 5 services visible in Zerops GUI |
| Self-heal | One incident resolved via real env + redeploy |
| Score | Computed from deployment state, not static |
| Demo | 3-min video with sandbox deploy + heal |
| Isolation | Platform project unchanged after test deploys |
