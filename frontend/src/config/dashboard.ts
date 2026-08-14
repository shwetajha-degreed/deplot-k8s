export interface LiveApp {
  name: string;
  url: string;
  environment: string;
}

export interface RecentActivity {
  id: string;
  message: string;
  occurred_at: string;
  category: string;
}

export interface DashboardSummary {
  connected_repos: number;
  total_deployments: number;
  active_deployments: number;
  success_rate_percent: number;
  environments: number;
  k8s_services: number;
  services_healthy: string;
  services_healthy_count: number;
  services_total: number;
  open_incidents: number;
  critical_incidents: number;
  deployment_readiness_score: number;
  estimated_monthly_cost_usd: number;
  avg_build_time_minutes: number;
  live_apps: LiveApp[];
  last_deploy_at: string | null;
  last_deploy_relative: string | null;
  mttr_minutes: number;
  top_framework: string | null;
  stack_mix: Record<string, number>;
  recent_activity: RecentActivity[];
  is_demo_baseline: boolean;
}

export const PHASE2_FEATURES = [
  {
    title: "CPU & memory time-series",
    description: "Live charts per K8s workload with historical rollups",
    icon: "📈",
  },
  {
    title: "Multi-cluster support",
    description: "Link and switch between multiple AKS clusters",
    icon: "🔗",
  },
  {
    title: "Build log streaming",
    description: "Real-time deploy logs from the Kaniko build pipeline",
    icon: "📜",
  },
  {
    title: "Team & RBAC",
    description: "Users, roles, and audit trails for platform ops",
    icon: "👥",
  },
  {
    title: "Cost & usage insights",
    description: "Estimated cluster spend by namespace and workload",
    icon: "💳",
  },
  {
    title: "SLA & error budget",
    description: "SLO tracking, burn rate, and incident budgets",
    icon: "🎯",
  },
] as const;

export const KPI_METRICS = [
  { key: "connected_repos", label: "Connected repos", icon: "⎔" },
  { key: "total_deployments", label: "Total deployments", icon: "▶" },
  { key: "active_deployments", label: "Active deployments", icon: "◉" },
  { key: "success_rate_percent", label: "Success rate", icon: "✓", suffix: "%" },
  { key: "environments", label: "Environments", icon: "◎" },
  { key: "k8s_services", label: "K8s workloads", icon: "⬡" },
  { key: "services_healthy", label: "Services healthy", icon: "💚" },
  { key: "open_incidents", label: "Open incidents", icon: "⚡" },
  { key: "critical_incidents", label: "Critical incidents", icon: "🔴" },
  { key: "deployment_readiness_score", label: "Readiness score", icon: "★", suffix: "/10" },
  { key: "estimated_monthly_cost_usd", label: "Est. monthly cost", icon: "💵", prefix: "$" },
  { key: "avg_build_time_minutes", label: "Avg build time", icon: "⏱", suffix: " min" },
  { key: "last_deploy_relative", label: "Last deploy", icon: "🕐" },
  { key: "mttr_minutes", label: "MTTR", icon: "🩺", suffix: " min" },
  { key: "top_framework", label: "Top framework", icon: "◈" },
] as const;
