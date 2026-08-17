# Wizard field reference

Long-form explanations for the fields shown in the Deplot deploy wizard.
The UI copy is intentionally terse — this doc has the details.

## GitHub token (Connect step)

**Required for**: private repositories. Optional for public repos.

**Scopes needed**
- Classic PAT: `repo` (specifically `repo:read` / `contents:read`)
- Fine-grained PAT: **Contents: Read-only** on the target repo

**Storage**
- Never written to disk on the backend.
- Held in the analyze/deploy session object, which lives in the
  `deplot_sessions` Postgres table (payload JSONB) so sessions
  survive backend restarts.
- Also mounted transiently into the Kaniko build Job as an env var to
  clone private repos, then the Job's Secret is garbage-collected when
  the Job's `ttlSecondsAfterFinished` expires (1 hour).

If you don't want the token in Postgres, don't paste it — Deplot will
fall through to unauthenticated clone and 404 on private repos.

## Estimated monthly cost (Plan step)

The wizard shows a rough figure. Full formula, rate table, and
worked examples live in
[cost-and-build-estimates.md](./cost-and-build-estimates.md).

TL;DR:
- Sums each service's `cpu_cores × $25 + ram_gb × $3.50 + disk_gb × $0.15`
- Uses Azure D-series AKS shared-pool list prices.
- Excludes egress, load balancer hours, ACR storage, and any
  shared-cluster amortization Degreed gets from reservations.
- Uses the resource **requests** Deplot's own manifests declare — not
  what the workload actually consumes at runtime.

Treat it as **order-of-magnitude** guidance, not a bill.

## Runtime environment (Configure step)

**What it does**
- You paste `KEY=VALUE` lines.
- Deplot creates a Kubernetes `Secret` named `<slug>-runtime-env` in the
  deploy namespace.
- Every generated app `Deployment` gets `envFrom: [secretRef: <slug>-runtime-env]`
  on its container, so the keys appear as environment variables at
  runtime.
- Your app reads them the normal way — `os.getenv("FOO")` in Python,
  `process.env.FOO` in Node, `import.meta.env.VITE_FOO` for Vite builds
  that were compiled with the value present, etc.

**What Deplot injects itself** (don't put these in the textarea; they get
filtered out anyway)
- `DATABASE_URL`, `DATABASE_URL_SYNC`
- `REDIS_URL`
- `TYPESENSE_URL`, `TYPESENSE_HOST`, `TYPESENSE_PORT`, `TYPESENSE_PROTOCOL`, `TYPESENSE_API_KEY`
- `PORT`, `NODE_ENV`
- `NEXT_PUBLIC_API_URL`, `REACT_APP_API_URL`, `VITE_API_URL`, `BACKEND_URL`

**Auto-detected**
During the Analyze step, Deplot greps source files and any
`.env.example` for `os.getenv`, `process.env.*`, and `import.meta.env.*`
references. Detected keys appear as chips above the textarea and are
pre-populated — you fill in the values.

**What's NOT persisted**
- Values never go into application logs.
- Values never go into the `deplot_sessions` / `deplot_deployments`
  Postgres tables. They live in the wizard state (browser memory) and
  in the K8s `Secret` in the deploy namespace.
