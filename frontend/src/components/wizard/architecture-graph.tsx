"use client";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";

export interface ArchNode {
  id: string;
  label: string;
  type: string;
  technology?: string | null;
  hostname?: string | null;
  health?: string;
}

export interface ArchEdge {
  source: string;
  target: string;
  label?: string | null;
}

const LAYOUT: Record<string, { x: number; y: number }> = {
  frontend: { x: 0, y: 40 },
  api: { x: 260, y: 40 },
  database: { x: 460, y: 200 },
  cache: { x: 260, y: 200 },
  search: { x: 60, y: 200 },
};

const HEALTH_STYLES: Record<string, string> = {
  healthy: "border-emerald-500/60 bg-emerald-500/10 shadow-[0_0_20px_rgba(16,185,129,0.15)]",
  degraded: "border-amber-500/60 bg-amber-500/10 shadow-[0_0_20px_rgba(245,158,11,0.15)]",
  critical: "border-red-500/60 bg-red-500/10 shadow-[0_0_20px_rgba(239,68,68,0.2)]",
  unknown: "border-indigo-500/30 bg-indigo-500/10",
};

interface ArchitectureGraphViewProps {
  showHealth?: boolean;
  nodes: ArchNode[];
  edges: ArchEdge[];
  healthOverrides?: Record<string, string>;
  showHostnames?: boolean;
}

export function ArchitectureGraphView({
  nodes,
  edges,
  healthOverrides = {},
  showHostnames = true,
  showHealth = true,
}: ArchitectureGraphViewProps) {
  const flowNodes: Node[] = useMemo(
    () =>
      nodes.map((n, i) => {
        const pos = LAYOUT[n.id] ?? { x: (i % 2) * 280, y: Math.floor(i / 2) * 160 };
        const health = healthOverrides[n.id] ?? n.health ?? "unknown";
        const style = HEALTH_STYLES[health] ?? HEALTH_STYLES.unknown;
        return {
          id: n.id,
          position: pos,
          data: {
            label: (
              <div className={`rounded-xl border px-5 py-4 text-center ${style}`}>
                <p className="text-sm font-semibold text-white">{n.label}</p>
                {showHostnames && n.hostname && (
                  <p className="mt-1 font-mono text-[10px] text-cyan-300/80">{n.hostname}</p>
                )}
                <p className="mt-1 text-[10px] uppercase tracking-wider text-zinc-500">
                  {n.technology ?? n.type}
                </p>
                {showHealth && (
                  <p
                    className={`mt-2 text-[10px] font-medium uppercase ${
                      health === "healthy"
                        ? "text-emerald-400"
                        : health === "critical"
                          ? "text-red-400"
                          : health === "degraded"
                            ? "text-amber-400"
                            : "text-zinc-500"
                    }`}
                  >
                    {health}
                  </p>
                )}
              </div>
            ),
          },
          style: { background: "transparent", border: "none", padding: 0 },
        };
      }),
    [nodes, healthOverrides, showHostnames, showHealth],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      edges.map((e, i) => ({
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        label: e.label ?? undefined,
        animated: true,
        style: { stroke: "#6366f1", strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#6366f1" },
        labelStyle: { fill: "#a1a1aa", fontSize: 10 },
      })),
    [edges],
  );

  return (
    <div className="h-[360px] w-full rounded-xl border border-white/10 bg-black/20">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#27272a" gap={20} />
        <Controls showInteractive={false} className="!bg-zinc-900 !border-white/10" />
      </ReactFlow>
    </div>
  );
}

/** Demo topology when API has not been called yet. */
export const DEMO_ARCHITECTURE = {
  nodes: [
    {
      id: "frontend",
      label: "Frontend",
      type: "frontend",
      technology: "Next.js",
      hostname: "demo-web",
    },
    {
      id: "api",
      label: "API",
      type: "api",
      technology: "FastAPI",
      hostname: "demo-api",
    },
    {
      id: "database",
      label: "Database",
      type: "database",
      technology: "PostgreSQL",
      hostname: "demo-postgres",
    },
    {
      id: "cache",
      label: "Cache",
      type: "cache",
      technology: "Valkey",
      hostname: "demo-cache",
    },
    { id: "search", label: "Search", type: "search", technology: "Typesense", hostname: "demo-search" },
  ] as ArchNode[],
  edges: [
    { source: "frontend", target: "api", label: "HTTP" },
    { source: "api", target: "database" },
    { source: "api", target: "cache" },
    { source: "api", target: "search", label: "index" },
  ] as ArchEdge[],
};
