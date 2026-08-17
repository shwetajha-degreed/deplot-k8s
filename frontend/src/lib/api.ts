const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export function deploymentStreamUrl(deploymentId: string): string {
  return `${API_BASE}/deployment/${deploymentId}/stream`;
}

function detailMessage(err: unknown): string | undefined {
  if (!err || typeof err !== "object") return undefined;
  const detail = (err as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const msg = (detail as { message?: unknown }).message;
    if (typeof msg === "string") return msg;
  }
  return undefined;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(
      "Could not reach the Deplot API. Please try again in a moment.",
    );
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(detailMessage(err) ?? `API error ${res.status}`);
  }
  return res.json();
}

/** Normalize pasted GitHub URLs (trim, strip trailing punctuation). */
export function normalizeRepoUrl(url: string): string {
  return url.trim().replace(/[.,;]+$/g, "").replace(/\/+$/, "");
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  analyze: (repoUrl: string | null, demoMode: boolean, githubToken?: string) =>
    request<{
      session_id: string;
      stack: Record<string, unknown>;
      required_env?: string[];
    }>("/analyze", {
      method: "POST",
      body: JSON.stringify({
        repo_url: repoUrl,
        demo_mode: demoMode,
        github_token: githubToken || undefined,
      }),
    }),

  architecture: (sessionId: string) =>
    request<{ nodes: unknown[]; edges: unknown[] }>("/architecture", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),

  generateYaml: (sessionId: string) =>
    request<{ manifests: unknown[]; namespace: string; services?: string[] }>("/generate-yaml", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),

  validateConfig: (sessionId: string) =>
    request<{ passed: boolean; issues: { severity: string; code: string; message: string; field?: string }[] }>(
      "/validate",
      {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      },
    ),

  getPlan: (sessionId: string) =>
    request<{ services: unknown[]; estimated_cost_usd_month: number }>(
      `/sessions/${sessionId}/plan`,
    ),

  deploy: (
    sessionId: string,
    demoMode: boolean,
    runtimeEnv?: Record<string, string>,
  ) =>
    request<{ deployment_id: string; status: string; stage: string }>("/deploy", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        demo_mode: demoMode,
        runtime_env: runtimeEnv ?? {},
      }),
    }),

  getDeployment: (id: string) => request<Record<string, unknown>>(`/deployment/${id}`),

  getDeploymentStatus: (id: string) =>
    request<{
      deployment_id: string;
      status: string;
      stage: string;
      live_url?: string;
      service_urls?: Record<string, string>;
      service_hostnames?: Record<string, string>;
      routing_checklist?: string[];
      pipeline_state?: string;
      message?: string;
      demo_mode?: boolean;
      failure_phase?: string;
      failure_summary?: string;
      retry_from?: string;
      deploy_ui_stage_index?: number;
    }>(`/deployment/${id}/status`),

  retryDeploy: (deploymentId: string, fromPhase: "import" | "pipeline") =>
    request<{ deployment_id: string; status: string; stage: string }>(
      `/deploy/${deploymentId}/retry`,
      {
        method: "POST",
        body: JSON.stringify({ from_phase: fromPhase }),
      },
    ),

  getObservability: (id: string) =>
    request<Record<string, unknown>>(`/deployment/${id}/observability`),

  listIncidents: (deploymentId: string) =>
    request<unknown[]>(`/deployment/${deploymentId}/incidents`),

  remediateIncident: (incidentId: string) =>
    request<Record<string, unknown>>(`/incidents/${incidentId}/remediate`, { method: "POST" }),

  diagnoseIncident: (incidentId: string) =>
    request<Record<string, unknown>>(`/incidents/${incidentId}/diagnose`, { method: "POST" }),

  redeploy: (deploymentId: string) =>
    request<{ deployment_id: string; status: string; stage: string }>(
      `/deploy/${deploymentId}/redeploy`,
      { method: "POST" },
    ),

  summarizeLogs: (deploymentId: string) =>
    request<{ summary: string }>("/logs/summarize", {
      method: "POST",
      body: JSON.stringify({ deployment_id: deploymentId }),
    }),

  getScore: (deploymentId: string) =>
    request<{
      security: number;
      performance: number;
      scalability: number;
      reliability: number;
      observability: number;
      overall?: number;
      recommendations?: string[];
    }>(`/deployment/${deploymentId}/score`),

  getDashboardSummary: () => request<import("@/config/dashboard").DashboardSummary>("/dashboard/summary"),
};
