"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { ReactNode } from "react";

export function AppShell({
  view,
  children,
  demoMode = true,
  onDemoToggle,
  step,
  maxReachedIndex,
  onStepChange,
}: {
  view: "dashboard" | "wizard";
  children: ReactNode;
  demoMode?: boolean;
  onDemoToggle?: (v: boolean) => void;
  step?: import("@/config/wizard-steps").WizardStepId;
  maxReachedIndex?: number;
  onStepChange?: (id: import("@/config/wizard-steps").WizardStepId) => void;
}) {
  return (
    <div className="flex min-h-screen">
      <Sidebar
        view={view}
        step={step ?? "connect"}
        maxReachedIndex={maxReachedIndex ?? 0}
        demoMode={demoMode}
        onStepChange={onStepChange ?? (() => {})}
        onDemoToggle={onDemoToggle ?? (() => {})}
      />
      <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  );
}
