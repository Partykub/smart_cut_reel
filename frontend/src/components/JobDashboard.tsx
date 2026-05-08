"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getJobStatus } from "@/lib/api";
import { isTerminalStatus, type JobStatusResponse } from "@/lib/types";

import { ArtifactList } from "./ArtifactList";
import { JobOutputPreview } from "./JobOutputPreview";
import { RunButton } from "./RunButton";
import { StatusBoard } from "./StatusBoard";

const POLL_INTERVAL_MS = 2000;

export function JobDashboard({ jobId }: { jobId: string }) {
  const [data, setData] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastSuccessfulRefreshAt, setLastSuccessfulRefreshAt] = useState<number | null>(null);
  const [isTriggeringRun, setIsTriggeringRun] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshInFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (refreshInFlightRef.current) {
      return;
    }

    refreshInFlightRef.current = true;
    setIsRefreshing(true);

    try {
      const next = await getJobStatus(jobId);
      setData(next);
      setError(null);
      setLastSuccessfulRefreshAt(Date.now());
      if (next.service_status.status === "running") {
        setIsTriggeringRun(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      refreshInFlightRef.current = false;
      setIsRefreshing(false);
    }
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!data) return;
    const overall = data.service_status.status;
    const shouldPoll = isTriggeringRun || !isTerminalStatus(overall);

    if (!shouldPoll) {
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
  }, [data, isTriggeringRun, refresh]);

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

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Job</p>
          <h1 className="font-mono text-2xl text-zinc-100">{data.job_id}</h1>
        </div>
        <RunButton
          jobId={jobId}
          status={data.service_status.status}
          onTriggerStart={() => {
            setIsTriggeringRun(true);
            setError(null);
            void refresh();
          }}
          onRunError={(runError) => {
            setIsTriggeringRun(false);
            setError(runError.message);
          }}
          onRan={refresh}
        />
      </header>

      {error ? (
        <p className="rounded-md border border-amber-900/40 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
          Last refresh failed: {error}
        </p>
      ) : null}

      <StatusBoard
        status={data.service_status}
        isRefreshing={isRefreshing}
        lastSuccessfulRefreshAt={lastSuccessfulRefreshAt}
        refreshError={error}
        isTriggeringRun={isTriggeringRun}
      />
      {data.artifacts.final_9x16 ? (
        <JobOutputPreview
          jobId={jobId}
          artifactKey="final_9x16"
          title="final_9x16.mp4"
          downloadName={`${jobId}_final_9x16.mp4`}
        />
      ) : null}
      {data.artifacts.source_overlay ? (
        <JobOutputPreview
          jobId={jobId}
          artifactKey="source_overlay"
          eyebrow="Debug Output"
          title="source_overlay.mp4"
          downloadName={`${jobId}_source_overlay.mp4`}
          videoClassName="mx-auto max-h-[min(70vh,560px)] w-full max-w-3xl rounded-md bg-black"
        />
      ) : null}
      <ArtifactList
        artifacts={data.artifacts}
        paths={data.paths}
        serviceStatus={data.service_status}
      />
    </div>
  );
}
