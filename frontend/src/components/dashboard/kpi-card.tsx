"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/cn";

export function KpiCard({
  label,
  value,
  icon,
  delay = 0,
  tone = "default",
}: {
  label: string;
  value: string;
  icon?: string;
  delay?: number;
  tone?: "default" | "success" | "warning" | "critical" | "accent";
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35 }}
      className={cn(
        "glass-panel glass-panel-hover relative overflow-hidden p-4",
        tone === "success" && "border-emerald-500/20",
        tone === "warning" && "border-amber-500/20",
        tone === "critical" && "border-red-500/20",
        tone === "accent" && "border-indigo-500/30",
      )}
    >
      <div className="pointer-events-none absolute -right-4 -top-4 h-16 w-16 rounded-full bg-indigo-500/5 blur-2xl" />
      {icon && <span className="mb-2 block text-lg opacity-80">{icon}</span>}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-xl font-semibold text-white">{value}</p>
    </motion.div>
  );
}

export function ComingSoonCard({
  title,
  description,
  icon,
  delay = 0,
}: {
  title: string;
  description: string;
  icon: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35 }}
      className="glass-panel relative overflow-hidden p-5 opacity-75"
    >
      <div className="absolute right-3 top-3 rounded-full bg-white/5 px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest text-zinc-500 ring-1 ring-white/10">
        Coming soon
      </div>
      <span className="mb-3 block text-2xl grayscale">{icon}</span>
      <h3 className="text-sm font-semibold text-zinc-300">{title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-zinc-600">{description}</p>
    </motion.div>
  );
}
