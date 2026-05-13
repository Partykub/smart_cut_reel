"use client";

import { useId, useMemo } from "react";

import { useScrubTime } from "@/hooks/useScrubTime";
import { removedGapsFromKeepSegments } from "@/lib/timelineRegions";
import type { CutPlanSegment, VadTimelineSegment } from "@/lib/types";

import { ScrubHoverOverlay } from "./ScrubHoverOverlay";

type WaveformVariant = "timeline" | "output";
type WaveformVisualTone = "emerald" | "zinc";

/**
 * SVG mirrored waveform with keep / removed overlays, time ruler, and hover scrub readout.
 */
export function WaveformStrip({
  peaks,
  height = 52,
  variant = "timeline",
  visualTone = "emerald",
  segments,
  vadSegments,
  totalDurationSeconds,
  label,
  sublabel,
  state,
  errorMessage,
  interactive = true,
}: {
  peaks: number[] | null;
  height?: number;
  variant?: WaveformVariant;
  /** Second strip in A/B pairs: cooler path so it reads as “reference / raw”. */
  visualTone?: WaveformVisualTone;
  segments?: CutPlanSegment[];
  /** Raw VAD timeline (speech/silence) for debug overlay under cut-plan strips. */
  vadSegments?: VadTimelineSegment[] | null;
  totalDurationSeconds: number;
  label: string;
  sublabel?: string;
  state: "idle" | "loading" | "ready" | "error";
  errorMessage?: string | null;
  /** Pointer scrub + tooltip on waveform + ruler area. */
  interactive?: boolean;
}) {
  const gid = useId();
  const gradId = `${gid}-wf-grad`;
  const glowId = `${gid}-wf-glow`;
  const isZincTone = visualTone === "zinc";

  const scrub = useScrubTime(totalDurationSeconds);

  const removedIntervals = useMemo(() => {
    if (!segments?.length || totalDurationSeconds <= 0) return [];
    return removedGapsFromKeepSegments(segments, totalDurationSeconds);
  }, [segments, totalDurationSeconds]);

  const w = Math.max(peaks?.length ?? 1, 1);
  const mid = height / 2;
  const amp = mid - 4;

  const pathD = useMemo(() => {
    if (!peaks?.length) return "";
    if (peaks.length === 1) {
      const p = peaks[0]!;
      const y0 = mid - p * amp;
      const y1 = mid + p * amp;
      return `M 0 ${y0.toFixed(3)} L ${w} ${y0.toFixed(3)} L ${w} ${y1.toFixed(3)} L 0 ${y1.toFixed(3)} Z`;
    }
    const step = w / (peaks.length - 1);
    const top: string[] = [];
    const bottom: string[] = [];
    peaks.forEach((p, i) => {
      const x = i * step;
      const y = mid - p * amp;
      top.push(`${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(3)}`);
    });
    for (let i = peaks.length - 1; i >= 0; i--) {
      const x = i * step;
      const y = mid + peaks[i]! * amp;
      bottom.push(`L ${x.toFixed(2)} ${y.toFixed(3)}`);
    }
    return `${top.join(" ")} ${bottom.join(" ")} Z`;
  }, [peaks, w, mid, amp, height]);

  const isTimeline = variant === "timeline";
  const scrubHandlers =
    interactive && totalDurationSeconds > 0 && state !== "error"
      ? {
          onMouseMove: scrub.onMouseMove,
          onMouseLeave: scrub.onMouseLeave,
        }
      : {};

  return (
    <div
      className={
        isTimeline
          ? "relative overflow-visible rounded-xl border border-zinc-800/90 bg-gradient-to-b from-zinc-900/90 to-zinc-950 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
          : "relative overflow-visible rounded-xl border border-zinc-800/80 bg-zinc-950/80 shadow-inner"
      }
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            "linear-gradient(105deg, transparent 0%, rgba(16,185,129,0.5) 45%, transparent 70%)",
        }}
      />

      {vadSegments && vadSegments.length > 0 && totalDurationSeconds > 0 ? (
        <div
          className="pointer-events-none absolute inset-0 z-0"
          aria-hidden
          title="Silero VAD: speech vs silence on the same timeline as the waveform"
        >
          {vadSegments.map((seg, idx) => {
            const t0 = Math.max(0, seg.start);
            const t1 = Math.min(totalDurationSeconds, seg.end);
            if (t1 <= t0) return null;
            const left = (t0 / totalDurationSeconds) * 100;
            const width = Math.max(((t1 - t0) / totalDurationSeconds) * 100, 0.06);
            const isSilence = seg.type === "silence";
            return (
              <div
                key={`vad-${idx}-${t0}-${isSilence ? "s" : "p"}`}
                className={
                  isSilence
                    ? "absolute bottom-0 top-0 bg-sky-500/[0.14] ring-1 ring-inset ring-sky-400/20"
                    : "absolute bottom-0 top-0 bg-amber-400/[0.09]"
                }
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  ...(isSilence
                    ? {
                        backgroundImage:
                          "repeating-linear-gradient(90deg, transparent, transparent 5px, rgba(56,189,248,0.12) 5px, rgba(56,189,248,0.12) 6px)",
                      }
                    : {}),
                }}
              />
            );
          })}
        </div>
      ) : null}

      {removedIntervals.length > 0 && totalDurationSeconds > 0 ? (
        <div className="pointer-events-none absolute inset-0 z-[1]">
          {removedIntervals.map((gap, idx) => {
            const left = (gap.start / totalDurationSeconds) * 100;
            const width = Math.max(
              ((gap.end - gap.start) / totalDurationSeconds) * 100,
              0.08,
            );
            return (
              <div
                key={`rm-${idx}-${gap.start}`}
                className="absolute bottom-0 top-0 bg-rose-950/[0.28] ring-1 ring-inset ring-rose-500/25"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  backgroundImage:
                    "repeating-linear-gradient(-45deg, transparent, transparent 4px, rgba(251,113,133,0.16) 4px, rgba(251,113,133,0.16) 5px)",
                }}
              />
            );
          })}
        </div>
      ) : null}

      {segments && totalDurationSeconds > 0 ? (
        <div className="pointer-events-none absolute inset-0 z-[2]">
          {segments.map((seg, idx) => {
            const left = (seg.source_start / totalDurationSeconds) * 100;
            const width = Math.max(
              ((seg.source_end - seg.source_start) / totalDurationSeconds) * 100,
              0.15,
            );
            return (
              <div
                key={`keep-${idx}-${seg.source_start}`}
                className="absolute bottom-0 top-0 bg-emerald-500/[0.14]"
                style={{ left: `${left}%`, width: `${width}%` }}
              />
            );
          })}
        </div>
      ) : null}

      <div className="relative z-10 flex items-start justify-between gap-3 px-3 pt-2.5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
            {label}
          </p>
          {sublabel ? (
            <p className="text-[11px] leading-snug text-zinc-500">{sublabel}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-0.5 text-right">
          {state === "loading" ? (
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-200/90 motion-safe:animate-pulse">
              Decoding…
            </span>
          ) : null}
          {state === "error" ? (
            <span className="rounded-full border border-amber-700/50 bg-amber-950/50 px-2 py-0.5 text-[10px] text-amber-200">
              Unavailable
            </span>
          ) : null}
        </div>
      </div>

      <div
        className={`relative z-10 ${interactive && state !== "error" ? "cursor-crosshair" : ""}`}
        {...scrubHandlers}
      >
        <div className="relative px-2 pb-2 pt-1">
          {state === "error" && errorMessage ? (
            <p className="px-1 pb-2 text-[11px] text-amber-200/90">{errorMessage}</p>
          ) : null}

          {state === "loading" || state === "idle" ? (
            <div
              className="flex w-full items-end gap-px px-1 opacity-40"
              style={{ height }}
              aria-hidden
            >
              {Array.from({ length: 48 }).map((_, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-sm bg-zinc-600 motion-safe:animate-pulse"
                  style={{
                    height: `${20 + ((i * 13) % 55)}%`,
                    animationDelay: `${i * 35}ms`,
                  }}
                />
              ))}
            </div>
          ) : null}

          {state === "ready" && peaks?.length ? (
            <svg
              width="100%"
              height={height}
              viewBox={`0 0 ${w} ${height}`}
              preserveAspectRatio="none"
              className="block w-full"
              role="img"
              aria-label={label}
            >
              <defs>
                <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="0%">
                  {isZincTone ? (
                    <>
                      <stop offset="0%" stopColor="rgba(148,163,184,0.35)" />
                      <stop offset="40%" stopColor="rgba(100,116,139,0.82)" />
                      <stop offset="100%" stopColor="rgba(148,163,184,0.4)" />
                    </>
                  ) : (
                    <>
                      <stop offset="0%" stopColor="rgba(52,211,153,0.35)" />
                      <stop offset="35%" stopColor="rgba(16,185,129,0.85)" />
                      <stop offset="100%" stopColor="rgba(45,212,191,0.45)" />
                    </>
                  )}
                </linearGradient>
                <filter id={glowId} x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="1.2" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <path
                d={pathD}
                fill={`url(#${gradId})`}
                stroke={
                  isZincTone ? "rgba(148,163,184,0.45)" : "rgba(167,243,208,0.35)"
                }
                strokeWidth={0.6}
                filter={`url(#${glowId})`}
                vectorEffect="non-scaling-stroke"
              />
              <line
                x1={0}
                y1={mid}
                x2={w}
                y2={mid}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth={0.5}
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          ) : null}

          {state === "ready" && !peaks?.length ? (
            <p className="px-1 text-[11px] text-zinc-500">No samples decoded.</p>
          ) : null}
        </div>

        {interactive ? (
          <ScrubHoverOverlay
            ratio={scrub.ratio}
            totalSeconds={totalDurationSeconds}
            removedGaps={removedIntervals.length ? removedIntervals : undefined}
          />
        ) : null}
      </div>
    </div>
  );
}
