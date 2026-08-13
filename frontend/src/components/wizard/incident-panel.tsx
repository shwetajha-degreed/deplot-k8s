"use client";

import { Badge, Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export interface RemediationStepData {
  name: string;
  status: string;
  message?: string;
}

export interface IncidentData {
  id?: string;
  title?: string;
  status?: string;
  severity?: string;
  diagnosis?: {
    root_cause?: string;
    reason?: string;
    impact?: string;
    confidence?: number;
    suggested_fix?: string;
    log_summary?: string;
  };
  runbook?: string[];
  suggested_remediation?: {
    description?: string;
    env_changes?: Record<string, string>;
    yaml_diff?: string;
  };
  remediation_steps?: RemediationStepData[];
  remediation_error?: string;
}

interface IncidentPanelProps {
  incident: IncidentData;
  onApplyFix?: () => void;
  applying?: boolean;
  resolved?: boolean;
}

const STEP_TONE: Record<string, string> = {
  pending: "text-zinc-500",
  running: "text-amber-300",
  succeeded: "text-emerald-400",
  failed: "text-red-400",
};

export function IncidentPanel({
  incident,
  onApplyFix,
  applying = false,
  resolved = false,
}: IncidentPanelProps) {
  const d = incident.diagnosis;
  const remediation = incident.suggested_remediation;
  const steps = incident.remediation_steps ?? [];

  return (
    <Card className={`mb-4 ${resolved ? "border-emerald-500/30" : "border-red-500/20"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Badge tone={resolved ? "success" : "critical"}>
            {resolved ? "Resolved" : incident.severity ?? "critical"}
          </Badge>
          <h3 className="mt-2 font-semibold text-white">{incident.title ?? "Incident"}</h3>
          {d?.root_cause && (
            <p className="mt-1 text-sm font-medium text-red-300/90">{d.root_cause}</p>
          )}
        </div>
        {incident.status && !resolved && (
          <span className="text-xs uppercase tracking-wider text-zinc-500">{incident.status}</span>
        )}
      </div>

      {d && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <InfoBlock label="Reason" value={d.reason} />
          <InfoBlock label="Impact" value={d.impact} />
          {d.confidence != null && (
            <InfoBlock label="Confidence" value={`${Math.round(d.confidence * 100)}%`} />
          )}
          {d.log_summary && (
            <div className="sm:col-span-2">
              <InfoBlock label="Log excerpt" value={d.log_summary} mono />
            </div>
          )}
        </div>
      )}

      {incident.runbook && incident.runbook.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">Runbook</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-zinc-300">
            {incident.runbook.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {remediation && (
        <div className="mt-4 space-y-3">
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            Suggested fix
          </p>
          {remediation.description && (
            <p className="text-sm text-zinc-300">{remediation.description}</p>
          )}
          {remediation.env_changes && Object.keys(remediation.env_changes).length > 0 && (
            <pre className="overflow-auto rounded-lg bg-black/40 p-3 font-mono text-xs text-emerald-300/90">
              {Object.entries(remediation.env_changes)
                .map(([k, v]) => `${k}=${v}`)
                .join("\n")}
            </pre>
          )}
          {remediation.yaml_diff && (
            <pre className="overflow-auto rounded-lg bg-black/40 p-3 font-mono text-xs text-cyan-300/90">
              {remediation.yaml_diff}
            </pre>
          )}
        </div>
      )}

      {steps.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
            Remediation timeline
          </p>
          <ul className="mt-2 space-y-2">
            {steps.map((step, i) => (
              <li key={`${step.name}-${i}`} className="flex gap-2 text-sm">
                <span className={STEP_TONE[step.status] ?? "text-zinc-400"}>
                  {step.status === "succeeded" ? "✓" : step.status === "failed" ? "✗" : "…"}
                </span>
                <div>
                  <span className="text-zinc-200">{step.name}</span>
                  {step.message && (
                    <p className="text-xs text-zinc-500">{step.message}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {incident.remediation_error && !resolved && (
        <p className="mt-4 text-sm text-red-400">{incident.remediation_error}</p>
      )}

      {!resolved && onApplyFix && incident.id && (
        <div className="mt-6">
          <Button onClick={onApplyFix} loading={applying} className="w-full sm:w-auto">
            Apply AI Fix & Redeploy
          </Button>
        </div>
      )}

      {resolved && (
        <p className="mt-4 text-sm text-emerald-400">
          ✓ Fix applied on Zerops — env patched, redeployed, readiness passing.
        </p>
      )}
    </Card>
  );
}

function InfoBlock({
  label,
  value,
  mono = false,
}: {
  label: string;
  value?: string;
  mono?: boolean;
}) {
  if (!value) return null;
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{label}</p>
      <p className={`mt-1 text-sm text-zinc-300 ${mono ? "font-mono text-xs" : ""}`}>{value}</p>
    </div>
  );
}
