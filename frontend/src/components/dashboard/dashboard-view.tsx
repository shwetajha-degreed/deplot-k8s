"use client";

import { Badge, Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScoreRing } from "@/components/wizard/step-panel";
import { ComingSoonCard, KpiCard } from "@/components/dashboard/kpi-card";
import {
  KPI_METRICS,
  PHASE2_FEATURES,
  type DashboardSummary,
} from "@/config/dashboard";
import { motion } from "framer-motion";
import Link from "next/link";

function formatKpiValue(
  key: (typeof KPI_METRICS)[number]["key"],
  data: DashboardSummary,
  metric: (typeof KPI_METRICS)[number],
): string {
  const raw = data[key as keyof DashboardSummary];
  if (key === "top_framework") {
    return raw ? String(raw) : "—";
  }
  if (key === "last_deploy_relative") {
    return data.last_deploy_relative ?? "—";
  }
  if (raw === null || raw === undefined) return "—";
  const prefix = "prefix" in metric ? metric.prefix : "";
  const suffix = "suffix" in metric ? metric.suffix : "";
  return `${prefix}${raw}${suffix}`;
}

function kpiTone(key: string, data: DashboardSummary): "default" | "success" | "warning" | "critical" | "accent" {
  if (key === "critical_incidents" && data.critical_incidents > 0) return "critical";
  if (key === "open_incidents" && data.open_incidents > 0) return "warning";
  if (key === "success_rate_percent" && data.success_rate_percent >= 90) return "success";
  if (key === "deployment_readiness_score") return "accent";
  return "default";
}

const CATEGORY_ICON: Record<string, string> = {
  deploy: "▶",
  incident: "⚡",
  analyze: "◈",
  score: "★",
};

export function DashboardView({ data }: { data: DashboardSummary }) {
  return (
    <div className="max-w-6xl space-y-10">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-wrap items-end justify-between gap-4"
      >
        <div>
          <Badge tone="accent">Mission Control</Badge>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white">
            Platform dashboard
          </h1>
          <p className="mt-2 max-w-xl text-base text-zinc-400">
            Ship, watch, and heal — all your Kubernetes deployments in one command center.
          </p>
          {data.total_deployments === 0 && data.connected_repos === 0 && (
            <p className="mt-2 text-xs text-zinc-500">
              No live activity yet — run the deploy wizard against a real GitHub repo to populate metrics.
            </p>
          )}
        </div>
        <Link href="/">
          <Button>+ New deployment</Button>
        </Link>
      </motion.div>

      {/* Phase 1 — Live KPIs */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <h2 className="text-xs font-bold uppercase tracking-widest text-zinc-500">Phase 1 · Live</h2>
          <span className="h-px flex-1 bg-white/5" />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {KPI_METRICS.map((metric, i) => (
            <KpiCard
              key={metric.key}
              label={metric.label}
              value={formatKpiValue(metric.key, data, metric)}
              icon={metric.icon}
              delay={i * 0.03}
              tone={kpiTone(metric.key, data)}
            />
          ))}
        </div>
      </section>

      {/* Live apps + readiness + stack */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card delay={0.1} className="lg:col-span-2">
          <h3 className="text-sm font-semibold text-white">Live apps</h3>
          <p className="mt-1 text-xs text-zinc-500">Production URLs across environments</p>
          {data.live_apps.length === 0 ? (
            <p className="mt-6 text-sm text-zinc-600">No live apps yet — deploy to see URLs here.</p>
          ) : (
            <ul className="mt-4 space-y-2">
              {data.live_apps.map((app) => (
                <li
                  key={app.url}
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white">{app.name}</p>
                    <a
                      href={app.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="truncate font-mono text-[11px] text-cyan-400/90 hover:text-cyan-300 hover:underline"
                    >
                      {app.url}
                    </a>
                  </div>
                  <Badge tone="default">{app.environment}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-4">
          <Card delay={0.15}>
            <h3 className="mb-4 text-sm font-semibold text-white">Readiness</h3>
            <div className="flex justify-center">
              <ScoreRing label="overall" value={data.deployment_readiness_score} />
            </div>
          </Card>
          <Card delay={0.2}>
            <h3 className="text-sm font-semibold text-white">Stack mix</h3>
            {Object.keys(data.stack_mix).length === 0 ? (
              <p className="mt-3 text-xs text-zinc-600">No stacks analyzed yet</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {Object.entries(data.stack_mix).map(([fw, count]) => (
                  <li key={fw} className="flex items-center justify-between text-sm">
                    <span className="capitalize text-zinc-400">{fw}</span>
                    <span className="font-mono text-white">{count}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {/* Activity feed */}
      <Card delay={0.25}>
        <h3 className="text-sm font-semibold text-white">Recent activity</h3>
        <ul className="mt-4 space-y-3">
          {data.recent_activity.length === 0 ? (
            <li className="text-sm text-zinc-600">No activity yet</li>
          ) : (
            data.recent_activity.map((item) => (
              <li
                key={item.id}
                className="flex items-start gap-3 border-b border-white/[0.04] pb-3 last:border-0 last:pb-0"
              >
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/5 text-xs">
                  {CATEGORY_ICON[item.category] ?? "•"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-zinc-300">{item.message}</p>
                  <p className="mt-0.5 text-[10px] uppercase tracking-wider text-zinc-600">
                    {item.category}
                  </p>
                </div>
              </li>
            ))
          )}
        </ul>
      </Card>

      {/* Phase 2 — Coming soon */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <h2 className="text-xs font-bold uppercase tracking-widest text-zinc-500">
            Phase 2 · Roadmap
          </h2>
          <span className="h-px flex-1 bg-white/5" />
          <Badge tone="default">Coming soon</Badge>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {PHASE2_FEATURES.map((feature, i) => (
            <ComingSoonCard
              key={feature.title}
              title={feature.title}
              description={feature.description}
              icon={feature.icon}
              delay={0.3 + i * 0.05}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
