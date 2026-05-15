"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { createJob } from "@/lib/api";
import { PRESET_INFO, SOUND_OUTPUT_STYLE_OPTIONS, type PresetInfo } from "@/lib/uploadPresets";
import {
  PIPELINE_ID_REFRAME_AUDIO_QUALITY,
  PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED,
  PIPELINE_ID_REFRAME_SMOOTH_AUDIO,
  type AudioProfileId,
  type PipelineId,
} from "@/lib/types";

type ToggleState = {
  removeDeadAir: boolean;
  removeFillerWords: boolean;
};

type FaceDetectorBackend = "retinaface" | "face_recognition";

const LOOKAHEAD_SWITCH_CONFIRMATION_FRAMES = 4;

function selectPipelineId(state: ToggleState): PipelineId {
  if (state.removeFillerWords) {
    return PIPELINE_ID_REFRAME_AUDIO_QUALITY;
  }
  if (state.removeDeadAir) {
    return PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED;
  }
  return PIPELINE_ID_REFRAME_SMOOTH_AUDIO;
}

function buildEnabledFeatures(state: ToggleState): Record<string, boolean> {
  const features: Record<string, boolean> = {
    remove_dead_air: state.removeDeadAir,
  };
  if (state.removeDeadAir) {
    features.enhance_audio = true;
  }
  if (state.removeFillerWords) {
    features.remove_filler_words = true;
    features.enhance_audio = true;
  }
  if (!state.removeDeadAir && !state.removeFillerWords) {
    features.enhance_audio = true;
  }
  return features;
}

/** Partial `audio_enhancement` override for denoise vs profile defaults */
function buildDenoisePartial(
  profile: AudioProfileId,
  reduceNoise: boolean,
): Record<string, string> | null {
  if (profile === "original") {
    if (reduceNoise) {
      return { denoise_model: "std" };
    }
    return null;
  }
  if (reduceNoise) {
    return null;
  }
  return { denoise_model: "off" };
}

function buildAudioEnhancementPartial(
  profile: AudioProfileId,
  reduceNoise: boolean,
  forcePeakInWindow: boolean,
): Record<string, string | boolean> | null {
  const denoise = buildDenoisePartial(profile, reduceNoise);
  const out: Record<string, string | boolean> = { ...(denoise ?? {}) };
  if (forcePeakInWindow) {
    out.peak_force_to_window_enabled = true;
  }
  if (Object.keys(out).length === 0) {
    return null;
  }
  return out;
}

function buildServiceConfig(faceDetectorBackend: FaceDetectorBackend): Record<string, object> {
  return {
    body_detection: {
      face_detector_backend: faceDetectorBackend,
    },
    reframe_planning: {
      framing_mode: "center_subject",
      face_hint_dead_zone_px: 48,
      lookahead_switch_confirmation_frames: LOOKAHEAD_SWITCH_CONFIRMATION_FRAMES,
    },
  };
}

const ACCENT_RING: Record<PresetInfo["accent"], string> = {
  emerald: "ring-emerald-500/35 border-emerald-500/25",
  violet: "ring-violet-500/35 border-violet-500/25",
  amber: "ring-amber-500/35 border-amber-500/25",
};

const ACCENT_DOT: Record<PresetInfo["accent"], string> = {
  emerald: "bg-emerald-400",
  violet: "bg-violet-400",
  amber: "bg-amber-400",
};

