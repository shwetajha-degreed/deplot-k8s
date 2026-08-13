"use client";

export interface OpsTimelineEvent {
  id?: string;
  source?: string;
  event_type?: string;
  message?: string;
  service?: string;
  occurred_at?: string;
}

const SOURCE_ICON: Record<string, string> = {
  deploy: "🚀",
  runtime: "⚡",
  aiops: "🧠",
  score: "★",
  readiness: "✓",
};

const TYPE_TONE: Record<string, string> = {
  started: "text-indigo-300",
  import_succeeded: "text-emerald-400",
  import_failed: "text-red-400",
  incident: "text-red-300",
  remediation_started: "text-amber-300",
  remediation_succeeded: "text-emerald-400",
  remediation_failed: "text-red-400",
  computed: "text-violet-300",
  error: "text-red-400",
};

interface OpsTimelineProps {
  events: OpsTimelineEvent[];
  title?: string;
}

export function OpsTimeline({ events, title = "Ops timeline" }: OpsTimelineProps) {
  if (!events.length) return null;

  return (
    <div className="mt-4">
      <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{title}</p>
      <ol className="relative mt-4 space-y-4 border-l border-white/10 pl-6">
        {events.map((ev, i) => {
          const icon = SOURCE_ICON[ev.source ?? ""] ?? "•";
          const tone = TYPE_TONE[ev.event_type ?? ""] ?? "text-zinc-300";
          return (
            <li key={ev.id ?? i} className="relative">
              <span className="absolute -left-[1.65rem] flex h-5 w-5 items-center justify-center rounded-full bg-zinc-900 text-xs">
                {icon}
              </span>
              <p className={`text-sm font-medium ${tone}`}>
                {ev.service ? `[${ev.service}] ` : ""}
                {ev.message}
              </p>
              <p className="text-[10px] uppercase tracking-wider text-zinc-600">
                {ev.source} · {ev.event_type}
                {ev.occurred_at ? ` · ${new Date(ev.occurred_at).toLocaleTimeString()}` : ""}
              </p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
