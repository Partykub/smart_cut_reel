"use client";

import { useEffect, useMemo, useState } from "react";

import {
  PIPELINE_ID_REFRAME_SMOOTH_AUDIO,
  STEP_ORDER_REFRAME_ONLY,
  STEP_ORDER_SMOOTH_AUDIO,
  type PipelineSummary,
  type ServiceStatus,
  type StepName,
  type StepState,
  type StepProgress,
  type StepStatus,
} from "@/lib/types";

const STATUS_BADGE: Record<StepStatus, string> = {
  pending: "border-zinc-700 bg-zinc-900 text-zinc-400",
  running: "border-sky-700 bg-sky-950/60 text-sky-200",
  success: "border-emerald-700 bg-emerald-950/60 text-emerald-200",
  failed: "border-red-800 bg-red-950/60 text-red-200",
};

const DEAD_AIR_CHAIN_STEPS = new Set<StepName>([
  "audio_extraction",
  "voice_activity_detection",
  "dead_air_cut_planning",
]);

const ENHANCEMENT_BADGE_STEPS = new Set<StepName>(["audio_enhancement"]);
const TRANSCRIPTION_BADGE_STEPS = new Set<StepName>(["transcription"]);

const DEFAULT_STEP_STATE: StepState = {
  status: "pending",
  started_at: null,
  finished_at: null,
};

const STEP_LABEL: Record<StepName, string> = {
  validation: "Validate input",
  media_metadata: "Inspect media",
  audio_extraction: "Extract audio (for VAD / cuts)",
  audio_enhancement: "Prep audio for VAD (analysis)",
  voice_activity_detection: "VAD — speech vs silence",
  transcription: "Transcribe (ASR — filler words)",
  dead_air_cut_planning: "Dead air — build keep/cut plan",
  proxy_frame_sampling: "Sample frames",
  body_detection: "Detect people",
  track_interpolation: "Stabilize tracks",
  reframe_planning: "Plan reframes",
  easing_smoothing: "Smooth motion",
  render_plan_compiler: "Compile render plan",
  ffmpeg_renderer: "Render outputs",
};

const HEARTBEAT_STALE_MS = 15_000;

