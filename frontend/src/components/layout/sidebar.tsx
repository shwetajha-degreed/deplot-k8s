"use client";

import {
  getPhaseForStep,
  getStepIndex,
  getStepsForPhase,
  WIZARD_PHASES,
  WIZARD_STEPS,
  type WizardLayer,
  type WizardStepId,
} from "@/config/wizard-steps";
import { cn } from "@/lib/cn";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export function Sidebar({
  view = "wizard",
  step,
  maxReachedIndex,
  demoMode,
  onStepChange,
  onDemoToggle,
}: {
  view?: "dashboard" | "wizard";
  step: WizardStepId;
  maxReachedIndex: number;
  demoMode: boolean;
  onStepChange: (id: WizardStepId) => void;
  onDemoToggle: (v: boolean) => void;
}) {
  const pathname = usePathname();
  const isDashboard = view === "dashboard" || pathname === "/dashboard";
  const activeIndex = getStepIndex(step);
  const activePhase = getPhaseForStep(step).layer;
  const [focusedPhase, setFocusedPhase] = useState<WizardLayer>(activePhase);
  const [hoveredStep, setHoveredStep] = useState<WizardStepId | null>(null);

  useEffect(() => {
    setFocusedPhase(activePhase);
  }, [activePhase]);

  const phaseProgress = (layer: WizardLayer) => {
    const steps = getStepsForPhase(layer);
    const indices = steps.map((s) => getStepIndex(s.id));
    const done = indices.filter((i) => i <= maxReachedIndex).length;
    return { done, total: steps.length };
  };

  return (
    <aside className="relative flex w-[19rem] shrink-0 flex-col border-r border-white/[0.06] bg-black/30 backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-0 grid-bg opacity-30" />
      <div className="relative flex flex-1 flex-col overflow-hidden">
        {/* Brand */}
        <div className="border-b border-white/[0.06] p-5">
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-3"
          >
            <div className="relative">
              <div className="absolute inset-0 animate-pulse-slow rounded-2xl bg-indigo-500/30 blur-md" />
              <div className="relative flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-glow">
                <span className="text-sm font-bold text-white">D</span>
              </div>
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-white">Degreed Ops AI Agents</h1>
              <p className="text-[10px] text-zinc-500">Mission control</p>
            </div>
          </motion.div>

          <label className="mt-4 flex cursor-pointer items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-2">
            <span className="text-[11px] font-medium text-zinc-400">Scripted demo (fallback)</span>
            <button
              type="button"
              role="switch"
              aria-checked={demoMode}
              onClick={() => onDemoToggle(!demoMode)}
              className={cn(
                "relative h-5 w-9 rounded-full transition-colors duration-300",
                demoMode ? "bg-indigo-500" : "bg-zinc-700",
              )}
            >
              <motion.span
                layout
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
                className={cn(
                  "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-md",
                  demoMode ? "left-[18px]" : "left-0.5",
                )}
              />
            </button>
          </label>

          {/* Primary nav */}
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Link
              href="/dashboard"
              className={cn(
                "rounded-xl border px-3 py-2 text-center text-[11px] font-semibold transition-all",
                isDashboard
                  ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-200"
                  : "border-white/[0.06] bg-white/[0.02] text-zinc-500 hover:border-white/10 hover:text-zinc-300",
              )}
            >
              📊 Dashboard
            </Link>
            <Link
              href="/"
              className={cn(
                "rounded-xl border px-3 py-2 text-center text-[11px] font-semibold transition-all",
                !isDashboard
                  ? "border-indigo-500/40 bg-indigo-500/15 text-indigo-200"
                  : "border-white/[0.06] bg-white/[0.02] text-zinc-500 hover:border-white/10 hover:text-zinc-300",
              )}
            >
              🚀 Deploy wizard
            </Link>
          </div>
        </div>

        {/* Phase pipeline — wizard only */}
        {!isDashboard && (
        <nav className="flex-1 overflow-y-auto px-4 py-5" aria-label="Deployment phases">
          <div className="relative">
            {/* Vertical spine connecting phases */}
            <div className="absolute bottom-6 left-[1.125rem] top-6 w-px bg-gradient-to-b from-indigo-500/40 via-cyan-500/30 to-fuchsia-500/40" />

            <div className="space-y-3">
              {WIZARD_PHASES.map((phase, phaseIdx) => {
                const steps = getStepsForPhase(phase.layer);
                const { done, total } = phaseProgress(phase.layer);
                const isActivePhase = activePhase === phase.layer;
                const isExpanded = focusedPhase === phase.layer;
                const phaseComplete = done === total;
                const phaseStarted = done > 0;

                return (
                  <motion.div
                    key={phase.layer}
                    layout
                    initial={{ opacity: 0, x: -12 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: phaseIdx * 0.08 }}
                    className="relative"
                  >
                    {/* Phase orb — click to expand/collapse genre */}
                    <button
                      type="button"
                      onClick={() =>
                        setFocusedPhase(isExpanded && !isActivePhase ? activePhase : phase.layer)
                      }
                      className={cn(
                        "group relative flex w-full items-start gap-3 rounded-2xl text-left transition-all duration-300",
                        isExpanded ? "pb-1" : "pb-0",
                      )}
                    >
                      <div className="relative z-10 shrink-0">
                        <motion.div
                          animate={{
                            scale: isActivePhase ? 1.08 : 1,
                            boxShadow: isActivePhase
                              ? "0 0 24px rgba(99,102,241,0.45)"
                              : "0 0 0px transparent",
                          }}
                          className={cn(
                            "flex h-9 w-9 items-center justify-center rounded-full border-2 text-base transition-colors",
                            isActivePhase
                              ? cn("border-white/20 bg-gradient-to-br text-white", phase.accent)
                              : phaseStarted
                                ? "border-emerald-500/40 bg-emerald-500/10"
                                : "border-white/10 bg-white/[0.04] grayscale opacity-60 group-hover:opacity-90 group-hover:grayscale-0",
                          )}
                        >
                          {phaseComplete ? "✓" : phase.icon}
                        </motion.div>
                        {isActivePhase && (
                          <motion.span
                            layoutId="phase-pulse"
                            className={cn(
                              "absolute inset-0 rounded-full bg-gradient-to-br opacity-40 blur-md",
                              phase.accent,
                            )}
                          />
                        )}
                      </div>

                      <div className="min-w-0 flex-1 pt-0.5">
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={cn(
                              "text-xs font-bold uppercase tracking-wider",
                              isActivePhase ? "text-white" : "text-zinc-500 group-hover:text-zinc-300",
                            )}
                          >
                            {phase.title}
                          </span>
                          <span className="font-mono text-[10px] text-zinc-600">
                            {done}/{total}
                          </span>
                        </div>
                        <p className="mt-0.5 text-[10px] leading-snug text-zinc-600 group-hover:text-zinc-500">
                          {phase.tagline}
                        </p>
                        {/* Mini progress arc */}
                        <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/5">
                          <motion.div
                            className={cn("h-full rounded-full bg-gradient-to-r", phase.line)}
                            initial={{ width: 0 }}
                            animate={{ width: `${(done / total) * 100}%` }}
                            transition={{ duration: 0.5 }}
                          />
                        </div>
                      </div>
                    </button>

                    {/* Step constellation — expands within genre */}
                    <AnimatePresence initial={false}>
                      {isExpanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}
                          className="overflow-hidden"
                        >
                          <div className="relative ml-[1.125rem] border-l border-dashed border-white/10 pl-5 pt-2">
                            <div className="flex flex-col gap-1 pb-2">
                              {steps.map((s) => {
                                const idx = getStepIndex(s.id);
                                const isActive = step === s.id;
                                const isUnlocked = idx <= maxReachedIndex;
                                const isPreview = idx > maxReachedIndex;
                                const isDone = isUnlocked && !isActive;
                                const isHovered = hoveredStep === s.id;

                                return (
                                  <motion.button
                                    key={s.id}
                                    type="button"
                                    onClick={() => onStepChange(s.id)}
                                    onMouseEnter={() => setHoveredStep(s.id)}
                                    onMouseLeave={() => setHoveredStep(null)}
                                    whileHover={{ x: 4 }}
                                    whileTap={{ scale: 0.98 }}
                                    className={cn(
                                      "group/step relative flex items-center gap-3 rounded-xl py-2 pl-1 pr-2 text-left transition-all",
                                      isActive && "bg-white/[0.06]",
                                      !isActive && "hover:bg-white/[0.03]",
                                      isPreview && !isActive && "opacity-70",
                                    )}
                                  >
                                    {/* Node on rail */}
                                    <span className="absolute -left-[1.35rem] top-1/2 z-10 -translate-y-1/2">
                                      <motion.span
                                        animate={{
                                          scale: isActive ? 1.3 : isHovered ? 1.15 : 1,
                                        }}
                                        className={cn(
                                          "block h-2.5 w-2.5 rounded-full border-2 transition-colors",
                                          isActive &&
                                            cn(
                                              "border-white bg-gradient-to-br shadow-lg",
                                              phase.accent,
                                            ),
                                          isDone && !isActive && "border-emerald-500/60 bg-emerald-500/30",
                                          isPreview &&
                                            !isActive &&
                                            "border-dashed border-amber-500/40 bg-amber-500/10",
                                          isUnlocked &&
                                            !isDone &&
                                            !isActive &&
                                            !isPreview &&
                                            "border-zinc-600 bg-zinc-800 group-hover/step:border-zinc-400",
                                        )}
                                      />
                                    </span>

                                    <span
                                      className={cn(
                                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg font-mono text-xs transition-all",
                                        isActive
                                          ? "bg-white/10 text-white"
                                          : "text-zinc-600 group-hover/step:text-zinc-400",
                                      )}
                                    >
                                      {s.icon}
                                    </span>

                                    <div className="min-w-0 flex-1">
                                      <p
                                        className={cn(
                                          "truncate text-xs font-medium",
                                          isActive ? "text-white" : "text-zinc-400",
                                        )}
                                      >
                                        {s.label}
                                        {isPreview && !isActive && (
                                          <span className="ml-1.5 text-[9px] font-normal uppercase tracking-wider text-amber-500/80">
                                            preview
                                          </span>
                                        )}
                                      </p>
                                      <AnimatePresence>
                                        {(isActive || isHovered) && (
                                          <motion.p
                                            initial={{ opacity: 0, height: 0 }}
                                            animate={{ opacity: 1, height: "auto" }}
                                            exit={{ opacity: 0, height: 0 }}
                                            className="text-[10px] text-zinc-600"
                                          >
                                            {s.description}
                                          </motion.p>
                                        )}
                                      </AnimatePresence>
                                    </div>

                                    {isActive && (
                                      <motion.span
                                        layoutId="step-beacon"
                                        className={cn(
                                          "h-1.5 w-1.5 shrink-0 rounded-full bg-gradient-to-r",
                                          phase.line,
                                        )}
                                        animate={{ opacity: [0.5, 1, 0.5] }}
                                        transition={{ repeat: Infinity, duration: 1.5 }}
                                      />
                                    )}
                                  </motion.button>
                                );
                              })}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })}
            </div>
          </div>
        </nav>
        )}

        {isDashboard && (
          <div className="flex-1 overflow-y-auto px-4 py-6">
            <div className="rounded-2xl border border-white/[0.06] bg-gradient-to-br from-indigo-500/10 to-violet-500/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-300/80">
                Command center
              </p>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                Platform KPIs, live apps, incidents, and readiness scores — all in one view.
              </p>
              <div className="mt-4 space-y-2 text-[11px] text-zinc-600">
                <p>◈ Ship — repos & deploys</p>
              </div>
            </div>
          </div>
        )}

        {/* Journey footer */}
        <div className="border-t border-white/[0.06] p-4">
          <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-indigo-500/5 to-violet-500/5 p-3">
            <p className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
              {isDashboard ? "Overview" : "Journey"}
            </p>
            <p className="mt-1 text-sm font-semibold text-white">
              {isDashboard ? "Mission Control" : WIZARD_STEPS[activeIndex]?.label}
            </p>
            {!isDashboard && (
            <div className="mt-3 flex items-center gap-1">
              {WIZARD_STEPS.map((s, i) => (
                <motion.div
                  key={s.id}
                  title={s.label}
                  className={cn(
                    "h-1 flex-1 rounded-full transition-colors",
                    i <= maxReachedIndex ? "bg-indigo-500/80" : i === activeIndex ? "bg-indigo-400/50" : "bg-white/5",
                  )}
                  animate={i === activeIndex ? { opacity: [0.6, 1, 0.6] } : {}}
                  transition={{ repeat: Infinity, duration: 2 }}
                />
              ))}
            </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
