import { cn } from "@/lib/cn";
import { motion } from "framer-motion";
import { ReactNode } from "react";

export function Card({
  children,
  className,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay, ease: [0.25, 0.46, 0.45, 0.94] }}
      className={cn("glass-panel glass-panel-hover p-6", className)}
    >
      {children}
    </motion.div>
  );
}

export function Badge({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "success" | "warning" | "critical" | "accent";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        tone === "default" && "bg-white/10 text-zinc-300",
        tone === "success" && "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30",
        tone === "warning" && "bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30",
        tone === "critical" && "bg-red-500/15 text-red-400 ring-1 ring-red-500/30",
        tone === "accent" && "bg-indigo-500/15 text-indigo-300 ring-1 ring-indigo-500/30",
      )}
    >
      {children}
    </span>
  );
}
