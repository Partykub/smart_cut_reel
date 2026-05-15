"use client";

import { useMemo } from "react";

import { useAudioWaveformPeaks } from "@/hooks/useAudioWaveformPeaks";
import { peakDbfsWithinWindowRounded } from "@/lib/audioDbfsGuide";
import type { CutPlanSegment } from "@/lib/types";

import { WaveformStrip } from "./WaveformStrip";
import { PeakDbfsWindowMeter } from "./PeakDbfsWindowMeter";

function fmtNum(v: unknown, digits = 2): string {
  if (typeof v === "number" && Number.isFinite(v)) return v.toFixed(digits);
  return "—";
}

function fmtBool(v: unknown): string {
  if (v === true) return "ใช่";
  if (v === false) return "ไม่";
  return "—";
}

export function AudioOutputInsightPanel({
  jobId,
  metrics,
  enhancedArtifactUrl,
  extractedArtifactUrl,
}: {
  jobId: string;
  metrics: Record<string, unknown> | null | undefined;
  enhancedArtifactUrl: string | null;
  extractedArtifactUrl: string | null;
}) {
  const hasMetrics = metrics != null && typeof metrics === "object" && !Array.isArray(metrics);
  const primaryUrl = enhancedArtifactUrl;
  const compareUrl =
    extractedArtifactUrl && enhancedArtifactUrl ? extractedArtifactUrl : null;

  const primaryPeaks = useAudioWaveformPeaks(primaryUrl);
  const comparePeaks = useAudioWaveformPeaks(compareUrl);

  const primaryDuration = primaryPeaks.durationSeconds ?? 0;
  const compareDuration = comparePeaks.durationSeconds ?? 0;

  const primarySegments: CutPlanSegment[] | undefined = useMemo(() => {
    const d = Math.max(primaryDuration, 0.001);
    return [{ source_start: 0, source_end: d }];
  }, [primaryDuration]);

  const compareSegments: CutPlanSegment[] | undefined = useMemo(() => {
    const d = Math.max(compareDuration, 0.001);
    return [{ source_start: 0, source_end: d }];
  }, [compareDuration]);

  const peakFromMetrics = useMemo(() => {
    if (metrics == null || typeof metrics !== "object" || Array.isArray(metrics)) {
      return {
        post: undefined as number | undefined,
        pre: undefined as number | undefined,
        withinPreBool: undefined as boolean | undefined,
      };
    }
    const m = metrics as Record<string, unknown>;
    const num = (v: unknown): number | undefined =>
      typeof v === "number" && Number.isFinite(v) ? v : undefined;
    return {
      post: num(m.peak_sample_dbfs),
      pre: num(m.peak_sample_dbfs_pre_peak_force),
      withinPreBool:
        typeof m.peak_within_window_pre_peak_force === "boolean"
          ? m.peak_within_window_pre_peak_force
          : undefined,
    };
  }, [metrics]);

  const hasWaveform = Boolean(primaryUrl);
  if (!hasMetrics && !hasWaveform) {
    return null;
  }

  const peak = hasMetrics ? peakFromMetrics.post : undefined;
  const peakPre = hasMetrics ? peakFromMetrics.pre : undefined;
  const within = hasMetrics ? metrics!.peak_within_window : undefined;
  const low = hasMetrics ? metrics!.peak_level_window_low_dbfs : undefined;
  const high = hasMetrics ? metrics!.peak_level_window_high_dbfs : undefined;
  const inLu = hasMetrics ? metrics!.input_lufs : undefined;
  const outLu = hasMetrics ? metrics!.output_lufs : undefined;
  const tgt = hasMetrics ? metrics!.target_lufs : undefined;
  const lnOn = hasMetrics ? metrics!.loudness_normalization_enabled : undefined;
  const truePeakCfg = hasMetrics ? metrics!.true_peak_db : undefined;
  const lraCfg = hasMetrics ? metrics!.loudness_range : undefined;
  const forced = hasMetrics ? metrics!.peak_force_applied : undefined;
  const gainTot = hasMetrics ? metrics!.peak_force_gain_db_total : undefined;

  const deltaVsTarget =
    typeof outLu === "number" && typeof tgt === "number" && Number.isFinite(outLu) && Number.isFinite(tgt)
      ? outLu - tgt
      : null;

  /** Post column: rounded 3dp window (aligns with fmtNum when outside/forced); raw float can be e.g. −13.9996 > −14 but show −14.000. */
  const withinPostResolved: boolean | undefined =
    typeof peak === "number" &&
    typeof low === "number" &&
    typeof high === "number" &&
    Number.isFinite(peak) &&
    Number.isFinite(low) &&
    Number.isFinite(high)
      ? peakDbfsWithinWindowRounded(peak, low, high, 3)
      : typeof within === "boolean"
        ? within
        : undefined;

  const withinLabel =
    withinPostResolved === true
      ? "อยู่ในช่วงที่ตั้งไว้"
      : withinPostResolved === false
        ? "อยู่นอกช่วงที่ตั้งไว้"
        : null;

  const withinPreResolved = hasMetrics ? peakFromMetrics.withinPreBool : undefined;
  const withinPreLabel =
    withinPreResolved === true
      ? "อยู่ในช่วงที่ตั้งไว้"
      : withinPreResolved === false
        ? "อยู่นอกช่วงที่ตั้งไว้"
        : null;

  const showPeakMeter =
    typeof low === "number" &&
    typeof high === "number" &&
    Number.isFinite(low) &&
    Number.isFinite(high) &&
    (typeof peakPre === "number" || typeof peak === "number");

  const peakDelta =
    typeof peakPre === "number" && typeof peak === "number" && Number.isFinite(peakPre) && Number.isFinite(peak)
      ? Math.abs(peakPre - peak)
      : 0;
  const showSplitPeakRows = typeof peakPre === "number" && typeof peak === "number" && peakDelta > 0.005;

  const peakDigits = forced === true || withinPostResolved === false ? 3 : 2;

  const singleRowFootnote = showSplitPeakRows
    ? ""
    : forced === true &&
        typeof gainTot === "number" &&
        Math.abs(gainTot) > 1e-6 &&
        typeof peakPre !== "number"
      ? "ใช้ peak-force แล้ว แต่ metrics ไม่มีค่า astats ก่อน force (job เก่า / worker เก่า หรือ astats ล้มเหลว) — รัน job ใหม่หลัง restart audio_enhancement"
      : forced === true &&
          typeof peakPre === "number" &&
          typeof peak === "number" &&
          peakDelta <= 0.005
        ? "มี peak-force แต่ค่า astats ก่อน/หลังใกล้กันมากในมิติที่แสดง — แถบ dBFS อาจเห็นจุดเดียว"
        : "ก่อนและหลัง peak-force เท่ากัน (ไม่มี gain) — ตรงกับ waveform";

  const hasPeakPre = typeof peakPre === "number" && Number.isFinite(peakPre);
  const hasPeakPost = typeof peak === "number" && Number.isFinite(peak);
  const peakDeltaSigned =
    hasPeakPre && hasPeakPost ? (peak as number) - (peakPre as number) : null;

  return (
    <section
      className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4"
      aria-labelledby="audio-output-insight-heading"
    >
      <div>
        <p className="text-xs uppercase tracking-widest text-zinc-500">Audio</p>
        <h2 id="audio-output-insight-heading" className="text-lg font-medium text-zinc-100">
          เสียงหลังประมวลผล (ตัวเลข + waveform)
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
          ตัวเลขมาจากขั้น <span className="font-mono text-zinc-400">audio_enhancement</span> — peak ใช้ ffmpeg{" "}
          <span className="font-mono">astats</span> (ไม่เท่ากับทุกมิเตอร์ QC) · waveform โหลดจาก WAV ที่ mux
          ใช้เป็นฐานเดียวกับเสียงใน MP4 เมื่อเลือก mux จาก enhanced
        </p>
      </div>

      {hasMetrics ? (
        <>
          <div className="rounded-lg border border-sky-900/45 bg-gradient-to-br from-sky-950/50 to-zinc-950/80 px-4 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-sky-300/95">
              LUFS — integrated loudness
            </p>
            <p className="mt-1 text-xs leading-relaxed text-zinc-500">
              ค่า <span className="font-mono text-zinc-400">input_lufs</span> /{" "}
              <span className="font-mono text-zinc-400">output_lufs</span> มาจาก JSON ของ ffmpeg{" "}
              <span className="font-mono">loudnorm</span> ใน stderr — เป็น{" "}
              <span className="text-zinc-400">integrated loudness</span> ที่ตัวกรองวัดเอง ไม่ใช่ค่าจากไฟล์ต้นทางก่อน
              highpass/denoise
            </p>
            {lnOn === false ? (
              <p className="mt-3 text-sm text-amber-200/90">
                ขั้นนี้ปิด loudnorm — ไม่มีการวัด LUFS จาก loudnorm สำหรับไฟล์นี้
              </p>
            ) : (
              <>
                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  <div>
                    <p className="text-xs text-zinc-500">เข้า loudnorm</p>
                    <p className="text-[10px] leading-tight text-zinc-600">
                      หลัง highpass / denoise ใน chain (ไม่ใช่ไฟล์ extract ดิบ)
                    </p>
                    <p className="mt-1 font-mono text-xl font-semibold tabular-nums text-zinc-50">
                      {fmtNum(inLu, 2)}
                      <span className="ml-1.5 text-sm font-normal text-sky-200/80">LUFS</span>
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-zinc-500">เป้า loudnorm</p>
                    <p className="text-[10px] leading-tight text-zinc-600">ค่าที่ส่งให้กรอง</p>
                    <p className="mt-1 font-mono text-xl font-semibold tabular-nums text-sky-100">
                      {fmtNum(tgt, 2)}
                      <span className="ml-1.5 text-sm font-normal text-sky-200/80">LUFS</span>
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-zinc-500">ออก loudnorm</p>
                    <p className="text-[10px] leading-tight text-zinc-600">
                      ก่อน peak-force (ถ้าเปิด) — ไฟล์ WAV สุดท้ายอาจเพี้ยนจากค่านี้
                    </p>
                    <p className="mt-1 font-mono text-xl font-semibold tabular-nums text-emerald-100">
                      {fmtNum(outLu, 2)}
                      <span className="ml-1.5 text-sm font-normal text-emerald-200/85">LUFS</span>
                    </p>
                  </div>
                </div>
                {deltaVsTarget != null ? (
                  <p className="mt-3 text-xs text-zinc-400">
                    ต่างจากเป้า (out − target):{" "}
                    <span className="font-mono text-zinc-200">
                      {deltaVsTarget >= 0 ? "+" : ""}
                      {deltaVsTarget.toFixed(2)} LUFS
                    </span>
                    <span className="text-zinc-600"> — ค่าติดลบ = ออกเบากว่าเป้า</span>
                  </p>
                ) : null}
                <div className="mt-3 rounded-md border border-zinc-700/80 bg-zinc-900/50 px-3 py-2.5 text-xs leading-relaxed text-zinc-300">
                  <p className="font-medium text-zinc-200">สรุป: ใช้ค่าไหน?</p>
                  <ul className="mt-2 list-inside list-disc space-y-1.5 text-zinc-400 marker:text-zinc-600">
                    <li>
                      <span className="text-emerald-200/90">ออก (output_lufs)</span> = หลัง{" "}
                      <span className="font-mono text-zinc-500">loudnorm</span> ตามที่ ffmpeg รายงาน
                      (ก่อน peak-force ถ้าเปิด) — ใช้เทียบกับเป้าใน job
                    </li>
                    <li>
                      <span className="text-sky-200/90">เป้า (target_lufs)</span> = ค่าที่ส่งให้{" "}
                      <span className="font-mono text-zinc-500">loudnorm</span> (เกณฑ์ ไม่ใช่การวัดจากไฟล์)
                    </li>
                    <li>
                      <span className="text-zinc-200">เข้า (input_lufs)</span> = เสียงที่เข้า{" "}
                      <span className="font-mono text-zinc-500">loudnorm</span> หลัง highpass/denoise
                      แล้ว — ไม่ใช่ค่าจาก extract ดิบ
                    </li>
                    <li className="text-zinc-500">
                      ถ้า <span className="font-mono text-zinc-400">เข้า</span> กับ{" "}
                      <span className="font-mono text-zinc-400">ออก</span> ใกล้กันมากแต่ไกลเป้า:
                      รีสตาร์ทบริการ <span className="font-mono">audio_enhancement</span> หลังอัปเดตโค้ด
                      (แก้การอ่าน JSON หลายบล็อก) หรือคลิปสั้น/เนื้อหาทำให้ integrated ขยับน้อย
                    </li>
                  </ul>
                </div>
                {(typeof truePeakCfg === "number" || typeof lraCfg === "number") && lnOn !== false ? (
                  <p className="mt-2 text-[11px] text-zinc-500">
                    พารามิเตอร์ loudnorm ที่ใช้: TP{" "}
                    <span className="font-mono text-zinc-400">{fmtNum(truePeakCfg, 2)}</span> dBTP
                    {typeof lraCfg === "number" ? (
                      <>
                        {" "}
                        · LRA <span className="font-mono text-zinc-400">{lraCfg.toFixed(1)}</span>
                      </>
                    ) : null}
                  </p>
                ) : null}
              </>
            )}
          </div>

          {(hasPeakPre || hasPeakPost) && (
            <div className="rounded-lg border border-zinc-800/90 bg-gradient-to-br from-violet-950/25 via-zinc-950/70 to-orange-950/20 px-4 py-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-400">
                Peak sample — ffmpeg astats (overall)
              </p>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                คอลัมน์ซ้าย = ffmpeg <span className="font-mono text-zinc-400">astats</span> บน WAV หลัง loudnorm
                แต่ก่อน pass <span className="font-mono text-zinc-400">volume</span> (peak-force) · คอลัมน์ขวา = หลังปรับ
                (ตรง waveform) — worker ปัจจุบันวัดซ้ายเสมอหลัง chain
              </p>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-md border border-violet-900/50 bg-violet-950/20 pl-3 pr-3 pt-3 pb-3">
                  <p className="text-xs font-medium text-violet-200/95">ก่อน peak-force</p>
                  <p className="mt-1 text-[10px] leading-tight text-zinc-500">
                    หลัง loudnorm · ก่อน <span className="font-mono text-zinc-500">volume</span> (peak-force)
                  </p>
                  <p className="mt-2 font-mono text-2xl font-semibold tabular-nums tracking-tight text-zinc-50">
                    {hasPeakPre ? fmtNum(peakPre, peakDigits) : "—"}
                    <span className="ml-1.5 text-sm font-normal text-violet-200/80">dBFS</span>
                  </p>
                  {withinPreLabel ? (
                    <p className="mt-2">
                      <span
                        className={
                          withinPreResolved === true
                            ? "inline-block rounded border border-emerald-800/60 bg-emerald-950/50 px-1.5 py-0.5 text-[11px] text-emerald-200"
                            : "inline-block rounded border border-amber-800/60 bg-amber-950/50 px-1.5 py-0.5 text-[11px] text-amber-200"
                        }
                      >
                        {withinPreLabel}
                      </span>
                    </p>
                  ) : null}
                  {!hasPeakPre ? (
                    <p className="mt-2 text-[10px] leading-snug text-zinc-500">
                      ไม่มีค่า <span className="font-mono text-zinc-500">peak_sample_dbfs_pre_peak_force</span> ใน
                      metrics — มักเป็น job ที่รันก่อน worker บันทึกฟิลด์นี้ หรือ astats ล้มเหลว; รัน job ใหม่หลัง
                      restart <span className="font-mono">audio_enhancement</span>
                    </p>
                  ) : null}
                </div>
                <div className="rounded-md border border-orange-900/50 bg-orange-950/15 pl-3 pr-3 pt-3 pb-3">
                  <p className="text-xs font-medium text-orange-200/95">หลังปรับ (ไฟล์ที่ mux)</p>
                  <p className="mt-1 text-[10px] leading-tight text-zinc-500">
                    หลัง peak-force — สอดคล้องกับ waveform ด้านล่าง
                  </p>
                  <p className="mt-2 font-mono text-2xl font-semibold tabular-nums tracking-tight text-zinc-50">
                    {hasPeakPost ? fmtNum(peak, peakDigits) : "—"}
                    <span className="ml-1.5 text-sm font-normal text-orange-200/80">dBFS</span>
                  </p>
                  {withinLabel ? (
                    <p className="mt-2">
                      <span
                        className={
                          withinPostResolved === true
                            ? "inline-block rounded border border-emerald-800/60 bg-emerald-950/50 px-1.5 py-0.5 text-[11px] text-emerald-200"
                            : "inline-block rounded border border-amber-800/60 bg-amber-950/50 px-1.5 py-0.5 text-[11px] text-amber-200"
                        }
                      >
                        {withinLabel}
                      </span>
                    </p>
                  ) : null}
                  {!hasPeakPost ? (
                    <p className="mt-2 text-[10px] leading-snug text-zinc-500">ยังไม่มีค่า peak หลังใน metrics</p>
                  ) : null}
                </div>
              </div>
              {peakDeltaSigned != null ? (
                <p className="mt-3 text-xs text-zinc-400">
                  ต่างกัน (หลัง − ก่อน):{" "}
                  <span className="font-mono text-zinc-100">
                    {peakDeltaSigned >= 0 ? "+" : ""}
                    {peakDeltaSigned.toFixed(peakDigits)} dB
                  </span>
                  <span className="text-zinc-600"> — ค่าติดลบ = peak หลังต่ำลง (เบาลง)</span>
                </p>
              ) : null}
              {!showSplitPeakRows && singleRowFootnote ? (
                <p className="mt-2 text-[10px] leading-snug text-zinc-500">{singleRowFootnote}</p>
              ) : null}
            </div>
          )}

          <dl className="grid gap-2 rounded-md border border-zinc-800/90 bg-zinc-950/70 px-3 py-3 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-zinc-500">ช่วง peak ที่ตั้ง (dBFS)</dt>
            <dd className="mt-0.5 font-mono text-zinc-200">
              {fmtNum(low, 1)} … {fmtNum(high, 1)}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-500">บังคับปรับ peak เข้าช่วง</dt>
            <dd className="mt-0.5 text-zinc-200">
              {fmtBool(forced)}
              {typeof gainTot === "number" && Math.abs(gainTot) > 1e-6 ? (
                <span className="ml-1 font-mono text-zinc-400">
                  ({gainTot >= 0 ? "+" : ""}
                  {gainTot.toFixed(2)} dB)
                </span>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-500">Job</dt>
            <dd className="mt-0.5 font-mono text-[11px] text-zinc-500">{jobId}</dd>
          </div>
        </dl>
        </>
      ) : null}

      {hasWaveform && primaryUrl ? (
        <div className="space-y-3">
          <WaveformStrip
            key={primaryUrl}
            peaks={primaryPeaks.peaks}
            height={56}
            variant="timeline"
            segments={primarySegments}
            vadSegments={null}
            totalDurationSeconds={Math.max(primaryDuration, 0.001)}
            label={compareUrl ? "Enhanced WAV (หลัง chain)" : "Enhanced / prep WAV"}
            sublabel="คลื่นแมปตาม dBFS เทียบช่วง −18…−14 (ยอดสูงสุดในไฟล์ = ค่า astats หลังปรับ) — ส่วนใหญ่ของคลื่นมักต่ำกว่าเส้นบนเพราะเป็น envelope รายช่วง ไม่ใช่ peak ทุก sample"
            referenceDbfsGuide={
              typeof low === "number" &&
              typeof high === "number" &&
              typeof peak === "number" &&
              Number.isFinite(low) &&
              Number.isFinite(high) &&
              Number.isFinite(peak)
                ? {
                    lowDbfs: low,
                    highDbfs: high,
                    anchorDbfs: peak,
                    prePeakDbfs: typeof peakPre === "number" ? peakPre : null,
                    postPeakDbfs: peak,
                  }
                : null
            }
            state={primaryPeaks.state}
            errorMessage={primaryPeaks.error}
          />
          {showPeakMeter ? (
            <PeakDbfsWindowMeter
              lowDbfs={low as number}
              highDbfs={high as number}
              preDbfs={typeof peakPre === "number" ? peakPre : null}
              postDbfs={typeof peak === "number" ? peak : null}
            />
          ) : null}
          {compareUrl ? (
            <WaveformStrip
              key={compareUrl}
              peaks={comparePeaks.peaks}
              height={56}
              variant="timeline"
              visualTone="zinc"
              segments={compareSegments}
              vadSegments={null}
              totalDurationSeconds={Math.max(compareDuration, 0.001)}
              label="Extracted WAV (ก่อน prep)"
              sublabel="ไทม์ไลน์เดียวกับด้านบน — สเกล dBFS เทียบช่วงเดียวกัน (anchor = peak ก่อน prep)"
              referenceDbfsGuide={
                typeof low === "number" &&
                typeof high === "number" &&
                typeof peakPre === "number" &&
                Number.isFinite(low) &&
                Number.isFinite(high) &&
                Number.isFinite(peakPre)
                  ? {
                      lowDbfs: low,
                      highDbfs: high,
                      anchorDbfs: peakPre,
                      prePeakDbfs: null,
                      postPeakDbfs: null,
                    }
                  : null
              }
              state={comparePeaks.state}
              errorMessage={comparePeaks.error}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
