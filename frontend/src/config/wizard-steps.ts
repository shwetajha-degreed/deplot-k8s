/**
 * Wizard steps — add new steps here without restructuring the app.
 */
export type WizardStepId =
  | "connect"
  | "analyze"
  | "architecture"
  | "plan"
  | "configure"
  | "deploy"
  | "operate"
  | "incidents"
  | "score";

export type WizardLayer = "platform" | "observability" | "aiops";

export interface WizardStep {
  id: WizardStepId;
  label: string;
  description: string;
  layer: WizardLayer;
  icon: string;
}

export const WIZARD_STEPS: WizardStep[] = [
  { id: "connect", label: "Connect", description: "GitHub URL or demo repo", layer: "platform", icon: "⎔" },
  { id: "analyze", label: "Analyze", description: "Stack detection", layer: "platform", icon: "◈" },
  { id: "architecture", label: "Architecture", description: "Service topology", layer: "platform", icon: "◎" },
  { id: "plan", label: "Plan", description: "Cost and build estimate", layer: "platform", icon: "◫" },
  { id: "configure", label: "Configure", description: "Import YAML + zerops.yaml", layer: "platform", icon: "⬡" },
  { id: "deploy", label: "Deploy", description: "Zerops deployment", layer: "platform", icon: "▶" },
  { id: "operate", label: "Operate", description: "Metrics, logs, health map", layer: "observability", icon: "◉" },
  { id: "incidents", label: "Incidents", description: "AIOps doctor and remediation", layer: "aiops", icon: "⚡" },
  { id: "score", label: "Score", description: "Deployment readiness", layer: "aiops", icon: "★" },
];

export const LAYER_LABELS: Record<WizardLayer, string> = {
  platform: "Platform Engineering",
  observability: "Observability",
  aiops: "AIOps",
};

export interface WizardPhase {
  layer: WizardLayer;
  title: string;
  tagline: string;
  icon: string;
  accent: string;
  ring: string;
  line: string;
}

export const WIZARD_PHASES: WizardPhase[] = [
  {
    layer: "platform",
    title: "Ship",
    tagline: "Repo → Zerops config → deploy",
    icon: "🚀",
    accent: "from-indigo-500 via-violet-500 to-indigo-600",
    ring: "ring-indigo-400/50 shadow-indigo-500/40",
    line: "from-indigo-500 to-violet-500",
  },
  {
    layer: "observability",
    title: "Watch",
    tagline: "Metrics, logs, live health",
    icon: "📡",
    accent: "from-cyan-400 via-sky-500 to-blue-600",
    ring: "ring-cyan-400/50 shadow-cyan-500/40",
    line: "from-violet-500 to-cyan-500",
  },
  {
    layer: "aiops",
    title: "Heal",
    tagline: "Detect, diagnose, remediate",
    icon: "🧠",
    accent: "from-fuchsia-500 via-purple-500 to-violet-600",
    ring: "ring-fuchsia-400/50 shadow-fuchsia-500/40",
    line: "from-cyan-500 to-fuchsia-500",
  },
];

export function getStepIndex(id: WizardStepId): number {
  return WIZARD_STEPS.findIndex((s) => s.id === id);
}

export function getStepsForPhase(layer: WizardLayer): WizardStep[] {
  return WIZARD_STEPS.filter((s) => s.layer === layer);
}

export function getPhaseForStep(stepId: WizardStepId): WizardPhase {
  const step = WIZARD_STEPS.find((s) => s.id === stepId)!;
  return WIZARD_PHASES.find((p) => p.layer === step.layer)!;
}
