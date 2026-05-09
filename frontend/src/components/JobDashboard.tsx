"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getJobStatus } from "@/lib/api";
import { isTerminalStatus, type JobStatusResponse } from "@/lib/types";

import { ArtifactList } from "./ArtifactList";
import { CutPlanCard } from "./CutPlanCard";
import { JobOutputPreview } from "./JobOutputPreview";
import { RunButton } from "./RunButton";
import { StatusBoard } from "./StatusBoard";
import { TranscriptCard } from "./TranscriptCard";

const POLL_INTERVAL_MS = 2000;

export function JobDashboard({ jobId }: { jobId: string }) {
  const [data, setData] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await getJobStatus(jobId);
      setData(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!data) return;
    const overall = data.service_status.status;

    if (isTerminalStatus(overall)) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    if (intervalRef.current) return;

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

  if (error && !data) {
    return (
      <div
        role="alert"
        className="rounded-md border border-red-900/40 bg-red-950/40 p-4 text-red-200"
      >
        <p className="font-medium">Failed to load job</p>
        <p className="mt-1 text-sm text-red-300">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <p className="text-zinc-500">Loading job <span className="font-mono">{jobId}</span>...</p>
    );
  }

  const pipeline = data.pipeline;
  const enabledFeatures = data.enabled_features ?? {};
  const isPhase2Pipeline =
    pipeline?.pipeline_id === "phase2_smooth_reframe_dead_air_cut";
  const isPhase3Pipeline =
    pipeline?.pipeline_id === "phase3_audio_quality_cut";
  const hasCutPlan = Boolean(data.artifacts?.cut_plan);
  // Only show transcript card when filler-word cutting is actually enabled.
  // When disabled, transcription is skipped server-side and the artifact is
  // an empty placeholder; rendering it confuses the user (looks like the
  // pipeline is doing word-level cutting when it isn't).
  const hasTranscript =
    Boolean(data.artifacts?.transcript) &&
    enabledFeatures.remove_filler_words === true;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Job</p>
          <h1 className="font-mono text-2xl text-zinc-100">{data.job_id}</h1>
          {isPhase2Pipeline ? (
            <p className="mt-1 text-xs text-violet-300">
              Phase 2 pipeline · remove_dead_air ={" "}
              <span className="font-mono">
                {String(enabledFeatures.remove_dead_air ?? false)}
              </span>
            </p>
          ) : null}
          {isPhase3Pipeline ? (
            <p className="mt-1 text-xs text-amber-300">
              Phase 3 pipeline · enhance_audio ={" "}
              <span className="font-mono">
                {String(enabledFeatures.enhance_audio ?? false)}
              </span>{" "}
              · remove_filler_words ={" "}
              <span className="font-mono">
                {String(enabledFeatures.remove_filler_words ?? false)}
              </span>
            </p>
          ) : null}
        </div>
        <RunButton
          jobId={jobId}
          status={data.service_status.status}
          onRan={refresh}
        />
      </header>

      {error ? (
        <p className="rounded-md border border-amber-900/40 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
          Last refresh failed: {error}
        </p>
      ) : null}

      <StatusBoard status={data.service_status} pipeline={pipeline} />
      {hasCutPlan ? (
        <CutPlanCard jobId={jobId} enabledFeatures={enabledFeatures} />
      ) : null}
      {hasTranscript ? <TranscriptCard jobId={jobId} /> : null}
      {data.artifacts.final_9x16 ? (
        <JobOutputPreview jobId={jobId} />
      ) : null}
      <ArtifactList artifacts={data.artifacts} paths={data.paths} />
    </div>
  );
}
