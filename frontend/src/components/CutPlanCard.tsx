"use client";

import { useEffect, useMemo, useState } from "react";

import { useAudioWaveformPeaks } from "@/hooks/useAudioWaveformPeaks";
import { useScrubTime } from "@/hooks/useScrubTime";
import type { CutPlan, EnabledFeatures, VadTimelineSegment } from "@/lib/types";
import { removedGapsFromKeepSegments } from "@/lib/timelineRegions";

import { ScrubHoverOverlay } from "./ScrubHoverOverlay";
import { WaveformStrip } from "./WaveformStrip";

interface CutPlanCardProps {
  jobId: string;
  enabledFeatures: EnabledFeatures;
  /** WAV URL for analysis track (prefer enhanced when present). */
  waveformAnalysisUrl: string | null;
  /** Raw extracted WAV when `waveformAnalysisUrl` is enhanced — same overlays, stacked for A/B. */
  waveformCompareUrl?: string | null;
}

export function CutPlanCard({
  jobId,
  enabledFeatures,
  waveformAnalysisUrl,
  waveformCompareUrl = null,
}: CutPlanCardProps) {
  const [plan, setPlan] = useState<CutPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [vadDebug, setVadDebug] = useState<{
    segments: VadTimelineSegment[];
    model: string | null;
  } | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    const url = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/vad_segments`;

    void (async () => {
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) {
          if (!cancelled) setVadDebug(null);
          return;
        }
        const body = (await response.json()) as {
          model?: string;
          segments?: unknown[];
        };
        if (cancelled) return;
        const raw = Array.isArray(body.segments) ? body.segments : [];
        const segments: VadTimelineSegment[] = [];
        for (const row of raw) {
          if (!row || typeof row !== "object") continue;
          const r = row as Record<string, unknown>;
          const typ = r.type === "silence" ? "silence" : r.type === "speech" ? "speech" : null;
          if (!typ) continue;
          const start = Number(r.start);
          const end = Number(r.end);
          if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
          segments.push({ start, end, type: typ });
        }
        setVadDebug(
          segments.length > 0
            ? {
                segments,
                model: typeof body.model === "string" ? body.model : null,
              }
            : null,
        );
      } catch {
        if (!cancelled) setVadDebug(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const analysisPeaks = useAudioWaveformPeaks(waveformAnalysisUrl);
  const comparePeaks = useAudioWaveformPeaks(waveformCompareUrl);
  const hasWaveformCompare = Boolean(waveformCompareUrl);
  const isEnhancedPrimary = waveformAnalysisUrl?.includes("enhanced_audio") === true;
  const analysisLabel = isEnhancedPrimary
    ? hasWaveformCompare
      ? "Prep output (enhanced WAV)"
      : "Analysis waveform"
    : "Source waveform";
  const analysisSub = isEnhancedPrimary
    ? hasWaveformCompare
      ? "FFmpeg chain used as VAD input — compare the strip below to the raw extract."
      : "FFmpeg prep + loudness — matches VAD input (not the final MP4 mix)."
    : "From extracted WAV — closest to the uploaded source track.";

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
        <div className="text-right text-xs text-zinc-500">
          <p className="font-mono text-zinc-400">
            ยาวต้นทาง {plan.source_duration_seconds.toFixed(2)} วิ. · {plan.metrics.cut_count}{" "}
            คัต
          </p>
          <p className="text-zinc-600">
            เหลือ {(plan.metrics.compression_ratio * 100).toFixed(1)}% ของต้นทาง
          </p>
          {typeof plan.metrics.removed_filler_seconds === "number" &&
          plan.metrics.removed_filler_seconds > 0 ? (
            <p className="text-amber-300/95">
              ตัดคำ filler{" "}
              <span className="font-mono">
                {plan.metrics.removed_filler_seconds.toFixed(2)} วิ.
              </span>
              {plan.metrics.filler_word_count
                ? ` (${plan.metrics.filler_word_count} คำ)`
                : null}
            </p>
          ) : null}
        </div>
      </header>

      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-md border border-zinc-800/80 bg-zinc-950/45 px-2 py-1 text-[11px] leading-tight text-zinc-400">
        <span className="tabular-nums">
          <span className="text-emerald-200/85">เก็บ</span>{" "}
          <span className="font-mono font-semibold text-emerald-100/95">
            {plan.metrics.total_kept_seconds.toFixed(2)}
          </span>{" "}
          <span className="text-emerald-200/55">วิ.</span>
        </span>
        <span className="text-zinc-600" aria-hidden>
          ·
        </span>
        <span className="tabular-nums">
          <span className="text-rose-200/85">ตัด</span>{" "}
          <span className="font-mono font-semibold text-rose-100/95">
            {plan.metrics.total_removed_seconds.toFixed(2)}
          </span>{" "}
          <span className="text-rose-200/55">วิ.</span>
        </span>
        {typeof plan.metrics.removed_silence_seconds === "number" &&
        plan.metrics.removed_silence_seconds > 0 ? (
          <>
            <span className="text-zinc-600" aria-hidden>
              ·
            </span>
            <span className="tabular-nums text-zinc-500">
              เงียบ{" "}
              <span className="font-mono text-rose-200/75">
                {plan.metrics.removed_silence_seconds.toFixed(2)}
              </span>{" "}
              วิ.
            </span>
          </>
        ) : null}
      </div>

      {vadDebug && vadDebug.segments.length > 0 ? (
        <p className="text-[10px] leading-snug text-zinc-500">
          <span className="font-semibold text-zinc-400">Debug Silero (VAD)</span>
          {vadDebug.model ? (
            <span className="ml-1 font-mono text-zinc-500">· {vadDebug.model}</span>
          ) : null}
          {" · "}
          <span className="text-amber-200/80">พูด</span> = พื้นเหลืองอ่อน ·{" "}
          <span className="text-sky-200/85">เงียบ</span> = ฟ้าเส้นตั้ง (ยังไม่ใช่ “จะตัด” เอง) · แดงลาย = ช่วงที่แผนตัดออก · เขียว = เก็บใน output
          {" · "}
          ตัดเงียบเมื่อยาว ≥{" "}
          <span className="font-mono text-zinc-300">
            {plan.config_used.silence_threshold_seconds.toFixed(2)}
          </span>{" "}
          วิ. (ค่าในงานนี้จาก cut plan)
        </p>
      ) : null}

      {waveformAnalysisUrl ? (
        <div className="space-y-3">
          <WaveformStrip
            key={waveformAnalysisUrl}
            peaks={analysisPeaks.peaks}
            height={56}
            variant="timeline"
            segments={segments}
            vadSegments={vadDebug?.segments ?? null}
            totalDurationSeconds={total}
            label={analysisLabel}
            sublabel={analysisSub}
            state={analysisPeaks.state}
            errorMessage={analysisPeaks.error}
          />
          {waveformCompareUrl ? (
            <WaveformStrip
              key={waveformCompareUrl}
              peaks={comparePeaks.peaks}
              height={56}
              variant="timeline"
              visualTone="zinc"
              segments={segments}
              vadSegments={vadDebug?.segments ?? null}
              totalDurationSeconds={total}
              label="Extracted waveform (pre-prep)"
              sublabel="Same timeline and overlays — compare noise floor and dynamics to the enhanced strip above."
              state={comparePeaks.state}
              errorMessage={comparePeaks.error}
            />
          ) : null}
        </div>
      ) : null}

      <Timeline
        segments={segments}
        totalDuration={total}
        featureEnabled={featureEnabled}
        vadSegments={vadDebug?.segments ?? null}
      />

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
  featureEnabled,
  vadSegments,
}: {
  segments: { source_start: number; source_end: number }[];
  totalDuration: number;
  featureEnabled: boolean;
  vadSegments?: VadTimelineSegment[] | null;
}) {
  const scrub = useScrubTime(totalDuration);

  const removed = useMemo(() => {
    if (!featureEnabled || !segments.length) return [];
    return removedGapsFromKeepSegments(segments, totalDuration);
  }, [featureEnabled, segments, totalDuration]);

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
        Kept segments (source time)
      </p>
      <div
        className="relative cursor-crosshair rounded-lg border border-zinc-800/90 bg-zinc-950/30"
        onMouseMove={scrub.onMouseMove}
        onMouseLeave={scrub.onMouseLeave}
      >
        <div className="relative h-8 overflow-hidden rounded-t-lg bg-zinc-900/90 shadow-inner">
          {vadSegments && vadSegments.length > 0 ? (
            <div className="pointer-events-none absolute inset-0 z-0" aria-hidden>
              {vadSegments.map((seg, idx) => {
                const t0 = Math.max(0, seg.start);
                const t1 = Math.min(totalDuration, seg.end);
                if (t1 <= t0) return null;
                const startPct = clampPct((t0 / totalDuration) * 100);
                const widthPct = clampPct(((t1 - t0) / totalDuration) * 100);
                const isSilence = seg.type === "silence";
                return (
                  <div
                    key={`tl-vad-${idx}-${t0}-${isSilence ? "s" : "p"}`}
                    className={
                      isSilence
                        ? "absolute bottom-0 top-0 bg-sky-500/[0.16] ring-1 ring-inset ring-sky-400/25"
                        : "absolute bottom-0 top-0 bg-amber-400/[0.1]"
                    }
                    style={{
                      left: `${startPct}%`,
                      width: `${Math.max(widthPct, 0.06)}%`,
                      ...(isSilence
                        ? {
                            backgroundImage:
                              "repeating-linear-gradient(90deg, transparent, transparent 4px, rgba(56,189,248,0.14) 4px, rgba(56,189,248,0.14) 5px)",
                          }
                        : {}),
                    }}
                  />
                );
              })}
            </div>
          ) : null}
          {removed.map((gap, idx) => {
            const startPct = clampPct((gap.start / totalDuration) * 100);
            const widthPct = clampPct(((gap.end - gap.start) / totalDuration) * 100);
            const rangeLabel = `${gap.start.toFixed(2)} – ${gap.end.toFixed(2)} วิ.`;
            return (
              <div
                key={`tl-rm-${idx}`}
                className="absolute bottom-0 top-0 z-[1] bg-rose-950/35 ring-1 ring-inset ring-rose-500/30"
                style={{
                  left: `${startPct}%`,
                  width: `${widthPct}%`,
                  backgroundImage:
                    "repeating-linear-gradient(-45deg, transparent, transparent 3px, rgba(251,113,133,0.18) 3px, rgba(251,113,133,0.18) 4px)",
                }}
              >
                {widthPct >= 4 ? (
                  <span
                    className={`pointer-events-none absolute inset-0 flex items-center justify-center px-0.5 text-center font-semibold tabular-nums ${
                      widthPct >= 8 ? "text-[9px]" : "text-[8px] leading-tight"
                    }`}
                  >
                    <span className="truncate rounded px-1 py-px text-rose-50 shadow-[0_1px_2px_rgba(0,0,0,0.65)] ring-1 ring-rose-400/35 bg-zinc-950/88 [text-shadow:0_0_8px_rgba(0,0,0,0.9)]">
                      {rangeLabel}
                    </span>
                  </span>
                ) : null}
              </div>
            );
          })}
          {segments.map((seg, idx) => {
            const startPct = clampPct((seg.source_start / totalDuration) * 100);
            const widthPct = clampPct(
              ((seg.source_end - seg.source_start) / totalDuration) * 100,
            );
            const rangeLabel = `${seg.source_start.toFixed(2)} – ${seg.source_end.toFixed(2)} วิ.`;
            return (
              <div
                key={`bar-${idx}`}
                className="absolute top-0 bottom-0 z-[2] bg-gradient-to-b from-emerald-400/90 to-emerald-600/85 shadow-[0_0_12px_rgba(16,185,129,0.25)] transition hover:from-emerald-300 hover:to-emerald-500"
                style={{ left: `${startPct}%`, width: `${widthPct}%` }}
              >
                {widthPct >= 4 ? (
                  <span
                    className={`pointer-events-none absolute inset-0 flex items-center justify-center px-0.5 text-center font-semibold tabular-nums text-emerald-950/90 drop-shadow-sm ${
                      widthPct >= 8 ? "text-[9px]" : "text-[8px] leading-tight"
                    }`}
                  >
                    <span className="truncate">{rangeLabel}</span>
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
        <ScrubHoverOverlay
          ratio={scrub.ratio}
          totalSeconds={totalDuration}
          removedGaps={featureEnabled && removed.length ? removed : undefined}
        />
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