export function UploadForm() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [faceDetectorBackend, setFaceDetectorBackend] = useState<FaceDetectorBackend>("retinaface");
  const [removeDeadAir, setRemoveDeadAir] = useState(true);
  const [removeFillerWords, setRemoveFillerWords] = useState(false);
  const [audioProfile, setAudioProfile] = useState<AudioProfileId>("original");
  const [reduceNoise, setReduceNoise] = useState(false);
  const [forcePeakInWindow, setForcePeakInWindow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const requiresDeadAir = removeFillerWords;
  const effectiveRemoveDeadAir = requiresDeadAir ? true : removeDeadAir;

  const toggleState: ToggleState = {
    removeDeadAir: effectiveRemoveDeadAir,
    removeFillerWords,
  };

  const pipelineId = selectPipelineId(toggleState);
  const enabledFeatures = buildEnabledFeatures(toggleState);
  const serviceConfig = buildServiceConfig(faceDetectorBackend);
  const preset = PRESET_INFO[pipelineId];

  const pickSoundStyle = (value: AudioProfileId) => {
    setAudioProfile(value);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!file) {
      setError("Please choose a video file first");
      return;
    }

    startTransition(async () => {
      try {
        const formData = new FormData();
        formData.append("source", file);
        formData.append("created_by", "debug_frontend");
        formData.append("pipeline_id", pipelineId);
        formData.append("enabled_features", JSON.stringify(enabledFeatures));
        formData.append("audio_profile", audioProfile);
        const denoisePartial = buildAudioEnhancementPartial(
          audioProfile,
          reduceNoise,
          forcePeakInWindow,
        );
        if (denoisePartial) {
          formData.append("audio_enhancement", JSON.stringify(denoisePartial));
        }
        formData.append("service_config", JSON.stringify(serviceConfig));
        const result = await createJob(formData);
        router.push(`/jobs/${result.job_id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not create job");
      }
    });
  };

  const audioEnhancementPreview = buildAudioEnhancementPartial(
    audioProfile,
    reduceNoise,
    forcePeakInWindow,
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-8 rounded-2xl border border-zinc-800/90 bg-zinc-900/55 p-6 shadow-xl ring-1 ring-white/[0.04] sm:p-8"
    >
      <div className="space-y-2 border-b border-zinc-800/80 pb-6">
        <h2 className="font-display text-xl font-semibold tracking-tight text-white">
          Upload & options
        </h2>
        <p className="text-sm text-zinc-500">
          Pick a 16:9 file, then set <strong>MP4 loudness</strong> below — the default path here
          still extracts and processes audio for mux (no silence trim). Silence trim / filler
          removal are further down.
        </p>
      </div>

      <div className="space-y-2">
        <label htmlFor="source" className="block text-sm font-medium text-zinc-300">
          Source video
        </label>
        <input
          id="source"
          name="source"
          type="file"
          accept="video/*"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          disabled={isPending}
          className="block w-full text-sm text-zinc-300 file:mr-4 file:rounded-lg file:border-0 file:bg-zinc-100 file:px-4 file:py-2.5 file:text-sm file:font-medium file:text-zinc-900 hover:file:bg-white disabled:opacity-50"
        />
        {file ? (
          <p className="text-xs text-zinc-500">
            {file.name} · {formatMegabytes(file.size)} MB
          </p>
        ) : null}
      </div>

      <div
        className={`rounded-xl border bg-zinc-950/50 p-5 ring-2 ring-inset ${ACCENT_RING[preset.accent]}`}
      >
        <div className="flex items-start gap-3">
          <span
            className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ACCENT_DOT[preset.accent]}`}
            aria-hidden
          />
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0">
              <span className="font-display text-base font-semibold text-zinc-100">{preset.label}</span>
              <span className="font-mono text-xs text-zinc-500">{preset.steps} steps</span>
            </div>
            <p className="text-sm leading-relaxed text-zinc-400">{preset.summary}</p>
            <ul className="list-inside list-disc space-y-1 text-xs text-zinc-500 marker:text-zinc-600">
              {preset.bullets.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <fieldset className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-950/35 p-5">
        <legend className="px-1 font-display text-sm font-semibold text-zinc-200">
          MP4 loudness & audio
        </legend>
        {!effectiveRemoveDeadAir ? (
          <p className="rounded-md border border-emerald-900/30 bg-emerald-950/15 px-3 py-2 text-xs leading-relaxed text-emerald-100/90">
            <span className="font-medium text-emerald-50">Vertical reframe + output audio:</span> pick
            a style below — we extract audio, run loudness processing for that preset, then mux.
            <span className="font-medium"> Source (embedded)</span> keeps the video’s original track
            in the MP4. When you enable <strong>Trim long silence</strong>, the same loudness
            settings feed the silence-analysis chain.
          </p>
        ) : (
          <p className="text-xs text-zinc-500">
            Audio is extracted from the source, processed with your chosen style, analyzed for
            silence, then muxed into the MP4 per preset.
          </p>
        )}
        <div className="space-y-2">
          {SOUND_OUTPUT_STYLE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`flex cursor-pointer gap-3 rounded-lg border px-3 py-2.5 text-sm transition ${audioProfile === opt.value
                ? "border-emerald-500/50 bg-emerald-950/20 text-zinc-100"
                : "border-zinc-800/80 bg-zinc-950/40 text-zinc-400 hover:border-zinc-700"
                }`}
            >
              <input
                type="radio"
                name="audio_profile"
                value={opt.value}
                checked={audioProfile === opt.value}
                onChange={() => pickSoundStyle(opt.value)}
                disabled={isPending}
                className="mt-1 border-zinc-600 bg-zinc-900 text-emerald-500 focus:ring-emerald-500"
              />
              <span>
                <span className="font-medium text-zinc-200">{opt.label}</span>
                <span className="mt-0.5 block text-xs text-zinc-500">{opt.hint}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="border-t border-zinc-800/80 pt-4">
          <ToggleRow
            accentClassName="text-sky-400 focus:ring-sky-500"
            checked={reduceNoise}
            disabled={isPending}
            onChange={(value) => setReduceNoise(value)}
            title="Noise reduction"
            subtitle="Independent of the loudness style above — toggles an FFT denoise override on the enhancement step."
            hint={
              audioProfile === "original" && reduceNoise
                ? "Source mode skips denoise by default — enabling adds standard denoise on the audio chain (turn off if it sounds muffled)."
                : undefined
            }
          />
        </div>

        <div className="border-t border-zinc-800/80 pt-4">
          <ToggleRow
            accentClassName="text-amber-400 focus:ring-amber-500"
            checked={forcePeakInWindow}
            disabled={isPending}
            onChange={(value) => setForcePeakInWindow(value)}
            title="บังคับ peak เข้า −18…−14 dBFS (optional)"
            subtitle="หลัง loudnorm จะปรับ volume จน astats peak อยู่ในช่วง (ไม่จำกัด boost +12 dB). LUFS อาจเพี้ยนจากเป้า loudness — ใช้เมื่อต้องการสเปก peak มากกว่า LUFS"
          />
        </div>
      </fieldset>

      <fieldset className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-950/35 p-5">
        <legend className="px-1 font-display text-sm font-semibold text-zinc-200">
          Video & silence
        </legend>

        <ToggleRow
          accentClassName="text-emerald-500 focus:ring-emerald-500"
          checked={effectiveRemoveDeadAir}
          disabled={isPending || requiresDeadAir}
          onChange={(value) => setRemoveDeadAir(value)}
          title="Trim long silence"
          subtitle="Remove long silent stretches before the vertical reframe — when on, the MP4 loudness section above applies before VAD / cut planning."
          hint={
            requiresDeadAir
              ? "Forced on — filler-word removal requires this path."
              : undefined
          }
        />

        <ToggleRow
          accentClassName="text-amber-400 focus:ring-amber-500"
          checked={removeFillerWords}
          disabled={isPending}
          onChange={(value) => setRemoveFillerWords(value)}
          title="Remove filler words (ASR + cuts)"
          subtitle="Word-level transcription with filler detection (Thai + English) merged into the cut plan — CPU-heavy per clip."
        />
      </fieldset>

      <fieldset className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-950/35 p-5">
        <legend className="px-1 font-display text-sm font-semibold text-zinc-200">
          Face detection backend
        </legend>
        <p className="text-xs leading-relaxed text-zinc-500">
          YOLO body detection still runs first to find the subject ROI. This setting chooses which
          face detector will run inside that body crop.
        </p>

        <label className="flex items-start gap-3 text-sm text-zinc-200">
          <input
            type="radio"
            name="face-detector-backend"
            value="retinaface"
            checked={faceDetectorBackend === "retinaface"}
            disabled={isPending}
            onChange={() => setFaceDetectorBackend("retinaface")}
            className="mt-1 h-4 w-4 border-zinc-600 bg-zinc-800 text-emerald-500 focus:ring-emerald-500"
          />
          <span className="space-y-1">
            <span className="block font-medium text-zinc-100">RetinaFace</span>
            <span className="block text-xs leading-relaxed text-zinc-400">
              Recommended default for production reframing. Better at small or angled faces.
            </span>
          </span>
        </label>

        <label className="flex items-start gap-3 text-sm text-zinc-200">
          <input
            type="radio"
            name="face-detector-backend"
            value="face_recognition"
            checked={faceDetectorBackend === "face_recognition"}
            disabled={isPending}
            onChange={() => setFaceDetectorBackend("face_recognition")}
            className="mt-1 h-4 w-4 border-zinc-600 bg-zinc-800 text-violet-400 focus:ring-violet-500"
          />
          <span className="space-y-1">
            <span className="block font-medium text-zinc-100">face_recognition</span>
            <span className="block text-xs leading-relaxed text-zinc-400">
              Alternate backend for comparison. Usually slower and heavier to package.
            </span>
          </span>
        </label>
      </fieldset>

      <details className="rounded-lg border border-zinc-800/80 bg-zinc-950/25 px-4 py-3 text-xs text-zinc-500">
        <summary className="cursor-pointer select-none font-medium text-zinc-400">
          Debug · API payload preview
        </summary>
        <dl className="mt-3 space-y-2 font-mono text-[11px] leading-relaxed">
          <div>
            <dt className="text-zinc-600">pipeline_id</dt>
            <dd className="text-zinc-400">{pipelineId}</dd>
          </div>
          <div>
            <dt className="text-zinc-600">enabled_features</dt>
            <dd className="break-all text-zinc-400">{JSON.stringify(enabledFeatures)}</dd>
          </div>
          <div>
            <dt className="text-zinc-600">audio_profile</dt>
            <dd className="break-all text-zinc-400">{audioProfile}</dd>
          </div>
          <div>
            <dt className="text-zinc-600">audio_enhancement (partial)</dt>
            <dd className="break-all text-zinc-400">
              {audioEnhancementPreview ? JSON.stringify(audioEnhancementPreview) : "(not sent)"}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-600">service_config</dt>
            <dd className="break-all text-zinc-400">{JSON.stringify(serviceConfig)}</dd>
          </div>
        </dl>
      </details>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-200"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!file || isPending}
        className="inline-flex w-full items-center justify-center rounded-xl bg-emerald-500 px-4 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-emerald-950/30 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400 disabled:shadow-none sm:w-auto sm:min-w-[200px]"
      >
        {isPending ? "Creating job…" : "Upload & start pipeline"}
      </button>
    </form>
  );
}

interface ToggleRowProps {
  accentClassName: string;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
  title: string;
  subtitle: string;
  hint?: string;
}

function ToggleRow({
  accentClassName,
  checked,
  disabled,
  onChange,
  title,
  subtitle,
  hint,
}: ToggleRowProps) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-3 text-sm text-zinc-200 ${disabled ? "opacity-70" : ""
        }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
        className={`mt-1 h-4 w-4 rounded border-zinc-600 bg-zinc-800 disabled:cursor-not-allowed ${accentClassName}`}
      />
      <span className="space-y-1">
        <span className="block font-medium text-zinc-100">{title}</span>
        <span className="block text-xs leading-relaxed text-zinc-400">{subtitle}</span>
        {hint ? <span className="block text-[11px] italic text-zinc-500">{hint}</span> : null}
      </span>
    </label>
  );
}

function formatMegabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(2);
}
