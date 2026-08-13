# Deplot AI — Agent Instructions

**Deplot** is an autonomous platform engineer: GitHub repo → AI analysis → architecture → zerops.yaml → deploy → observe → AIOps → self-heal.

## Repo layout

```
backend/app/     # FastAPI — registry-based services & agents
frontend/src/    # Next.js — config-driven wizard steps
prompts/         # Agent prompts
templates/zerops/
zerops/          # Deplot's own Zerops configs
```

See [README.md](README.md) for quick start.

## When Implementing

1. Read `.cursor/rules/` — core guardrails always apply
2. Add agents via `@register_agent`, services via `bootstrap.py`
3. Add wizard steps in `frontend/src/config/wizard-steps.ts`
4. Match demo flow: repo → stack → architecture → yaml → deploy → operate → incidents → score
