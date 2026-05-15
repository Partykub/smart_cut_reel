"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getJobStatus } from "@/lib/api";
import { buildUploadAlignedJobSummaryLines } from "@/lib/uploadPresets";
import {
  isTerminalStatus,
  PIPELINE_ID_REFRAME_AUDIO_QUALITY,
  PIPELINE_ID_REFRAME_DEAD_AIR,
  PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED,
  PIPELINE_ID_REFRAME_SMOOTH_AUDIO,
  type JobStatusResponse,
} from "@/lib/types";

import { ArtifactList } from "./ArtifactList";
import { AudioOutputInsightPanel } from "./AudioOutputInsightPanel";
import { CutPlanCard } from "./CutPlanCard";
import { JobOutputPreview } from "./JobOutputPreview";
import { RunButton } from "./RunButton";
import { StatusBoard } from "./StatusBoard";
import { TranscriptCard } from "./TranscriptCard";

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

  const pipeline = data.pipeline;
  const enabledFeatures = data.enabled_features ?? {};
  const pid = pipeline?.pipeline_id;
  const isDeadAirPipeline =
    pid === PIPELINE_ID_REFRAME_DEAD_AIR ||
    pid === PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED ||
    pid === PIPELINE_ID_REFRAME_AUDIO_QUALITY;
  const isLegacyDeadAirOnly = pid === PIPELINE_ID_REFRAME_DEAD_AIR;
  const isAudioQualityPipeline = pid === PIPELINE_ID_REFRAME_AUDIO_QUALITY;
  const isSmoothAudioPipeline = pid === PIPELINE_ID_REFRAME_SMOOTH_AUDIO;
  const hasCutPlan = Boolean(data.artifacts?.cut_plan);
  const waveformAnalysisUrl =
    data.artifacts?.enhanced_audio != null
      ? `/api/jobs/${encodeURIComponent(jobId)}/artifacts/enhanced_audio`
      : data.artifacts?.extracted_audio != null
        ? `/api/jobs/${encodeURIComponent(jobId)}/artifacts/extracted_audio`
        : null;
  /** Same timeline as analysis strip — raw extract when prep output exists (A/B waveform). */
  const waveformCompareUrl =
    data.artifacts?.enhanced_audio != null && data.artifacts?.extracted_audio != null
      ? `/api/jobs/${encodeURIComponent(jobId)}/artifacts/extracted_audio`
      : null;
  // Only show transcript card when filler-word cutting is actually enabled.
  // When disabled, transcription is skipped server-side and the artifact is
  // an empty placeholder; rendering it confuses the user (looks like the
  // pipeline is doing word-level cutting when it isn't).
  const hasTranscript =
    Boolean(data.artifacts?.transcript) &&
    enabledFeatures.remove_filler_words === true;

  const audioEnhancementStep = data.service_status?.steps?.audio_enhancement;
  const audioStepMetrics =
    audioEnhancementStep &&
    typeof audioEnhancementStep === "object" &&
    "metrics" in audioEnhancementStep &&
    audioEnhancementStep.metrics &&
    typeof audioEnhancementStep.metrics === "object" &&
    !Array.isArray(audioEnhancementStep.metrics)
      ? (audioEnhancementStep.metrics as Record<string, unknown>)
      : null;
  const enhancedWavApiUrl = data.artifacts?.enhanced_audio
    ? `/api/jobs/${encodeURIComponent(jobId)}/artifacts/enhanced_audio`
    : null;
  const extractedWavApiUrl = data.artifacts?.extracted_audio
    ? `/api/jobs/${encodeURIComponent(jobId)}/artifacts/extracted_audio`
    : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Job</p>
          <h1 className="font-mono text-2xl text-zinc-100">{data.job_id}</h1>
          {isSmoothAudioPipeline ? (
            <p className="mt-1 text-xs text-emerald-200/85">
              Queue: vertical reframe + output audio (11 steps) · remove_dead_air ={" "}
              <span className="font-mono">{String(enabledFeatures.remove_dead_air ?? false)}</span>
              {" · "}
              enhance_audio ={" "}
              <span className="font-mono">{String(enabledFeatures.enhance_audio ?? false)}</span>
            </p>
          ) : null}
          {isDeadAirPipeline && !isAudioQualityPipeline ? (
            <p className="mt-1 text-xs text-amber-300">
              Queue: reframe + dead air
              {isLegacyDeadAirOnly
                ? " (12 steps — no audio prep before VAD)"
                : " (13 steps — conditioned audio then silence trim)"}
              {" · "}
              remove_dead_air ={" "}
              <span className="font-mono">
                {String(enabledFeatures.remove_dead_air ?? false)}
              </span>
              {" · "}
              enhance_audio ={" "}
              <span className="font-mono">{String(enabledFeatures.enhance_audio ?? false)}</span>
            </p>
          ) : null}
          {isAudioQualityPipeline ? (
            <p className="mt-1 text-xs text-amber-300">
              Queue: reframe + dead air + transcription / filler cuts (14 steps) · enhance_audio ={" "}
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

      <section
        className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4"
        aria-labelledby="job-output-options-heading"
      >
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Output</p>
          <h2 id="job-output-options-heading" className="text-base font-medium text-zinc-100">
            MP4 audio & options used for this job
          </h2>
        </div>
        <p className="whitespace-pre-line rounded-md border border-zinc-800/90 bg-zinc-950/70 px-3 py-2 text-xs leading-relaxed text-zinc-300">
          {buildUploadAlignedJobSummaryLines(data)}
        </p>
      </section>

      {error ? (
        <p className="rounded-md border border-amber-900/40 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
          Last refresh failed: {error}
        </p>
      ) : null}

      <StatusBoard
        status={data.service_status}
        pipeline={pipeline}
        isRefreshing={isRefreshing}
        lastSuccessfulRefreshAt={lastSuccessfulRefreshAt}
        refreshError={error}
        isTriggeringRun={isTriggeringRun}
      />
      {hasCutPlan ? (
        <CutPlanCard
          jobId={jobId}
          enabledFeatures={enabledFeatures}
          waveformAnalysisUrl={waveformAnalysisUrl}
          waveformCompareUrl={waveformCompareUrl}
        />
      ) : null}
      {hasTranscript ? <TranscriptCard jobId={jobId} /> : null}
      {data.artifacts.final_9x16 ? (
        <JobOutputPreview
          jobId={jobId}
          artifactKey="final_9x16"
          title="final_9x16.mp4"
          downloadName={`${jobId}_final_9x16.mp4`}
        />
      ) : null}
      <AudioOutputInsightPanel
        jobId={jobId}
        metrics={audioStepMetrics}
        enhancedArtifactUrl={enhancedWavApiUrl}
        extractedArtifactUrl={extractedWavApiUrl}
      />
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
