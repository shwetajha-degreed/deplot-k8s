# Cost & Build Time Estimates

Reference for how Deplot's **Plan** step computes the "Est. monthly cost" and
"Build time" tiles the user sees before deploying.

**TL;DR** — both numbers come from
[`PlannerService.build_plan`](../backend/app/services/domain.py) using fixed
per-workload resource shapes multiplied by Azure D-series list rates. They're
ballpark, not billing-grade.

---

## Cost model

### Formula

```
service_cost_usd_month =
      cpu_cores    × $25.00 / core-month     (CPU_USD_PER_CORE_MONTH)
    + ram_gb       × $3.50  / GB-month       (RAM_USD_PER_GB_MONTH)
    + disk_gb      × $0.15  / GB-month       (DISK_USD_PER_GB_MONTH)

plan_cost_usd_month = Σ (service_cost) over every node in the architecture graph
```

Rates live at the top of `PlannerService` in
[`backend/app/services/domain.py`](../backend/app/services/domain.py) as class
attributes.

### Where the rates come from

Azure public list price, AKS Standard_D-series (shared CPU) node pool, US
regions. Approximate values as of pricing snapshot:

| Resource | Hourly | × 730 hr / mo | Deplot rate |
|---|---|---|---|
| CPU (1 vCPU on D-series) | ~$0.034 / hr | ~$24.82 | **$25.00 / core-mo** |
| RAM (1 GB) | ~$0.005 / hr | ~$3.50 | **$3.50 / GB-mo** |
| Managed Disk (Premium SSD) | – | – | **$0.15 / GB-mo** |

Source pattern: sum of "shared-CPU per-core" and "per-GB memory" line items on
the AKS pricing page. Round to convenient numbers.

**When to update:** if Azure changes list prices materially (>10%) or Degreed
switches to a different node SKU / reserved instances. Just edit the three
class attributes; no other code changes required.

### Per-workload shapes

Each `WORKLOAD_SHAPES` entry mirrors the resource **requests** actually
declared by Deplot's manifests + dep provisioners. When those change, update
the shapes too.

| Service type | CPU | RAM | Disk | Where it's declared |
|---|---|---|---|---|
| `api` / `frontend` / `web` | 0.1 | 128 Mi | 0 | Fallback Dockerfile Deployment in [`deploy.py`](../backend/app/api/v1/deploy.py) |
| `database` (Postgres) | 0.5 | 512 Mi | 5 Gi | CNPG `Cluster` in [`services/deps/postgres.py`](../backend/app/services/deps/postgres.py) |
| `cache` (Redis) | 0.05 | 64 Mi | 1 Gi | [`services/deps/redis.py`](../backend/app/services/deps/redis.py) |
| `search` (Typesense) | 0.1 | 256 Mi | 2 Gi | [`services/deps/typesense.py`](../backend/app/services/deps/typesense.py) |

Unknown types default to the `api` shape.

### Worked examples

**dev-velocity** — Next.js frontend + FastAPI api + Postgres:

```
api        0.10 CPU × $25   =  $2.50
           0.125 GB × $3.50 =  $0.44
                             --------
                              $2.94/mo
frontend   0.10 CPU × $25   =  $2.50
           0.125 GB × $3.50 =  $0.44
                             --------
                              $2.94/mo
database   0.50 CPU × $25   = $12.50
           0.50 GB  × $3.50 =  $1.75
           5.0 GB   × $0.15 =  $0.75
                             --------
                             $15.00/mo
                             --------
                             $20.88/mo total
```

**Showcase** — same + Redis + Typesense: **~$26/mo**.

**Static frontend only**: **~$3/mo**.

### Caveats when explaining

- **List price, not what Degreed actually pays.** Reserved instances,
  Enterprise Agreements, autoscaling, and shared-cluster amortization all
  reduce real spend.
- **Excludes**: egress bandwidth, Load Balancer hours, cross-region traffic,
  ACR storage, container image pulls, Datadog/observability overhead. In an
  internal sandbox those approach zero; for a prod deploy they don't.
