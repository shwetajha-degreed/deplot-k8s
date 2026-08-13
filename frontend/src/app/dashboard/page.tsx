"use client";

import { DashboardView } from "@/components/dashboard/dashboard-view";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { DashboardSummary } from "@/config/dashboard";
import { useCallback, useEffect, useState } from "react";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await api.getDashboardSummary();
      setData(summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell view="dashboard" demoMode={false}>
      <div className="flex-1 overflow-y-auto p-8">
        {loading && (
          <div className="flex h-64 items-center justify-center">
            <span className="h-8 w-8 animate-spin rounded-full border-2 border-indigo-500/30 border-t-indigo-400" />
          </div>
        )}
        {error && (
          <div className="glass-panel max-w-md p-6 text-center">
            <p className="text-sm text-red-400">{error}</p>
            <Button className="mt-4" variant="secondary" onClick={load}>
              Retry
            </Button>
          </div>
        )}
        {data && !loading && <DashboardView data={data} />}
      </div>
    </AppShell>
  );
}
