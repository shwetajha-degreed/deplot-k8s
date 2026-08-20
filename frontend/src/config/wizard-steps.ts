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

// DEMO BRANCH: only the SHIP journey is enabled. Watch (operate) and Heal
// (incidents/score) are gated out below so they don't render in the sidebar
// or the wizard, though the step IDs are kept in the type union above so
// existing page.tsx JSX doesn't need to change. See also WIZARD_PHASES.
const ALL_WIZARD_STEPS: WizardStep[] = [
  { id: "connect", label: "Connect", description: "GitHub URL or demo repo", layer: "platform", icon: "⎔" },
  { id: "analyze", label: "Analyze", description: "Stack detection", layer: "platform", icon: "◈" },
  { id: "architecture", label: "Architecture", description: "Service topology", layer: "platform", icon: "◎" },
  { id: "plan", label: "Plan", description: "Cost and build estimate", layer: "platform", icon: "◫" },
  { id: "configure", label: "Configure", description: "K8s manifests preview", layer: "platform", icon: "⬡" },
  { id: "deploy", label: "Deploy", description: "Kubernetes deployment", layer: "platform", icon: "▶" },
  { id: "operate", label: "Operate", description: "Metrics, logs, health map", layer: "observability", icon: "◉" },
  { id: "incidents", label: "Incidents", description: "AIOps doctor and remediation", layer: "aiops", icon: "⚡" },
  { id: "score", label: "Score", description: "Deployment readiness", layer: "aiops", icon: "★" },
];

export const WIZARD_STEPS: WizardStep[] = ALL_WIZARD_STEPS.filter(
  (s) => s.layer === "platform",
);

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

// DEMO BRANCH: only the Ship phase is exposed. Watch and Heal are
// intentionally omitted from the sidebar and journey nav.
export const WIZARD_PHASES: WizardPhase[] = [
  {
    layer: "platform",
    title: "Ship",
    tagline: "Repo → K8s manifests → deploy",
    icon: "🚀",
    accent: "from-indigo-500 via-violet-500 to-indigo-600",
    ring: "ring-indigo-400/50 shadow-indigo-500/40",
    line: "from-indigo-500 to-violet-500",
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