export function StatusBoard({
  status,
  pipeline,
  isRefreshing,
  lastSuccessfulRefreshAt,
  refreshError,
  isTriggeringRun,
}: {
  status: ServiceStatus;
  pipeline?: PipelineSummary;
  isRefreshing: boolean;
  lastSuccessfulRefreshAt: number | null;
  refreshError: string | null;
  isTriggeringRun: boolean;
}) {
  const steps = useMemo((): StepName[] => {
    if (pipeline?.steps && pipeline.steps.length > 0) {
      return pipeline.steps as StepName[];
    }
    if (pipeline?.pipeline_id === PIPELINE_ID_REFRAME_SMOOTH_AUDIO) {
      return STEP_ORDER_SMOOTH_AUDIO;
    }
    return STEP_ORDER_REFRAME_ONLY;
  }, [pipeline?.pipeline_id, pipeline?.steps]);

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (status.status !== "running") {
      return;
    }

    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [status.status]);

  const completedCount = useMemo(
    () => steps.filter((step) => status.steps[step]?.status === "success").length,
    [status.steps, steps],
  );
  const failedCount = useMemo(
    () => steps.filter((step) => status.steps[step]?.status === "failed").length,
    [status.steps, steps],
  );
  const pendingCount =
    steps.length - completedCount - failedCount - (status.current_step ? 1 : 0);

  const runningStep = status.current_step ? status.steps[status.current_step] : null;
  const currentStep = status.current_step;
  const lastUpdateAgeMs = Math.max(0, now - parseTimestamp(status.updated_at));
  const isHeartbeatStale = status.status === "running" && lastUpdateAgeMs > HEARTBEAT_STALE_MS;
  const lastSuccessfulRefreshAgeMs = lastSuccessfulRefreshAt
    ? Math.max(0, now - lastSuccessfulRefreshAt)
    : null;
  const hasLiveRunningStep = status.status === "running" && status.current_step && runningStep;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-medium uppercase tracking-widest text-zinc-400">
          Pipeline
        </h2>
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${STATUS_BADGE[status.status]}`}
        >
          {status.status}
        </span>
        {pipeline?.pipeline_id ? (
          <span className="rounded-full border border-zinc-700 bg-zinc-900 px-2 py-0.5 font-mono text-[11px] text-zinc-400">
            {pipeline.pipeline_id}
          </span>
        ) : null}
        <span className="text-xs text-zinc-500">{steps.length} steps</span>
        {status.current_step ? (
          <span className="inline-flex items-center gap-2 rounded-full border border-sky-900/60 bg-sky-950/40 px-2.5 py-1 text-xs text-sky-100">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-sky-300" />
            </span>
            Active: {STEP_LABEL[status.current_step]}
          </span>
        ) : null}
        <span className="text-xs text-zinc-500">
          {completedCount}/{steps.length} complete
        </span>
        <span
          className={`inline-flex items-center rounded-full border px-2 py-1 text-xs ${
            isHeartbeatStale
              ? "border-amber-800 bg-amber-950/50 text-amber-200"
              : "border-zinc-800 bg-zinc-900 text-zinc-400"
          }`}
        >
          {isHeartbeatStale
            ? `No update for ${formatDuration(lastUpdateAgeMs)}`
            : `Updated ${formatRelativeTime(lastUpdateAgeMs)} ago`}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/80 p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Completed</p>
          <p className="mt-2 font-mono text-2xl text-zinc-50">
            {completedCount}
            <span className="ml-2 text-sm text-zinc-500">/ {steps.length}</span>
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            {pendingCount} pending, {failedCount} failed
          </p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/80 p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Live Sync</p>
          <p className="mt-2 flex items-center gap-2 text-sm text-zinc-100">
            <span
              className={`size-2 rounded-full ${
                refreshError
                  ? "bg-amber-300"
                  : isRefreshing
                    ? "animate-pulse bg-sky-300"
                    : "bg-emerald-300"
              }`}
            />
            {refreshError
              ? "showing cached status"
              : isRefreshing
                ? "refreshing now"
                : "connected"}
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            {lastSuccessfulRefreshAgeMs === null
              ? "waiting for first refresh"
              : `last success ${formatRelativeTime(lastSuccessfulRefreshAgeMs)} ago`}
          </p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/80 p-4 md:col-span-2">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Current Activity</p>
          <p className="mt-2 text-sm text-zinc-100">
            {hasLiveRunningStep && currentStep
              ? STEP_LABEL[currentStep]
              : isTriggeringRun
                ? "Trigger sent, waiting for pipeline to enter running state"
                : status.status === "success"
                  ? "Pipeline completed"
                  : status.status === "failed"
                    ? "Pipeline failed"
                    : "Waiting to start"}
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            {hasLiveRunningStep
              ? `frontend polls every 2s, backend heartbeat ${formatRelativeTime(lastUpdateAgeMs)} ago`
              : refreshError
                ? `latest refresh error: ${refreshError}`
                : "step updates appear here as soon as the orchestrator advances"}
          </p>
        </div>
      </div>

      {hasLiveRunningStep && currentStep ? (
        <div className="rounded-xl border border-sky-900/50 bg-gradient-to-r from-sky-950/70 via-zinc-950 to-zinc-950 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-sky-300/80">In Progress</p>
              <p className="mt-1 text-base font-medium text-sky-50">{STEP_LABEL[currentStep]}</p>
              <p className="mt-1 text-sm text-zinc-400">
                Step <span className="font-mono text-zinc-200">{currentStep}</span>
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">Running Time</p>
              <p className="mt-1 font-mono text-2xl text-zinc-50">
                {runningStep?.started_at
                  ? formatDuration(now - parseTimestamp(runningStep.started_at))
                  : "—"}
              </p>
              {runningStep?.started_at ? (
                <p className="mt-1 text-xs text-zinc-500">
                  started {formatTime(runningStep.started_at)}
                </p>
              ) : null}
            </div>
          </div>
          {status.progress ? (
            <StepProgressBar progress={status.progress} />
          ) : null}
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-900">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-400 via-cyan-300 to-sky-500 transition-[width] duration-500"
              style={{ width: `${(completedCount / steps.length) * 100}%` }}
            />
          </div>
        </div>
      ) : null}

      {isTriggeringRun && status.status !== "running" ? (
        <div className="rounded-xl border border-cyan-900/50 bg-cyan-950/30 p-4 text-sm text-cyan-100">
          <div className="flex items-center gap-3">
            <span className="relative flex size-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-300 opacity-75" />
              <span className="relative inline-flex size-3 rounded-full bg-cyan-200" />
            </span>
            Pipeline trigger sent. Waiting for the orchestrator to mark the first step as running.
          </div>
        </div>
      ) : null}

      <ol className="space-y-2">
        {steps.map((step, index) => {
          const state = status.steps[step] ?? DEFAULT_STEP_STATE;
          const isCurrent = status.current_step === step;
          const isDeadAirChainStep = DEAD_AIR_CHAIN_STEPS.has(step);
          const isEnhancementBadgeStep = ENHANCEMENT_BADGE_STEPS.has(step);
          const isTranscriptionBadgeStep = TRANSCRIPTION_BADGE_STEPS.has(step);
          return (
            <li
              key={step}
              className={`flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 ${STATUS_BADGE[state.status]} ${isCurrent ? "ring-1 ring-sky-500/50" : ""}`}
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-zinc-500">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm">{step}</span>
                    {isDeadAirChainStep ? (
                      <span className="rounded-full border border-violet-800 bg-violet-950/40 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wider text-violet-200">
                        audio
                      </span>
                    ) : null}
                    {isEnhancementBadgeStep ? (
                      <span className="rounded-full border border-amber-800 bg-amber-950/40 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wider text-amber-200">
                        enhance
                      </span>
                    ) : null}
                    {isTranscriptionBadgeStep ? (
                      <span className="rounded-full border border-sky-800 bg-sky-950/40 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wider text-sky-200">
                        ASR
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs text-zinc-500">{STEP_LABEL[step]}</p>
                  {step === "audio_enhancement" && state.metrics ? (
                    <p className="mt-1 max-w-xl text-[11px] leading-snug text-zinc-400">
                      {formatAudioEnhancementMetrics(state.metrics)}
                    </p>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span className="font-medium uppercase tracking-wider">{state.status}</span>
                {isCurrent ? (
                  <span className="inline-flex items-center gap-2 rounded-full border border-sky-800/70 bg-sky-900/30 px-2 py-1 text-sky-100">
                    <span className="size-2 animate-pulse rounded-full bg-sky-300" />
                    working now
                  </span>
                ) : null}
                {state.started_at ? (
                  <span className="text-zinc-500">start {formatTime(state.started_at)}</span>
                ) : null}
                {state.finished_at ? (
                  <span className="text-zinc-500">end {formatTime(state.finished_at)}</span>
                ) : null}
                {state.started_at ? (
                  <span className="text-zinc-500">
                    {state.finished_at
                      ? `took ${formatDuration(parseTimestamp(state.finished_at) - parseTimestamp(state.started_at))}`
                      : `elapsed ${formatDuration(now - parseTimestamp(state.started_at))}`}
                  </span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      {status.warnings.length > 0 ? (
        <details
          open
          className="rounded-md border border-amber-900/40 bg-amber-950/30 p-3"
        >
          <summary className="cursor-pointer text-sm font-medium text-amber-200">
            Warnings ({status.warnings.length})
          </summary>
          <ul className="mt-2 space-y-1 text-sm text-amber-100">
            {status.warnings.map((warning, idx) => (
              <li key={`${warning.code}-${idx}`} className="font-mono">
                <span className="text-amber-300">[{warning.step}]</span> {warning.code}:{" "}
                {warning.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {status.errors.length > 0 ? (
        <div className="rounded-md border border-red-900/40 bg-red-950/40 p-3">
          <p className="text-sm font-medium text-red-200">Errors</p>
          <ul className="mt-2 space-y-1 text-sm text-red-100">
            {status.errors.map((message, idx) => (
              <li key={idx} className="font-mono">
                {message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString();
}

function parseTimestamp(value: string | null): number {
  if (!value) return Date.now();
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? Date.now() : timestamp;
}

function formatDuration(valueMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(valueMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
  }

  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  }

  return `${seconds}s`;
}

function formatAudioEnhancementMetrics(metrics: Record<string, unknown>): string {
  const parts: string[] = [];
  const peakPre = metrics.peak_sample_dbfs_pre_peak_force;
  const peak = metrics.peak_sample_dbfs;
  if (typeof peakPre === "number" && typeof peak === "number" && Math.abs(peakPre - peak) > 0.02) {
    parts.push(`Peak (astats): ${peakPre.toFixed(2)} → ${peak.toFixed(2)} dBFS`);
  } else if (typeof peak === "number") {
    parts.push(`Peak (astats): ${peak.toFixed(2)} dBFS`);
  } else if (peak === null) {
    parts.push("Peak (astats): —");
  }
  const low = metrics.peak_level_window_low_dbfs;
  const high = metrics.peak_level_window_high_dbfs;
  const within = metrics.peak_within_window;
  if (typeof low === "number" && typeof high === "number") {
    parts.push(`window ${low.toFixed(1)}…${high.toFixed(1)} dBFS`);
  }
  if (typeof within === "boolean") {
    parts.push(within ? "inside window" : "outside window");
  }
  if (metrics.peak_force_applied === true) {
    const g = metrics.peak_force_gain_db_total;
    parts.push(
      typeof g === "number" ? `force gain ${g.toFixed(2)} dB` : "peak force applied",
    );
  }
  return parts.join(" · ");
}

function formatRelativeTime(valueMs: number): string {
  if (valueMs < 1000) return "just now";
  if (valueMs < 60_000) return `${Math.floor(valueMs / 1000)}s`;
  if (valueMs < 3_600_000) return `${Math.floor(valueMs / 60_000)}m`;
  return `${Math.floor(valueMs / 3_600_000)}h`;
}

function formatSeconds(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

function StepProgressBar({ progress }: { progress: StepProgress }) {
  return (
    <div className="mt-4 rounded-lg border border-sky-900/30 bg-zinc-950/60 p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-zinc-400">
        <span className="font-mono">
          {formatSeconds(progress.current_seconds)}
          <span className="text-zinc-600"> / </span>
          {formatSeconds(progress.total_seconds)}
        </span>
        <span className="font-mono text-sky-300">{progress.percent.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-sky-500 to-cyan-400 transition-[width] duration-700"
          style={{ width: `${Math.min(100, progress.percent)}%` }}
        />
      </div>
    </div>
  );
}
