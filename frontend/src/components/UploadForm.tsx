"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { createJob } from "@/lib/api";
import {
  PHASE_1_PIPELINE_ID,
  PHASE_2_PIPELINE_ID,
  PHASE_3_PIPELINE_ID,
  type PipelineId,
} from "@/lib/types";

type ToggleState = {
  removeDeadAir: boolean;
  enhanceAudio: boolean;
  removeFillerWords: boolean;
};

function selectPipelineId(state: ToggleState): PipelineId {
  if (state.enhanceAudio || state.removeFillerWords) {
    return PHASE_3_PIPELINE_ID;
  }
  if (state.removeDeadAir) {
    return PHASE_2_PIPELINE_ID;
  }
  return PHASE_1_PIPELINE_ID;
}

function buildEnabledFeatures(state: ToggleState): Record<string, boolean> {
  const features: Record<string, boolean> = {
    remove_dead_air: state.removeDeadAir,
  };
  if (state.enhanceAudio) features.enhance_audio = true;
  if (state.removeFillerWords) features.remove_filler_words = true;
  return features;
}

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

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!file) {
      setError("กรุณาเลือกไฟล์วิดีโอก่อน");
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
        setError(err instanceof Error ? err.message : "สร้างงานไม่สำเร็จ");
      }
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-6 rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 shadow-lg"
    >
      <div className="space-y-2">
        <label
          htmlFor="source"
          className="block text-sm font-medium text-zinc-300"
        >
          วิดีโอต้นทาง
        </label>
        <input
          id="source"
          name="source"
          type="file"
          accept="video/*"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          disabled={isPending}
          className="block w-full text-sm text-zinc-300 file:mr-4 file:rounded-md file:border-0 file:bg-zinc-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-zinc-900 hover:file:bg-zinc-200 disabled:opacity-50"
        />
        {file ? (
          <p className="text-xs text-zinc-500">
            {file.name} · {formatMegabytes(file.size)} MB
          </p>
        ) : null}
      </div>

      <fieldset className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
        <legend className="px-2 text-xs font-semibold uppercase tracking-widest text-zinc-400">
          ตัวเลือกการประมวลผล
        </legend>

        <ToggleRow
          accentClassName="text-emerald-500 focus:ring-emerald-500"
          checked={effectiveRemoveDeadAir}
          disabled={isPending || requiresDeadAir}
          onChange={(value) => setRemoveDeadAir(value)}
          title="ตัดช่วงเงียบยาว"
          subtitle="หาเสียงพูดด้วย Silero VAD แล้วตัดช่วงเงียบเกิน 0.8 วินาที (เช่น พักนาน หายใจยาว) ออกก่อนนำไปครอป"
          hint={
            requiresDeadAir
              ? "เปิดอยู่อัตโนมัติ เพราะ option ด้านล่างต้องใช้"
              : undefined
          }
        />

        <ToggleRow
          accentClassName="text-violet-400 focus:ring-violet-500"
          checked={enhanceAudio}
          disabled={isPending}
          onChange={(value) => setEnhanceAudio(value)}
          title="เพิ่มคุณภาพเสียง (Phase 3)"
          subtitle="กรองเสียงต่ำ (highpass 80 Hz) + ลด noise (afftdn) + ปรับระดับเสียงตามมาตรฐาน EBU R128 ที่ -16 LUFS ก่อน VAD/ASR — ช่วยให้คลิปที่อัดในห้องดัง/ก้องตัดได้แม่นกว่าเดิม"
        />

        <ToggleRow
          accentClassName="text-amber-400 focus:ring-amber-500"
          checked={removeFillerWords}
          disabled={isPending}
          onChange={(value) => setRemoveFillerWords(value)}
          title="ตัดคำลังเล (Phase 3)"
          subtitle="ใช้ faster-whisper ถอดคำพร้อม timestamp แล้วตัดคำเช่น “เอ่อ / อืม / อ่า / อ่ะ / um / uh / er” ออกจาก keep segments — เพิ่ม 30s–2min ต่อคลิปเพราะต้องรัน ASR"
        />

        <div className="space-y-1 pl-7 text-[11px] text-zinc-500">
          <p>
            pipeline ที่จะใช้:{" "}
            <span className="font-mono text-zinc-400">{pipelineId}</span>
          </p>
          <p>
            enabled_features:{" "}
            <span className="font-mono text-zinc-400">
              {JSON.stringify(enabledFeatures)}
            </span>
          </p>
        </div>
      </fieldset>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-900/40 bg-red-950/40 px-3 py-2 text-sm text-red-300"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!file || isPending}
        className="inline-flex items-center justify-center rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
      >
        {isPending ? "กำลังสร้างงาน..." : "เริ่มประมวลผล"}
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
        <span className="block text-xs text-zinc-400">{subtitle}</span>
        {hint ? (
          <span className="block text-[11px] italic text-zinc-500">{hint}</span>
        ) : null}
      </span>
    </label>
  );
}

function formatMegabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(2);
}
