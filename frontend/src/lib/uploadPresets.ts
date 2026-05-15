import type { AudioProfileId, JobStatusResponse, PipelineId } from "./types";

export type PresetAccent = "emerald" | "violet" | "amber";

export type PresetInfo = {
  label: string;
  accent: PresetAccent;
  steps: number;
  summary: string;
  bullets: string[];
};

/** MP4 output loudness style — same labels as the upload form */
export const SOUND_OUTPUT_STYLE_OPTIONS: ReadonlyArray<{
  value: AudioProfileId;
  label: string;
  hint: string;
}> = [
  {
    value: "original",
    label: "Source (embedded track)",
    hint: "Closest to the uploaded file — no LUFS targeting by default; MP4 uses the video’s embedded audio (noise reduction toggle below is separate).",
  },
  {
    value: "podcast",
    label: "Podcast (-16 LUFS)",
    hint: "Mono 48 kHz extract, then loudness normalization to podcast targets — no denoise / high-pass by default; enable noise reduction below if needed.",
  },
  {
    value: "social",
    label: "Social (-14 LUFS)",
    hint: "Like podcast but louder (-14 LUFS), good for short clips — loudnorm-only by default; optional noise reduction.",
  },
  {
    value: "broadcast",
    label: "Broadcast (-23 LUFS)",
    hint: "Targets -23 LUFS (broadcast-style headroom) — loudnorm-only by default; optional noise reduction.",
  },
];

/** Preset card titles on the upload form */
export const PRESET_INFO: Record<PipelineId, PresetInfo> = {
  "reframe_16x9_to_9x16": {
    label: "Smooth vertical reframe (vision-only — API / scripts)",
    accent: "emerald",
    steps: 9,
    summary:
      "Vision-only pipeline: no in-app audio extract/enhance — use when calling the API with this pipeline_id directly.",
    bullets: [
      "This upload UI uses “reframe + output audio” instead (11 steps).",
      "Best when your mix is already finished and you don’t need the audio chain.",
    ],
  },
  "reframe_16x9_to_9x16_smooth_audio": {
    label: "Vertical reframe + output audio prep",
    accent: "emerald",
    steps: 11,
    summary:
      "Extract audio from video, apply the loudness style you pick below, then mux into MP4 — no VAD or silence trimming.",
    bullets: [
      "Set MP4 loudness before enabling long-silence trim.",
      "When you enable long-silence trim, the same loudness settings feed the analysis chain.",
    ],
  },
  "reframe_16x9_to_9x16_dead_air": {
    label: "Vertical reframe + dead air (legacy id)",
    accent: "violet",
    steps: 12,
    summary:
      "If you POST this pipeline_id, the orchestrator still materializes the 13-step enhanced dead-air preset; the 12-step template exists for fixtures only.",
    bullets: [
      "Keep this id in scripts for compatibility — manifests store dead_air_enhanced.",
      "The upload UI selects dead_air_enhanced directly.",
    ],
  },
  "reframe_16x9_to_9x16_dead_air_enhanced": {
    label: "Vertical reframe + silence trim",
    accent: "amber",
    steps: 13,
    summary:
      "Extract audio, apply your loudness style, run VAD / cut planning for long silence, then smooth vertical reframe.",
    bullets: [
      "Pick MP4 loudness below — audio is conditioned before silence detection.",
      "Enable filler-word removal below to add ASR (14 steps).",
    ],
  },
  "reframe_16x9_to_9x16_audio_quality": {
    label: "Full audio quality + transcription",
    accent: "amber",
    steps: 14,
    summary:
      "Same silence path as above, then faster-whisper and optional filler cuts from the transcript-aware plan.",
    bullets: [
      "Loudness options match the silence-trim preset — set in the audio section.",
      "Filler-word removal uses significant CPU for ASR.",
    ],
  },
};

/** Toggle labels — keep in sync with `ToggleRow` titles on the upload form */
export const UPLOAD_FORM_TOGGLE_TITLES = {
  removeDeadAir: "Trim long silence",
  removeFillerWords: "Remove filler words (ASR + cuts)",
  reduceNoise: "Noise reduction",
} as const;

function onOff(v: boolean | undefined): string {
  return v === true ? "On" : "Off";
}

export function audioProfileOptionLabel(
  profile: AudioProfileId | string | null | undefined,
): string {
  if (profile == null || profile === "") return "—";
  const row = SOUND_OUTPUT_STYLE_OPTIONS.find((o) => o.value === profile);
  return row?.label ?? String(profile);
}

export function pipelinePresetCardLabel(
  pipelineId: PipelineId | string | null | undefined,
): string {
  if (pipelineId == null || pipelineId === "") return "—";
  const info = (PRESET_INFO as Record<string, PresetInfo | undefined>)[pipelineId];
  return info?.label ?? String(pipelineId);
}

