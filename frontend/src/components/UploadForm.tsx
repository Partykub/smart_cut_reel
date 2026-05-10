"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { createJob } from "@/lib/api";
import {
  PIPELINE_ID_REFRAME_AUDIO_QUALITY,
  PIPELINE_ID_REFRAME_DEAD_AIR,
  PIPELINE_ID_REFRAME_ONLY,
  type PipelineId,
} from "@/lib/types";

type ToggleState = {
  removeDeadAir: boolean;
  enhanceAudio: boolean;
  removeFillerWords: boolean;
};

type PresetInfo = {
  label: string;
  accent: "emerald" | "violet" | "amber";
  steps: number;
  summary: string;
  bullets: string[];
};

const PRESET_INFO: Record<PipelineId, PresetInfo> = {
  "reframe_16x9_to_9x16": {
    label: "Smooth vertical reframe",
    accent: "emerald",
    steps: 9,
    summary:
      "Vision-only pipeline: sample frames, detect subject, plan crop, smooth motion, render one 9:16 MP4.",
    bullets: [
      "No audio extraction or silence cuts",
      "Best when your timeline is already tight",
    ],
  },
  "reframe_16x9_to_9x16_dead_air": {
    label: "Reframe + dead air",
    accent: "violet",
    steps: 12,
    summary:
      "Adds an audio chain before vision: WAV extract → voice activity detection → cut plan, then the same reframe/render path with trims.",
    bullets: [
      "Trims long silent stretches (configurable in the orchestrator)",
      "Requires dead-air chain when enhancing audio or cutting fillers",
    ],
  },
  "reframe_16x9_to_9x16_audio_quality": {
    label: "Full audio-quality chain",
    accent: "amber",
    steps: 14,
    summary:
      "Dead-air base plus enhancement (denoise / loudness), Silero VAD on enhanced audio, transcription, and optional filler-word removal from the cut plan.",
    bullets: [
      "Longer runs — includes ASR when removing fillers",
      "Best for noisy rooms and verbal clutter",
    ],
  },
};

function selectPipelineId(state: ToggleState): PipelineId {
  if (state.enhanceAudio || state.removeFillerWords) {
    return PIPELINE_ID_REFRAME_AUDIO_QUALITY;
  }
  if (state.removeDeadAir) {
    return PIPELINE_ID_REFRAME_DEAD_AIR;
  }
  return PIPELINE_ID_REFRAME_ONLY;
}

function buildEnabledFeatures(state: ToggleState): Record<string, boolean> {
  const features: Record<string, boolean> = {
    remove_dead_air: state.removeDeadAir,
  };
  if (state.enhanceAudio) features.enhance_audio = true;
  if (state.removeFillerWords) features.remove_filler_words = true;
  return features;
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
  const [removeDeadAir, setRemoveDeadAir] = useState(true);
  const [enhanceAudio, setEnhanceAudio] = useState(false);
  const [removeFillerWords, setRemoveFillerWords] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const requiresDeadAir = enhanceAudio || removeFillerWords;
  const effectiveRemoveDeadAir = requiresDeadAir ? true : removeDeadAir;

  const toggleState: ToggleState = {
    removeDeadAir: effectiveRemoveDeadAir,
    enhanceAudio,
    removeFillerWords,
  };

  const pipelineId = selectPipelineId(toggleState);
  const enabledFeatures = buildEnabledFeatures(toggleState);
  const preset = PRESET_INFO[pipelineId];

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!file) {
      setError("Choose a video file first.");
      return;
    }

    startTransition(async () => {
      try {
        const formData = new FormData();
        formData.append("source", file);
        formData.append("created_by", "debug_frontend");
        formData.append("pipeline_id", pipelineId);
        formData.append("enabled_features", JSON.stringify(enabledFeatures));
        const result = await createJob(formData);
        router.push(`/jobs/${result.job_id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not create job.");
      }
    });
  };

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
          Select a 16:9 source file, tune cuts and audio below, then start — you&apos;ll land on the
          job dashboard with live steps and artifacts.
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
          Video & audio cuts
        </legend>

        <ToggleRow
          accentClassName="text-emerald-500 focus:ring-emerald-500"
          checked={effectiveRemoveDeadAir}
          disabled={isPending || requiresDeadAir}
          onChange={(value) => setRemoveDeadAir(value)}
          title="Remove dead air (silence)"
          subtitle="Extract audio, run Silero VAD, build a cut plan, then trim long silent gaps before reframing. Turns off only when neither enhancement nor filler-word removal is selected."
          hint={
            requiresDeadAir
              ? "Forced on — audio enhancement and filler cuts require this chain."
              : undefined
          }
        />

        <ToggleRow
          accentClassName="text-violet-400 focus:ring-violet-500"
          checked={enhanceAudio}
          disabled={isPending}
          onChange={(value) => setEnhanceAudio(value)}
          title="Enhance audio"
          subtitle="High-pass, light denoise, and EBU R128-style loudness normalization before VAD / ASR — helps noisy rooms and uneven levels."
        />

        <ToggleRow
          accentClassName="text-amber-400 focus:ring-amber-500"
          checked={removeFillerWords}
          disabled={isPending}
          onChange={(value) => setRemoveFillerWords(value)}
          title="Remove filler words"
          subtitle="faster-whisper with word timestamps; cuts common fillers (Thai + English). Adds noticeable CPU time per clip."
        />
      </fieldset>

      <details className="rounded-lg border border-zinc-800/80 bg-zinc-950/25 px-4 py-3 text-xs text-zinc-500">
        <summary className="cursor-pointer select-none font-medium text-zinc-400">
          Technical · API payload (debug)
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
      className={`flex cursor-pointer items-start gap-3 text-sm text-zinc-200 ${
        disabled ? "opacity-70" : ""
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
