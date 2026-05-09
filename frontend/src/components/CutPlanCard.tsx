"use client";

import { useEffect, useState } from "react";

import type { CutPlan, EnabledFeatures } from "@/lib/types";

interface CutPlanCardProps {
  jobId: string;
  enabledFeatures: EnabledFeatures;
}

export function CutPlanCard({ jobId, enabledFeatures }: CutPlanCardProps) {
  const [plan, setPlan] = useState<CutPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const url = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/cut_plan`;

    async function load() {
      setIsLoading(true);
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const body = (await response.json()) as CutPlan;
        if (!cancelled) {
          setPlan(body);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (isLoading) {
    return (
      <section className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4 text-sm text-zinc-500">
        Loading cut plan…
      </section>
    );
  }

  if (error || !plan) {
    return (
      <section className="rounded-lg border border-amber-900/40 bg-amber-950/30 p-4 text-sm text-amber-200">
        Could not load cut plan: {error ?? "no data"}
      </section>
    );
  }

  const featureEnabled =
    plan.feature_enabled && enabledFeatures.remove_dead_air !== false;
  const total = Math.max(plan.source_duration_seconds, 0.0001);
  const segments = plan.keep_segments;

  return (
    <section className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">
            Dead Air Cut Plan
          </p>
          <h2 className="text-lg font-medium text-zinc-100">
            {featureEnabled ? "Trimmed timeline" : "Identity (feature off)"}
          </h2>
        </div>
        <div className="text-right text-xs text-zinc-400">
          <p>
            kept{" "}
            <span className="font-mono text-zinc-200">
              {plan.metrics.total_kept_seconds.toFixed(2)}s
            </span>{" "}
            of{" "}
            <span className="font-mono text-zinc-200">
              {plan.source_duration_seconds.toFixed(2)}s
            </span>
          </p>
          <p>
            removed{" "}
            <span className="font-mono text-zinc-200">
              {plan.metrics.total_removed_seconds.toFixed(2)}s
            </span>{" "}
            · {plan.metrics.cut_count} cuts ·{" "}
            {(plan.metrics.compression_ratio * 100).toFixed(1)}% compression
          </p>
          {typeof plan.metrics.removed_filler_seconds === "number" &&
          plan.metrics.removed_filler_seconds > 0 ? (
            <p className="text-amber-300">
              filler removed{" "}
              <span className="font-mono">
                {plan.metrics.removed_filler_seconds.toFixed(2)}s
              </span>
              {plan.metrics.filler_word_count
                ? ` (${plan.metrics.filler_word_count} words)`
                : null}
            </p>
          ) : null}
        </div>
      </header>

      <Timeline segments={segments} totalDuration={total} />

      <ol className="divide-y divide-zinc-800 rounded-md border border-zinc-800 text-xs">
        {segments.map((seg, idx) => {
          const duration = Math.max(seg.source_end - seg.source_start, 0);
          return (
            <li
              key={`${seg.source_start}-${seg.source_end}-${idx}`}
              className="flex items-baseline justify-between gap-3 px-3 py-2"
            >
              <span className="font-mono text-zinc-500">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <span className="flex-1 font-mono text-zinc-200">
                {formatSeconds(seg.source_start)} →{" "}
                {formatSeconds(seg.source_end)}
              </span>
              <span className="font-mono text-zinc-400">
                {duration.toFixed(2)}s
              </span>
            </li>
          );
        })}
      </ol>

      {plan.plan_warnings && plan.plan_warnings.length > 0 ? (
        <details className="rounded-md border border-amber-900/40 bg-amber-950/20 p-3 text-xs text-amber-100">
          <summary className="cursor-pointer text-amber-200">
            Plan warnings ({plan.plan_warnings.length})
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono">
            {JSON.stringify(plan.plan_warnings, null, 2)}
          </pre>
        </details>
      ) : null}
    </section>
  );
}

function Timeline({
  segments,
  totalDuration,
}: {
  segments: { source_start: number; source_end: number }[];
  totalDuration: number;
}) {
  return (
    <div className="space-y-1">
      <div className="relative h-6 overflow-hidden rounded-md border border-zinc-800 bg-zinc-900">
        {segments.map((seg, idx) => {
          const startPct = clampPct((seg.source_start / totalDuration) * 100);
          const widthPct = clampPct(
            ((seg.source_end - seg.source_start) / totalDuration) * 100,
          );
          return (
            <div
              key={`bar-${idx}`}
              className="absolute top-0 bottom-0 bg-emerald-500/80 hover:bg-emerald-400"
              style={{ left: `${startPct}%`, width: `${widthPct}%` }}
              title={`${seg.source_start.toFixed(2)}s → ${seg.source_end.toFixed(2)}s`}
            />
          );
        })}
      </div>
      <div className="flex justify-between font-mono text-[10px] text-zinc-500">
        <span>0.00s</span>
        <span>{totalDuration.toFixed(2)}s</span>
      </div>
    </div>
  );
}

function clampPct(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function formatSeconds(value: number): string {
  return `${value.toFixed(2)}s`;
}
