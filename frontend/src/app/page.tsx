"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import {
  ArchitectureGraphView,
  DEMO_ARCHITECTURE,
  type ArchEdge,
  type ArchNode,
} from "@/components/wizard/architecture-graph";
import { IncidentPanel, type IncidentData } from "@/components/wizard/incident-panel";
import { OpsTimeline, type OpsTimelineEvent } from "@/components/wizard/ops-timeline";
import { PreviewBanner, ScoreRing, StatCard, StepPanel } from "@/components/wizard/step-panel";
import { WIZARD_STEPS, getStepIndex, type WizardStepId } from "@/config/wizard-steps";
import { api, deploymentStreamUrl, normalizeRepoUrl } from "@/lib/api";

type Stack = Record<string, unknown> | null;

const DEPLOY_STAGES = [
  "Building",
  "Installing dependencies",
  "Uploading artifacts",
  "Creating runtime",
  "Provisioning database",
  "Running readiness check",
  "Deployment complete",
];

const DEMO_STACK = {
  framework: "nextjs",
  runtime: "nodejs@22",
  database: "postgresql",
  cache: "valkey",
  search: "typesense",
};

const DEMO_PLAN = {
  estimated_cost_usd_month: 12.68,
  estimated_build_minutes: 15,
  services: [{ name: "frontend" }, { name: "api" }, { name: "database" }, { name: "cache" }, { name: "search" }],
  pricing_source: "k8s_estimated",
  pricing_note:
    "Baseline single-replica resource requests on AKS shared node pool. Actual spend varies with autoscaling and per-namespace usage.",
};

const DEMO_YAML = {
  import: `# Preview — Namespace scaffolding\napiVersion: v1\nkind: Namespace\nmetadata:\n  name: deploy-demo\n  labels:\n    app.kubernetes.io/part-of: demo-app`,
  workloads: `# Preview — Deployment\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n  namespace: deploy-demo\nspec:\n  replicas: 1\n  template:\n    spec:\n      containers:\n        - name: api\n          image: dgscucorecr01.azurecr.io/demo-api:latest\n          ports: [{containerPort: 8000}]`,
};

const DEMO_SCORE = {
  security: 9.2,
  performance: 8.7,
  scalability: 8.9,
  reliability: 9.4,
  observability: 7.8,
  overall: 8.8,
  recommendations: [
    "Attach HTTPRoute for web and api to the internal gateway after apply",
    "Verify Typesense and Valkey hostnames in API env",
  ],
};

const OBSERVABILITY_POLL_MS = 30_000;

const DEMO_INCIDENT: IncidentData = {
  title: "Backend cannot start — migration failed",
  severity: "critical",
  status: "diagnosed",
  diagnosis: {
    root_cause: "Prisma migration failed",
    reason: "DATABASE_URL environment variable is missing",
    impact: "Backend cannot connect to PostgreSQL",
    confidence: 0.96,
    suggested_fix: "Set DATABASE_URL on the api Deployment env or via a Secret",
    log_summary: "Error: P1001 — Can't reach database server at postgres:5432",
  },
  runbook: [
    "kubectl edit deployment/api -n deploy-{slug}  →  spec.template.spec.containers[0].env",
    "Add DATABASE_URL referencing the postgres service",
    "Redeploy the api service and wait for readiness check",
  ],
  suggested_remediation: {
    description: "Add DATABASE_URL to api service env",
    env_changes: { DATABASE_URL: "postgresql://user:pass@postgres:5432/app" },
    yaml_diff: "+ envVariables:\n+   DATABASE_URL: ${postgres_hostname}",
  },
};