/** Human-readable mux mode (aligned with upload copy) */
export function outputMuxDisplayLabel(
  mux: "source_video" | "enhanced_wav" | string | null | undefined,
): string | null {
  if (mux === "enhanced_wav") {
    return "Mux processed WAV into MP4 (per loudness preset)";
  }
  if (mux === "source_video") {
    return "Embedded track from the uploaded video";
  }
  if (mux != null && mux !== "") {
    return String(mux);
  }
  return null;
}

/** Multi-line summary for job / output panels */
export function buildUploadAlignedJobSummaryLines(data: JobStatusResponse): string {
  const pid = data.pipeline?.pipeline_id;
  const lines: string[] = [];

  lines.push(`Preset: ${pipelinePresetCardLabel(pid)}`);

  const ef = data.enabled_features ?? {};
  lines.push(
    `Form options: “${UPLOAD_FORM_TOGGLE_TITLES.removeDeadAir}” ${onOff(ef.remove_dead_air)} · “${UPLOAD_FORM_TOGGLE_TITLES.removeFillerWords}” ${onOff(ef.remove_filler_words)}`,
  );

  const ap = data.audio_profile;
  lines.push(
    `MP4 loudness style: ${
      ap
        ? audioProfileOptionLabel(ap)
        : "Not recorded (legacy job or API without audio_profile)"
    }`,
  );

  const muxLabel = outputMuxDisplayLabel(
    data.output_audio_source as "source_video" | "enhanced_wav" | null | undefined,
  );
  lines.push(`MP4 audio mux: ${muxLabel ?? "—"}`);

  const ae = data.audio_enhancement;
  if (ae && typeof ae === "object" && !Array.isArray(ae)) {
    const parts: string[] = [];
    const denoise = ae.denoise_model;
    if (denoise === "off") {
      parts.push(`“${UPLOAD_FORM_TOGGLE_TITLES.reduceNoise}” off`);
    } else if (denoise === "std") {
      parts.push(`“${UPLOAD_FORM_TOGGLE_TITLES.reduceNoise}” on (standard)`);
    } else if (denoise != null) {
      parts.push(`“${UPLOAD_FORM_TOGGLE_TITLES.reduceNoise}” ${String(denoise)}`);
    }
    if (ae.loudness_normalization_enabled != null) {
      parts.push(
        `Loudness normalization: ${ae.loudness_normalization_enabled === true ? "on" : "off"}`,
      );
    }
    if (ae.loudness_normalization_enabled === true && ae.target_lufs != null) {
      parts.push(`Target integrated loudness (LUFS): ${String(ae.target_lufs)}`);
    }
    if (ae.peak_force_to_window_enabled === true) {
      parts.push(
        "Peak-window force: on (astats −18…−14 dBFS target — may drift LUFS vs loudnorm)",
      );
    }
    if (ae.peak_window_report_enabled === false) {
      parts.push("Peak window report: off");
    }
    if (parts.length) {
      lines.push(`Audio processing: ${parts.join(" · ")}`);
    }
  }

  const aeMetrics = data.service_status?.steps?.audio_enhancement?.metrics;
  if (aeMetrics && typeof aeMetrics === "object" && !Array.isArray(aeMetrics)) {
    const m = aeMetrics as Record<string, unknown>;
    const sub: string[] = [];
    if (
      typeof m.peak_sample_dbfs_pre_peak_force === "number" &&
      typeof m.peak_sample_dbfs === "number" &&
      Math.abs((m.peak_sample_dbfs_pre_peak_force as number) - (m.peak_sample_dbfs as number)) > 0.02
    ) {
      sub.push(
        `measured peak ${(m.peak_sample_dbfs_pre_peak_force as number).toFixed(2)} → ${(m.peak_sample_dbfs as number).toFixed(2)} dBFS (astats, pre/post peak-force)`,
      );
    } else if (typeof m.peak_sample_dbfs === "number") {
      sub.push(`measured peak ${(m.peak_sample_dbfs as number).toFixed(2)} dBFS (astats)`);
    }
    if (
      typeof m.peak_within_window === "boolean" &&
      typeof m.peak_level_window_low_dbfs === "number" &&
      typeof m.peak_level_window_high_dbfs === "number"
    ) {
      sub.push(
        (m.peak_within_window ? "inside" : "outside") +
          ` ${(m.peak_level_window_low_dbfs as number).toFixed(0)}…${(m.peak_level_window_high_dbfs as number).toFixed(0)} dBFS`,
      );
    }
    if (m.peak_force_applied === true) {
      sub.push("peak force applied");
    }
    if (sub.length) {
      lines.push(`Audio peak (from job): ${sub.join(" · ")}`);
    }
  }

  return lines.join("\n");
}