- **Static shapes.** If someone patches the manifests to request 4 CPU
  instead of 100 m, the plan won't reflect it — the estimate uses the shapes
  Deplot's fallback manifests declare, not what actually got applied.
- **Deploy namespaces are not billing-isolated.** The estimate approximates
  what one workload's worth of resources costs at Azure's rates; the
  cluster itself is a shared fixed spend.

**One-liner for stakeholders:** *"It's Azure's list price for the CPU +
RAM + disk we ask for. Actual Degreed spend is lower (reservations,
shared node pool), but this tells you the marginal cost of one more
deploy in the right order of magnitude."*

---

## Build time model

Simple, based on empirically observed Kaniko durations against
`dgscucorecr01.azurecr.io` from this cluster.

### Formula

```
buildable_count = number of services in the graph whose type is api / frontend / web
                  (CNPG Postgres, Redis, Typesense pull prebuilt images — no build)

if buildable_count == 0:  build_time = 0 min
if buildable_count >= 1:  build_time = 4 min
if buildable_count  > 2:  build_time += (buildable_count - 2)  # +1 min per extra
```

### Where the 4 min comes from

Observed on `DGCUSUSSBXAKS01` during this project's smoke tests:

| Scenario | Wall clock |
|---|---|
| Cache hit (same repo + git ref) | ~1.5 min |
| Cold Kaniko build of a FastAPI backend | ~3 min |
| Cold Kaniko build of a Next.js frontend (npm install + build) | ~5 min |
| API + frontend in parallel (dev-velocity, both cold) | ~4 min (max of the two) |

Kaniko builds run as parallel K8s Jobs in `deplot-builds`, so wall clock
is `max(build_i)`, not `sum`. **4 min** hits the middle for a two-service
build with one cache-warm and one cold layer.

### Why the +1 per extra beyond 2

The `deplot-builds` namespace has a **ResourceQuota** (8 CPU / 12 Gi total).
Each Kaniko build requests 2 Gi + 500 m CPU. Two builds fit comfortably;
three or four start queueing on quota, so wall clock grows roughly
linearly with each additional service.

### Examples

| Repo | Buildable services | Est. build time |
|---|---|---|
| Static frontend only | frontend | 4 min |
| dev-velocity | api + frontend | 4 min (parallel) |
| Showcase | api + frontend | 4 min (parallel) |
| Monorepo with api + frontend + worker | 3 services | 5 min |

### Caveats

- **Cache-cold builds go longer.** First-ever deploy of a repo means base
  image pulls + full `npm install`. Kaniko caches to
  `dgscucorecr01.azurecr.io/{slug}-{svc}/cache` so subsequent deploys of
  the same repo are 60–90 s.
- **Datadog init containers add ~30 s** per pod on startup (they inject
  before the build container runs). Included in the 4 min baseline.
- **This is build time only.** Not the same as "time to reachable URL,"
  which also includes deps provisioning (Postgres ~90 s, Redis ~30 s),
  manifest apply, DNS propagation (~2–3 min via ExternalDNS), and pod
  readiness. Total deploy wall clock is typically **build + 3–5 min**.

**One-liner for stakeholders:** *"Kaniko builds each service in parallel;
each cold build is 3–5 minutes and cache hits are ~90 seconds. Whole
end-to-end wall clock, first deploy, is roughly 5–8 minutes."*

---

## When these estimates are wrong

- **First deploy of a huge repo** — the 4 min baseline is a Node/Python
  ballpark. A Rust or Java build might legitimately take 15+ min. Not
  handled today; would need language-aware baselines.
- **Custom Dockerfile with many build stages** — same issue.
- **Larger-than-default resource requests** in the repo's committed
  Dockerfile or Deplot's yaml_generator prompt output.
- **Cluster under load** — quota queueing pushes builds later; the
  estimate doesn't know about cluster state.

If someone asks "why did the actual cost/build differ from the estimate,"
one of these is almost always why.