export default function HomePage() {
  const [step, setStep] = useState<WizardStepId>("connect");
  const [demoMode, setDemoMode] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [stack, setStack] = useState<Stack>(null);
  const [yaml, setYaml] = useState<{ workloads: string; import: string } | null>(null);
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [incidents, setIncidents] = useState<IncidentData[]>([]);
  const [architecture, setArchitecture] = useState<{ nodes: ArchNode[]; edges: ArchEdge[] } | null>(
    null,
  );
  const [observability, setObservability] = useState<Record<string, unknown> | null>(null);
  const [healed, setHealed] = useState(false);
  const [remediating, setRemediating] = useState(false);
  const [score, setScore] = useState<{
    security: number;
    performance: number;
    scalability: number;
    reliability: number;
    observability: number;
    overall?: number;
    recommendations?: string[];
  } | null>(null);
  const [validation, setValidation] = useState<{
    passed: boolean;
    issues: { severity: string; code: string; message: string; field?: string }[];
  } | null>(null);
  const [deployStatus, setDeployStatus] = useState<{
    live_url?: string;
    service_urls?: Record<string, string>;
    routing_checklist?: string[];
    pipeline_state?: string;
    status?: string;
    failure_phase?: string;
    failure_summary?: string;
    retry_from?: string;
    deploy_ui_stage_index?: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deployStage, setDeployStage] = useState(0);
  const [deployFailed, setDeployFailed] = useState(false);
  const [deployLogs, setDeployLogs] = useState<string[]>([]);
  const [maxReachedIndex, setMaxReachedIndex] = useState(0);

  const advanceToStep = useCallback((id: WizardStepId) => {
    const idx = getStepIndex(id);
    setMaxReachedIndex((prev) => Math.max(prev, idx));
    setStep(id);
  }, []);

  const unlockWatchAndHeal = useCallback(() => {
    setMaxReachedIndex((prev) => Math.max(prev, getStepIndex("incidents")));
  }, []);

  const goToStep = useCallback((id: WizardStepId) => {
    setStep(id);
  }, []);

  const isPreviewStep = getStepIndex(step) > maxReachedIndex;

  const runAnalyze = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cleaned = demoMode ? null : (repoUrl ? normalizeRepoUrl(repoUrl) : null);
      if (cleaned) setRepoUrl(cleaned);
      const token = githubToken.trim() || undefined;
      const res = await api.analyze(cleaned, demoMode, token);
      setSessionId(res.session_id);
      setStack(res.stack);
      advanceToStep("analyze");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analyze failed");
    } finally {
      setLoading(false);
    }
  }, [demoMode, repoUrl, githubToken, advanceToStep]);

  const loadArchitecture = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const graph = await api.architecture(sessionId);
      setArchitecture({
        nodes: graph.nodes as ArchNode[],
        edges: graph.edges as ArchEdge[],
      });
      advanceToStep("architecture");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Architecture failed");
    } finally {
      setLoading(false);
    }
  }, [sessionId, advanceToStep]);

  const loadObservability = useCallback(async () => {
    if (!deploymentId) return;
    try {
      const snap = await api.getObservability(deploymentId);
      setObservability(snap);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Observability failed");
    }
  }, [deploymentId]);

  useEffect(() => {
    if (!deploymentId || isPreviewStep) return;
    if (step !== "operate" && step !== "incidents") return;

    void loadObservability();
    const timer = setInterval(() => void loadObservability(), OBSERVABILITY_POLL_MS);
    return () => clearInterval(timer);
  }, [step, deploymentId, isPreviewStep, loadObservability]);

  const applyFix = useCallback(async () => {
    const open = incidents.find((i) => i.status !== "resolved" && i.id);
    if (!open?.id || !deploymentId) return;
    setRemediating(true);
    setError(null);
    try {
      const updated = (await api.remediateIncident(String(open.id))) as IncidentData;
      setIncidents((prev) =>
        prev.map((inc) => (inc.id === updated.id ? { ...inc, ...updated } : inc)),
      );
      if (updated.status === "resolved") {
        setHealed(true);
        await loadObservability();
      } else if (updated.remediation_error) {
        setError(updated.remediation_error);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Remediation failed");
    } finally {
      setRemediating(false);
    }
  }, [incidents, deploymentId, loadObservability]);

  const healthMap = useMemo(() => {
    const health = observability?.health as
      | { service: string; status: string; readiness_ok?: boolean }[]
      | undefined;
    if (health?.length) {
      return Object.fromEntries(health.map((h) => [h.service, h.status]));
    }
    if (healed) {
      return {
        frontend: "healthy",
        api: "healthy",
        database: "healthy",
        cache: "healthy",
        search: "healthy",
      };
    }
    const hasOpen = incidents.some((i) => i.status !== "resolved");
    if (hasOpen) {
      return {
        frontend: "healthy",
        api: "critical",
        database: "degraded",
        cache: "healthy",
        search: "degraded",
      };
    }
    return {};
  }, [observability, incidents, healed]);

  const observabilityCheckedAt =
    typeof observability?.checked_at === "string" ? observability.checked_at : null;

  const loadPlan = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      setPlan(await api.getPlan(sessionId));
      advanceToStep("plan");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Plan failed");
    } finally {
      setLoading(false);
    }
  }, [sessionId, advanceToStep]);

  const loadYaml = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.generateYaml(sessionId);
      // Backend returns K8sConfig { manifests, namespace, services }. Render
      // the namespace/services summary as the "import" pane and pretty-print
      // the manifest list as the "workloads" pane. Full YAML rendering is a
      // future improvement; JSON preview keeps the UX honest for now.
      const services = data.services ?? [];
      const importPreview =
        `# Namespace scaffolding\nnamespace: ${data.namespace}\n` +
        (services.length
          ? `services:\n${services.map((s) => `  - ${s}`).join("\n")}\n`
          : "");
      const workloadsPreview =
        (data.manifests ?? [])
          .map((m) => JSON.stringify(m, null, 2))
          .join("\n---\n") || "# no manifests generated";
      setYaml({ workloads: workloadsPreview, import: importPreview });
      const report = await api.validateConfig(sessionId);
      setValidation(report);
      advanceToStep("configure");
    } catch (e) {
      setError(e instanceof Error ? e.message : "YAML generation failed");
    } finally {
      setLoading(false);
    }
  }, [sessionId, advanceToStep]);

  const applyDeploymentOutcome = useCallback(
    async (id: string) => {
      let finalStatus: typeof deployStatus = null;

      if (demoMode) {
        unlockWatchAndHeal();
        setDeployStage(DEPLOY_STAGES.length - 1);
        setIncidents((await api.listIncidents(id)) as IncidentData[]);
        await loadObservability();
        return null;
      }

      // Poll for up to ~12 min at 3s intervals. Covers:
      //   builds (~2m cached, ~5m fresh) + deps provision (~2m) +
      //   K8s apply + heal-loop 60s stable hold before SUCCEEDED.
      for (let attempt = 0; attempt < 240; attempt++) {
        const st = await api.getDeploymentStatus(id);
        setDeployStatus(st);
        finalStatus = st;
        if (st.status === "succeeded" || st.status === "failed") break;
        await new Promise((r) => setTimeout(r, 3000));
      }

      const failed = finalStatus?.status === "failed";
      setDeployFailed(failed);
      if (failed) {
        const failedIndex =
          typeof finalStatus?.deploy_ui_stage_index === "number"
            ? finalStatus.deploy_ui_stage_index
            : DEPLOY_STAGES.length - 2;
        setDeployStage(failedIndex);
        unlockWatchAndHeal();
      } else {
        setDeployStage(DEPLOY_STAGES.length - 1);
        unlockWatchAndHeal();
      }

      setIncidents((await api.listIncidents(id)) as IncidentData[]);
      await loadObservability();
      return finalStatus;
    },
    [demoMode, loadObservability, unlockWatchAndHeal],
  );

  const watchDeploymentStream = useCallback(
    (id: string) =>
      new Promise<void>((resolve) => {
        const es = new EventSource(deploymentStreamUrl(id));
        const finish = () => {
          es.close();
          resolve();
        };
        es.addEventListener("log", (ev) => {
          try {
            const data = JSON.parse(ev.data) as { line?: string };
            if (data.line) {
              setDeployLogs((prev) => [...prev.slice(-100), data.line as string]);
              setDeployStage((s) => Math.min(s + 1, DEPLOY_STAGES.length - 2));
            }
          } catch {
            /* ignore malformed SSE */
          }
        });
        es.addEventListener("status", (ev) => {
          try {
            const data = JSON.parse(ev.data) as {
              status?: string;
              pipeline_state?: string;
              stage?: string;
            };
            setDeployStatus((prev) => ({ ...prev, ...data }));
            if (data.status === "failed") {
              setDeployFailed(true);
            }
          } catch {
            /* ignore */
          }
        });
        es.addEventListener("done", (ev) => {
          try {
            const data = JSON.parse(ev.data) as { status?: string };
            if (data.status !== "failed") {
              setDeployStage(DEPLOY_STAGES.length - 1);
            }
          } catch {
            /* ignore */
          }
          finish();
        });
        es.addEventListener("end", finish);
        es.onerror = finish;
      }),
    [],
  );

  const runDeploy = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    setHealed(false);
    setDeployStatus(null);
    setDeployLogs([]);
    setDeployFailed(false);
    advanceToStep("deploy");
    setDeployStage(0);
    try {
      const res = await api.deploy(sessionId, demoMode);
      setDeploymentId(res.deployment_id);
      await watchDeploymentStream(res.deployment_id);
      await applyDeploymentOutcome(res.deployment_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deploy failed");
    } finally {
      setLoading(false);
    }
  }, [sessionId, demoMode, advanceToStep, watchDeploymentStream, applyDeploymentOutcome]);

  const retryFromPhase = useCallback(
    async (fromPhase: "import" | "pipeline") => {
      if (!deploymentId) return;
      setLoading(true);
      setError(null);
      setDeployFailed(false);
      setDeployLogs([]);
      setDeployStage(0);
      try {
        await api.retryDeploy(deploymentId, fromPhase);
        await watchDeploymentStream(deploymentId);
        await applyDeploymentOutcome(deploymentId);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Retry failed");
      } finally {
        setLoading(false);
      }
    },
    [deploymentId, watchDeploymentStream, applyDeploymentOutcome],
  );

  const loadScore = useCallback(async () => {
    if (!deploymentId) return;
    setLoading(true);
    try {
      setScore(await api.getScore(deploymentId));
      await loadObservability();
      advanceToStep("score");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Score failed");
    } finally {
      setLoading(false);
    }
  }, [deploymentId, advanceToStep, loadObservability]);

  const activeArchitecture =
    architecture ?? (isPreviewStep && step === "architecture" ? DEMO_ARCHITECTURE : null);
  const activeStack = stack ?? (isPreviewStep && step === "analyze" ? DEMO_STACK : null);
  const activePlan = plan ?? (isPreviewStep && step === "plan" ? DEMO_PLAN : null);
  const activeYaml = yaml ?? (isPreviewStep && step === "configure" ? DEMO_YAML : null);
  const activeScore = score ?? (isPreviewStep && step === "score" ? DEMO_SCORE : null);
  const timelineEvents = (Array.isArray(observability?.timeline)
    ? observability.timeline
    : []) as OpsTimelineEvent[];

  const stackFields = activeStack
    ? [
        { label: "Framework", value: String(activeStack.framework ?? "—"), icon: "⚡" },
        { label: "Runtime", value: String(activeStack.runtime ?? "—"), icon: "🟢" },
        { label: "Database", value: String(activeStack.database ?? "—"), icon: "🗄️" },
        { label: "Cache", value: String(activeStack.cache ?? "None"), icon: "⚡" },
      ]
    : [];

  const analysisSummary =
    activeStack &&
    typeof (activeStack as Record<string, unknown>).analysis_summary === "string"
      ? ((activeStack as Record<string, unknown>).analysis_summary as string)
      : null;

  return (
    <AppShell
      view="wizard"
      step={step}
      maxReachedIndex={maxReachedIndex}
      demoMode={demoMode}
      onStepChange={goToStep}
      onDemoToggle={setDemoMode}
    >
      <div className="pointer-events-none absolute inset-0 grid-bg opacity-30" />
      <header className="relative border-b border-white/[0.06] bg-black/10 px-8 py-4 backdrop-blur-md">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-widest text-zinc-500">
                {WIZARD_STEPS.find((s) => s.id === step)?.description}
              </p>
            </div>
            <Badge tone={demoMode ? "accent" : "default"}>
              {demoMode ? "Demo active" : "Live repo"}
            </Badge>
          </div>
        </header>

        <div className="relative min-h-0 flex-1 overflow-y-auto p-8">
          {error && (
            <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          <AnimatePresence mode="wait" initial={false}>
            {step === "connect" && (
              <StepPanel
                key="connect"
                title="Connect your repository"
                subtitle="Paste a GitHub URL or use Demo Mode to explore the full platform engineering flow."
                badge="Platform Engineering"
              >
                <Card className="gradient-border max-w-2xl">
                  <div className="flex flex-col gap-4 sm:flex-row">
                    <input
                      className="flex-1 rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-white placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:opacity-40"
                      placeholder="https://github.com/org/repo"
                      value={repoUrl}
                      onChange={(e) => setRepoUrl(e.target.value)}
                      disabled={demoMode}
                    />
                    <Button onClick={runAnalyze} loading={loading} className="shrink-0">
                      Analyze Repository
                    </Button>
                  </div>
                  <div className="mt-4">
                    <label className="text-xs uppercase tracking-wider text-zinc-500">
                      GitHub token (optional — required for private repos)
                    </label>
                    <input
                      type="password"
                      className="mt-2 w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-white placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:opacity-40"
                      placeholder="ghp_… or github_pat_…"
                      value={githubToken}
                      onChange={(e) => setGithubToken(e.target.value)}
                      disabled={demoMode}
                      autoComplete="off"
                    />
                    <p className="mt-2 text-xs text-zinc-500">
                      Needs <code>repo:read</code> (or <code>contents:read</code> for a fine-grained
                      token). Not stored — persists only in memory for this deploy.
                    </p>
                  </div>
                  {demoMode && (
                    <p className="mt-4 text-xs text-zinc-500">
                      Demo Mode uses a sample Next.js + Prisma stack — no GitHub required.
                    </p>
                  )}
                </Card>
              </StepPanel>
            )}

            {step === "analyze" && activeStack && (
              <StepPanel
                key="analyze"
                title="Stack detected"
                subtitle="AI identified your application stack and infrastructure requirements."
                badge="Repository Intelligence"
              >
                {isPreviewStep && <PreviewBanner />}
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  {stackFields.map((f, i) => (
                    <StatCard key={f.label} {...f} delay={i * 0.08} />
                  ))}
                </div>
                {analysisSummary && (
                  <Card className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      AI analysis
                    </p>
                    <p className="mt-2 text-sm text-zinc-300">{analysisSummary}</p>
                  </Card>
                )}
                <div className="mt-6 flex gap-3">
                  <Button onClick={loadArchitecture} loading={loading} disabled={isPreviewStep}>
                    View Architecture
                  </Button>
                </div>
              </StepPanel>
            )}

            {step === "architecture" && activeArchitecture && (
              <StepPanel
                key="architecture"
                title="Infrastructure architecture"
                subtitle="Proposed multi-service topology for cluster-internal networking."
                badge="Architecture Builder"
              >
                {isPreviewStep && <PreviewBanner />}
                <Card className="overflow-hidden p-2">
                  <ArchitectureGraphView
                    nodes={activeArchitecture.nodes}
                    edges={activeArchitecture.edges}
                    healthOverrides={healthMap}
                  />
                </Card>
                <div className="mt-6">
                  <Button onClick={loadPlan} loading={loading} disabled={isPreviewStep}>
                    Deployment Plan
                  </Button>
                </div>
              </StepPanel>
            )}

            {step === "plan" && activePlan && (
              <StepPanel
                key="plan"
                title="Deployment plan"
                subtitle="Estimated resources, cost, and build time before you deploy."
                badge="Deployment Planner"
              >
                {isPreviewStep && <PreviewBanner />}
                <div className="grid gap-4 sm:grid-cols-3">
                  <StatCard
                    label="Est. monthly cost"
                    value={`$${activePlan.estimated_cost_usd_month ?? "—"}`}
                    icon="💰"
                  />
                  <StatCard
                    label="Build time"
                    value={`${activePlan.estimated_build_minutes ?? "—"} min`}
                    icon="⏱️"
                  />
                  <StatCard
                    label="Services"
                    value={String((activePlan.services as unknown[])?.length ?? 0)}
                    icon="📦"
                  />
                </div>
                {"pricing_note" in activePlan && activePlan.pricing_note ? (
                  <p className="mt-4 text-xs text-zinc-500">{String(activePlan.pricing_note)}</p>
                ) : null}
                <div className="mt-6">
                  <Button onClick={loadYaml} loading={loading} disabled={isPreviewStep}>
                    Generate K8s Manifests
                  </Button>
                </div>
              </StepPanel>
            )}

            {step === "configure" && activeYaml && (
              <StepPanel
                key="configure"
                title="Kubernetes manifests"
                subtitle="Deployment + Service + HTTPRoute generated from your repository analysis."
                badge="K8s Native"
              >
                {isPreviewStep && <PreviewBanner />}
                <div className="grid gap-4 lg:grid-cols-2">
                  <YamlPreview title="namespace.yaml" content={activeYaml.import} />
                  <YamlPreview title="workloads.yaml" content={activeYaml.workloads} />
                </div>
                {validation && !isPreviewStep && (
                  <Card className="mt-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                        Pre-deploy validation
                      </p>
                      <Badge tone={validation.passed ? "success" : "warning"}>
                        {validation.passed ? "Passed" : "Warnings"}
                      </Badge>
                    </div>
                    <ul className="mt-3 space-y-2">
                      {validation.issues.map((issue, i) => (
                        <li key={i} className="flex gap-2 text-sm text-zinc-300">
                          <Badge tone={issue.severity === "error" ? "critical" : "warning"}>
                            {issue.code}
                          </Badge>
                          <span>{issue.message}</span>
                        </li>
                      ))}
                    </ul>
                    {!validation.passed && (
                      <p className="mt-3 text-xs text-amber-400/90">
                        Fix blockers before production deploy. Demo Mode will simulate the failure
                        scenario for the AIOps loop.
                      </p>
                    )}
                  </Card>
                )}
                <div className="mt-6">
                  <Button onClick={runDeploy} loading={loading} disabled={isPreviewStep}>
                    Deploy to Kubernetes
                  </Button>
                </div>
              </StepPanel>
            )}

            {step === "deploy" && (
              <StepPanel
                key="deploy"
                title="Deploying to Kubernetes"
                subtitle="Real-time pipeline status from build to readiness check."
                badge="Deployment Engine"
              >
                {isPreviewStep && <PreviewBanner />}
                <Card>
                  <ul className="space-y-3">
                    {DEPLOY_STAGES.map((s, i) => {
                      const failedHere = deployFailed && i === deployStage;
                      const completed = !deployFailed && i < deployStage;
                      const active = !deployFailed && i === deployStage && loading;
                      const failedComplete = deployFailed && i < deployStage;
                      return (
                      <motion.li
                        key={s}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}
                        className="flex items-center gap-3"
                      >
                        <span
                          className={
                            failedHere
                              ? "text-red-400"
                              : completed || failedComplete
                              ? "text-emerald-400"
                              : active
                                ? "text-indigo-400"
                                : "text-zinc-600"
                          }
                        >
                          {failedHere ? "✕" : completed || failedComplete ? "✓" : active ? "●" : "○"}
                        </span>
                        <span
                          className={
                            failedHere
                              ? "text-red-300"
                              : i <= deployStage
                                ? "text-zinc-200"
                                : "text-zinc-600"
                          }
                        >
                          {s}
                          {failedHere && (
                            <span className="ml-2 text-xs text-red-400/90">failed here</span>
                          )}
                        </span>
                        {active && (
                          <span className="h-1 flex-1 overflow-hidden rounded-full bg-white/5">
                            <motion.span
                              className="block h-full w-1/3 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 shimmer"
                              animate={{ x: ["-100%", "400%"] }}
                              transition={{ repeat: Infinity, duration: 1.5 }}
                            />
                          </span>
                        )}
                      </motion.li>
                      );
                    })}
                  </ul>
                </Card>
                {deployLogs.length > 0 && (
                  <Card className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      Live build log (SSE)
                    </p>
                    <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-black/40 p-3 font-mono text-xs text-zinc-400">
                      {deployLogs.join("\n")}
                    </pre>
                  </Card>
                )}
                {deployFailed && deployStatus && (
                  <Card className="mt-4 border-red-500/30">
                    <p className="text-xs font-medium uppercase tracking-wider text-red-400">
                      Deployment failed — AI diagnosis
                    </p>
                    <p className="mt-2 text-sm text-zinc-200">
                      {deployStatus.failure_summary ??
                        "Kubernetes apply or pipeline failed. Review the log below."}
                    </p>
                    {deployStatus.failure_phase && (
                      <p className="mt-2 text-xs text-zinc-500">
                        Failed phase:{" "}
                        <span className="text-zinc-300">{deployStatus.failure_phase}</span>
                        {deployStatus.pipeline_state
                          ? ` · Pipeline: ${deployStatus.pipeline_state}`
                          : ""}
                      </p>
                    )}
                    {incidents[0] && (
                      <div className="mt-4">
                        <IncidentPanel incident={incidents[0]} />
                      </div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-3">
                      {deployStatus.failure_phase === "import" && (
                        <Button loading={loading} onClick={() => retryFromPhase("import")}>
                          Retry from import
                        </Button>
                      )}
                      {deployStatus.failure_phase !== "import" && (
                        <Button loading={loading} onClick={() => retryFromPhase("pipeline")}>
                          Retry pipeline
                        </Button>
                      )}
                      <Button variant="secondary" onClick={() => advanceToStep("operate")}>
                        Open observability anyway
                      </Button>
                      <Button variant="secondary" onClick={() => advanceToStep("incidents")}>
                        View full AIOps report
                      </Button>
                    </div>
                  </Card>
                )}
                {deployStatus && !demoMode && (
                  <Card className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      Kubernetes deployment
                    </p>
                    <p className="mt-2 text-sm text-zinc-300">
                      Pipeline: {deployStatus.pipeline_state ?? "—"} · Status:{" "}
                      {deployStatus.status ?? "—"}
                    </p>
                    {deployStatus.live_url && (
                      <p className="mt-2 text-sm">
                        <span className="text-zinc-500">Live URL: </span>
                        <a
                          href={deployStatus.live_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-indigo-400 hover:underline"
                        >
                          {deployStatus.live_url}
                        </a>
                      </p>
                    )}
                    {deployStatus.service_urls &&
                      Object.entries(deployStatus.service_urls).map(([role, url]) => (
                        <p key={role} className="mt-1 text-sm">
                          <span className="text-zinc-500 capitalize">{role}: </span>
                          <a href={url} target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline">
                            {url}
                          </a>
                        </p>
                      ))}
                    {(deployStatus.routing_checklist?.length ?? 0) > 0 && (
                      <div className="mt-4">
                        <p className="text-xs font-medium uppercase tracking-wider text-amber-500/90">
                          Post-deploy checklist
                        </p>
                        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-400">
                          {deployStatus.routing_checklist!.map((item, i) => (
                            <li key={i}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </Card>
                )}
                {!loading && !deployFailed && (
                  <div className="mt-6">
                    <Button onClick={() => advanceToStep("operate")} disabled={isPreviewStep}>
                      Open Observability
                    </Button>
                  </div>
                )}
              </StepPanel>
            )}

            {step === "operate" && (
              <StepPanel
                key="operate"
                title="Observability"
                subtitle="Unified metrics, logs, and live health from the K8s API — polled every 30s."
                badge="Observability Layer"
              >
                {isPreviewStep && <PreviewBanner />}
                {observabilityCheckedAt && !isPreviewStep && (
                  <p className="mb-3 text-xs text-zinc-500">
                    Last health probe: {new Date(observabilityCheckedAt).toLocaleTimeString()}
                  </p>
                )}
                {activeArchitecture && (
                  <Card className="mb-4 overflow-hidden p-2">
                    <ArchitectureGraphView
                      nodes={activeArchitecture.nodes}
                      edges={activeArchitecture.edges}
                      healthOverrides={healthMap}
                    />
                  </Card>
                )}
                <div className="grid gap-4 sm:grid-cols-3">
                  <StatCard
                    label="API CPU"
                    value={(() => {
                      const cpu = (observability?.metrics as { service: string; cpu_percent: number }[] | undefined)?.find((m) => m.service === "api")?.cpu_percent;
                      return cpu != null ? `${cpu.toFixed(1)}%` : "—";
                    })()}
                    icon="📊"
                    delay={0}
                  />
                  <StatCard
                    label="API Memory"
                    value={(() => {
                      const mem = (observability?.metrics as { service: string; memory_mb: number }[] | undefined)?.find((m) => m.service === "api")?.memory_mb;
                      return mem != null ? `${Math.round(mem)} MB` : "—";
                    })()}
                    icon="💾"
                    delay={0.08}
                  />
                  <StatCard
                    label="Status"
                    value={
                      (observability?.health as { status: string }[] | undefined)?.some(
                        (h) => h.status === "critical",
                      )
                        ? "Critical"
                        : (observability?.health as { status: string }[] | undefined)?.some(
                              (h) => h.status === "degraded",
                            )
                          ? "Degraded"
                          : healed || !(incidents.some((i) => i.status !== "resolved"))
                            ? "Healthy"
                            : "Degraded"
                    }
                    icon={healed ? "✅" : "⚠️"}
                    delay={0.16}
                  />
                </div>
                {typeof observability?.log_summary === "string" && observability.log_summary && (
                  <Card className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      AI log summary
                    </p>
                    <p className="mt-2 text-sm text-zinc-300">{observability.log_summary}</p>
                  </Card>
                )}
                {timelineEvents.length > 0 && (
                  <Card className="mt-4">
                    <OpsTimeline events={timelineEvents} title="Ops timeline — deploy → incident → heal → score" />
                  </Card>
                )}
                <div className="mt-6 flex items-center gap-3">
                  {!healed && incidents.some((i) => i.status !== "resolved") ? (
                    <>
                      <span className="relative flex h-2 w-2">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
                        <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500" />
                      </span>
                      <span className="text-sm text-red-300">Active incident detected</span>
                    </>
                  ) : (
                    <>
                      <span className="relative flex h-2 w-2">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                      </span>
                      <span className="text-sm text-zinc-400">Monitoring active</span>
                    </>
                  )}
                </div>
                <div className="mt-6">
                  <Button onClick={() => advanceToStep("incidents")} disabled={isPreviewStep}>
                    {incidents.some((i) => i.status !== "resolved") ? "View Incident" : "View Incidents"}
                  </Button>
                </div>
              </StepPanel>
            )}

            {step === "incidents" && (
              <StepPanel
                key="incidents"
                title="AIOps incidents"
                subtitle="Detect, diagnose, and remediate production failures."
                badge="AIOps Engine"
              >
                {isPreviewStep && <PreviewBanner />}
                {activeArchitecture && (
                  <Card className="mb-4 overflow-hidden p-2">
                    <ArchitectureGraphView
                      nodes={activeArchitecture.nodes}
                      edges={activeArchitecture.edges}
                      healthOverrides={healthMap}
                    />
                  </Card>
                )}
                {incidents.length === 0 && !isPreviewStep ? (
                  <Card className="text-center">
                    <p className="text-emerald-400">✓ No active incidents</p>
                    <p className="mt-2 text-sm text-zinc-500">
                      Run deploy in Demo Mode to simulate a failure scenario.
                    </p>
                  </Card>
                ) : (
                  (isPreviewStep ? [DEMO_INCIDENT] : incidents).map((inc, i) => (
                    <IncidentPanel
                      key={inc.id ?? i}
                      incident={inc}
                      resolved={healed || inc.status === "resolved"}
                      onApplyFix={!isPreviewStep && !healed ? applyFix : undefined}
                      applying={remediating}
                    />
                  ))
                )}
                {timelineEvents.length > 0 && !isPreviewStep && (
                  <Card className="mt-4">
                    <OpsTimeline events={timelineEvents} />
                  </Card>
                )}
                <div className="mt-6 flex gap-3">
                  <Button onClick={loadScore} loading={loading} disabled={isPreviewStep}>
                    Deployment Score
                  </Button>
                  {healed && (
                    <Button variant="secondary" onClick={() => advanceToStep("operate")}>
                      Back to Observability
                    </Button>
                  )}
                </div>
              </StepPanel>
            )}

            {step === "score" && activeScore && (
              <StepPanel
                key="score"
                title="Deployment score"
                subtitle="Computed from validation, live health, incidents, and observability — not static defaults."
                badge="Optimization Advisor"
              >
                {isPreviewStep && <PreviewBanner />}
                {"overall" in activeScore && typeof activeScore.overall === "number" && (
                  <p className="mb-4 text-sm text-zinc-400">
                    Overall readiness:{" "}
                    <span className="font-semibold text-indigo-300">{activeScore.overall}/10</span>
                  </p>
                )}
                <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
                  {(
                    ["security", "performance", "scalability", "reliability", "observability"] as const
                  ).map((k, i) =>
                    typeof activeScore[k] === "number" ? (
                      <ScoreRing key={k} label={k} value={activeScore[k]} delay={i * 0.08} />
                    ) : null,
                  )}
                </div>
                {Array.isArray(activeScore.recommendations) && activeScore.recommendations.length > 0 && (
                  <Card className="mt-6">
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      Recommendations
                    </p>
                    <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-zinc-300">
                      {activeScore.recommendations.map((rec, i) => (
                        <li key={i}>{rec}</li>
                      ))}
                    </ul>
                  </Card>
                )}
              </StepPanel>
            )}
          </AnimatePresence>
        </div>
    </AppShell>
  );
}

function YamlPreview({ title, content }: { title: string; content: string }) {
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-mono text-sm font-medium text-indigo-300">{title}</h3>
        <Badge tone="default">Generated</Badge>
      </div>
      <pre className="max-h-80 overflow-auto rounded-lg bg-black/40 p-4 font-mono text-xs leading-relaxed text-zinc-400">
        {content}
      </pre>
    </Card>
  );
}
