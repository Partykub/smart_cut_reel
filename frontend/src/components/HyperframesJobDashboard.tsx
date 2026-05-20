"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getHyperframesJobStatus, runHyperframesJob } from "@/lib/hyperframes-api";
import { getHyperframesSubtitleHelpText } from "@/lib/hyperframes-subtitles";
import {
  isTerminalHyperframesStatus,
  type HyperframesArtifactEntry,
  type HyperframesJobStatusResponse,
} from "@/lib/hyperframes-types";

const POLL_INTERVAL_MS = 2000;

export function HyperframesJobDashboard({ jobId }: { jobId: string }) {
  const [data, setData] = useState<HyperframesJobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await getHyperframesJobStatus(jobId);
      setData(next);
      setError(null);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
    }
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!data || isTerminalHyperframesStatus(data.status)) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }
    if (intervalRef.current) {
      return;
    }
    intervalRef.current = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [data, refresh]);

  if (!data) {
    return <p className="text-zinc-500">Loading Hyperframes job {jobId}...</p>;
  }

  const artifacts: HyperframesArtifactEntry[] = Object.values(data.artifacts);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Hyperframes job</p>
          <h1 className="font-mono text-2xl text-zinc-100">{data.job_id}</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Template: <span className="font-mono text-zinc-200">{data.template_family}</span>
            {" · "}
            Orientation: <span className="font-mono text-zinc-200">{data.orientation_detected}</span>
          </p>
          {data.project_id ? (
            <div className="mt-3 flex flex-wrap gap-3 text-sm text-zinc-400">
              <Link
                href={`/hyperframes/projects/${data.project_id}`}
                className="text-cyan-300 hover:text-cyan-200"
              >
                Back to project
              </Link>
              {data.revision_id ? (
                <p>
                  Revision: <span className="font-mono text-zinc-300">{data.revision_id}</span>
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          disabled={isRunning || data.status === "rendering"}
          onClick={async () => {
            setIsRunning(true);
            try {
              await runHyperframesJob(jobId);
              await refresh();
            } catch (runError) {
              setError(runError instanceof Error ? runError.message : String(runError));
            } finally {
              setIsRunning(false);
            }
          }}
          className="rounded-lg border border-zinc-700 bg-zinc-950/80 px-4 py-2 text-sm text-zinc-200 hover:border-zinc-500 disabled:opacity-50"
        >
          {data.status === "rendering" || isRunning ? "Rendering..." : "Run again"}
        </button>
      </header>

      <section className="grid gap-4 sm:grid-cols-3">
        <MetricCard label="Status" value={data.status} />
        <MetricCard label="Variant" value={data.template_variant} />
        <MetricCard label="Progress" value={`${data.progress_percent}%`} />
      </section>

      {error ? (
        <p className="rounded-md border border-amber-900/40 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
          {error}
        </p>
      ) : null}

      {data.error_message ? (
        <p className="rounded-md border border-red-900/40 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          {data.error_code ?? "render_failed"}: {data.error_message}
        </p>
      ) : null}

      {data.error_code === "render_failed" && data.error_message?.toLowerCase().includes("subtitle") ? (
        <div className="rounded-xl border border-amber-900/40 bg-amber-950/30 p-4 text-sm text-amber-200">
          <p className="font-medium text-amber-100">Subtitle contract hint</p>
          <p className="mt-1">{getHyperframesSubtitleHelpText()}</p>
        </div>
      ) : null}

      <section className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
        <h2 className="font-display text-lg text-zinc-100">Artifacts</h2>
        <div className="space-y-2 text-sm text-zinc-300">
          {artifacts.length === 0 ? (
            <p className="text-zinc-500">No artifacts yet.</p>
          ) : (
            artifacts.map((artifact) => (
              <div
                key={artifact.artifact_key}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-800/90 bg-zinc-950/70 px-3 py-2"
              >
                <div>
                  <p className="font-mono text-xs text-zinc-200">{artifact.artifact_key}</p>
                  <p className="text-xs text-zinc-500">{artifact.object_key}</p>
                </div>
                <a
                  href={`/api/hyperframes/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifact.artifact_key)}`}
                  className="text-xs text-emerald-300 hover:text-emerald-200"
                >
                  Open artifact
                </a>
              </div>
            ))
          )}
        </div>
      </section>

      {data.output_url ? (
        <section className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
          <h2 className="font-display text-lg text-zinc-100">Output</h2>
          <video
            controls
            className="aspect-[9/16] w-full max-w-sm rounded-xl border border-zinc-800 bg-black object-contain"
            src={`/api/hyperframes/jobs/${encodeURIComponent(jobId)}/output`}
          />
          <a
            href={`/api/hyperframes/jobs/${encodeURIComponent(jobId)}/output`}
            className="inline-flex rounded-lg bg-emerald-400 px-4 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-300"
          >
            Download MP4
          </a>
        </section>
      ) : null}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
      <p className="text-xs uppercase tracking-widest text-zinc-500">{label}</p>
      <p className="mt-2 font-mono text-base text-zinc-100">{value}</p>
    </div>
  );
}
