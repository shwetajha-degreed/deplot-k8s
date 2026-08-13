import { motion } from "framer-motion";
import { ReactNode } from "react";
import { Badge } from "@/components/ui/card";

export function StepPanel({
  title,
  subtitle,
  badge,
  children,
}: {
  title: string;
  subtitle?: string;
  badge?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
      className="max-w-4xl"
    >
      <div className="mb-8">
        {badge && (
          <Badge tone="accent" >
            {badge}
          </Badge>
        )}
        <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white">{title}</h2>
        {subtitle && <p className="mt-2 text-base text-zinc-400">{subtitle}</p>}
      </div>
      {children}
    </motion.div>
  );
}

export function PreviewBanner() {
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3"
    >
      <p className="text-sm text-amber-200/90">
        <span className="font-semibold">Preview mode</span> — sample layout only. Run{" "}
        <span className="text-white">Analyze Repository</span> from Connect to unlock live data
        and actions.
      </p>
    </motion.div>
  );
}

export function StatCard({
  label,
  value,
  icon,
  delay = 0,
}: {
  label: string;
  value: string;
  icon?: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.3 }}
      className="glass-panel glass-panel-hover p-4"
    >
      {icon && <span className="mb-2 block text-lg">{icon}</span>}
      <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-white">{value}</p>
    </motion.div>
  );
}

export function ScoreRing({ label, value, delay = 0 }: { label: string; value: number; delay?: number }) {
  const pct = Math.min(100, (value / 10) * 100);
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className="glass-panel flex flex-col items-center p-6"
    >
      <div className="relative h-20 w-20">
        <svg className="h-20 w-20 -rotate-90" viewBox="0 0 36 36">
          <path
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="2"
          />
          <motion.path
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke="url(#scoreGradient)"
            strokeWidth="2"
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: pct / 100 }}
            transition={{ delay: delay + 0.2, duration: 0.8, ease: "easeOut" }}
          />
          <defs>
            <linearGradient id="scoreGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#6366f1" />
              <stop offset="100%" stopColor="#a855f7" />
            </linearGradient>
          </defs>
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-white">
          {value.toFixed(1)}
        </span>
      </div>
      <p className="mt-3 text-xs capitalize text-zinc-400">{label}</p>
    </motion.div>
  );
}
