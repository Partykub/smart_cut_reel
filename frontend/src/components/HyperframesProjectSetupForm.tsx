"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useState, useTransition, type FormEvent } from "react";

import { createHyperframesProject } from "@/lib/hyperframes-api";
import type {
  HyperframesTemplatePreset,
  HyperframesThemeId,
} from "@/lib/hyperframes-catalog";
import {
  getHyperframesSubtitleHelpText,
  summarizeHyperframesSubtitleDocument,
  validateHyperframesSubtitleFile,
} from "@/lib/hyperframes-subtitles";
import type { HyperframesTemplateFamily } from "@/lib/hyperframes-types";

export function HyperframesProjectSetupForm({
  preset,
}: {
  preset?: HyperframesTemplatePreset | null;
}) {
  const router = useRouter();
  const [projectName, setProjectName] = useState(preset?.suggestedProjectName ?? "");
  const [sourceVideo, setSourceVideo] = useState<File | null>(null);
  const [introVideo, setIntroVideo] = useState<File | null>(null);
  const [outroVideo, setOutroVideo] = useState<File | null>(null);
  const [logoImage, setLogoImage] = useState<File | null>(null);
  const [subtitleFile, setSubtitleFile] = useState<File | null>(null);
  const [subtitleSummary, setSubtitleSummary] = useState<string | null>(null);
  const [subtitleValidationError, setSubtitleValidationError] = useState<string | null>(null);
  const [templateFamily, setTemplateFamily] = useState<HyperframesTemplateFamily>(
    preset?.templateFamily ?? "auto",
  );
  const [brandTheme, setBrandTheme] = useState<HyperframesThemeId>(preset?.brandTheme ?? "default");
  const [subtitleTheme, setSubtitleTheme] = useState<HyperframesThemeId>(
    preset?.subtitleTheme ?? "glassmorphism",
  );
  const templateVariant = preset?.templateVariant ?? "default";
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!projectName.trim()) {
      setError("Please enter a project name");
      return;
    }

    if (!sourceVideo) {
      setError("Please choose a source video first");
      return;
    }

    if (subtitleValidationError) {
      setError(subtitleValidationError);
      return;
    }

    startTransition(async () => {
      try {
        if (subtitleFile) {
          const document = await validateHyperframesSubtitleFile(subtitleFile);
          setSubtitleSummary(summarizeHyperframesSubtitleDocument(document));
        }

        const formData = new FormData();
        formData.append("project_name", projectName.trim());
        formData.append("source_video", sourceVideo);
        formData.append("template_family", templateFamily);
        formData.append("template_variant", templateVariant);
        formData.append("brand_theme", brandTheme);
        formData.append("subtitle_theme", subtitleTheme);
        formData.append("created_by", "hyperframes_frontend");
        if (introVideo) formData.append("intro_video", introVideo);
        if (outroVideo) formData.append("outro_video", outroVideo);
        if (logoImage) formData.append("logo_image", logoImage);
        if (subtitleFile) formData.append("subtitle_file", subtitleFile);

        const created = await createHyperframesProject(formData);
        router.push(`/hyperframes/projects/${created.project_id}` as Route);
      } catch (submitError) {
        setError(submitError instanceof Error ? submitError.message : "Could not create project");
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
          Hyperframes project setup
        </h2>
        <p className="text-sm text-zinc-500">
          Start with assets and routing decisions here. Editing happens in Hyperframes Studio after
          the project workspace is created.
        </p>
        {preset ? (
          <div className="mt-4 rounded-xl border border-cyan-300/20 bg-cyan-300/8 p-4 text-sm text-zinc-300">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">
              Selected preset
            </p>
            <p className="mt-2 font-display text-xl text-white">{preset.title}</p>
            <p className="mt-1 text-zinc-400">{preset.subtitle}</p>
            <p className="mt-3 text-xs uppercase tracking-[0.22em] text-cyan-200/70">
              Variant: {templateVariant}
            </p>
            <p className="mt-3 text-xs text-zinc-400">
              Intro: {preset.introPreset ?? "none"} · Main: {preset.mainPreset ?? "none"} · Outro: {preset.outroPreset ?? "none"}
            </p>
            <p className="mt-1 text-xs text-zinc-400">
              Auto intro: {preset.autoGenerateIntro ? "yes" : "no"} · Auto outro: {preset.autoGenerateOutro ? "yes" : "no"} · Logo-driven intro: {preset.usesLogoAsIntroSubject ? "yes" : "no"}
            </p>
          </div>
        ) : null}
      </div>

      <label className="block space-y-2 text-sm text-zinc-300">
        <span className="font-medium">Project name</span>
        <input
          value={projectName}
          disabled={isPending}
          onChange={(event) => setProjectName(event.target.value)}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-950/80 px-3 py-2 text-zinc-100"
          placeholder={preset?.suggestedProjectName ?? "Bugaboo promo cut"}
        />
      </label>

      <UploadField
        id="source_video"
        label="Source video"
        accept="video/*"
        disabled={isPending}
        onChange={setSourceVideo}
        required
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadField
          id="intro_video"
          label="Optional intro asset"
          accept="video/*"
          disabled={isPending}
          onChange={setIntroVideo}
        />
        <UploadField
          id="outro_video"
          label="Optional outro asset"
          accept="video/*"
          disabled={isPending}
          onChange={setOutroVideo}
        />
      </div>

      {preset ? (
        <div className="rounded-xl border border-zinc-800/90 bg-zinc-950/40 px-4 py-3 text-sm text-zinc-400">
          <p className="font-medium text-zinc-200">Preset automation</p>
          <p className="mt-1">
            {preset.autoGenerateIntro
              ? "If you skip intro upload, this preset auto-generates the intro."
              : "This preset does not auto-generate an intro."}
          </p>
          <p className="mt-1">
            {preset.autoGenerateOutro
              ? "If you skip outro upload, this preset auto-generates the outro."
              : "This preset does not auto-generate an outro."}
          </p>
          <p className="mt-1">
            {preset.usesLogoAsIntroSubject
              ? "When you upload a logo, the preset uses it as the intro subject."
              : "Uploaded logo is used in the main composition only."}
          </p>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <UploadField
          id="logo_image"
          label="Logo image"
          accept="image/png,image/svg+xml"
          disabled={isPending}
          onChange={setLogoImage}
        />
        <UploadField
          id="subtitle_file"
          label="Subtitle file"
          accept="application/json,.json,.srt,text/plain"
          disabled={isPending}
          onChange={async (file) => {
            setSubtitleFile(file);
            setSubtitleSummary(null);
            setSubtitleValidationError(null);

            if (!file) {
              return;
            }

            try {
              const document = await validateHyperframesSubtitleFile(file);
              setSubtitleSummary(summarizeHyperframesSubtitleDocument(document));
            } catch (validationError) {
              setSubtitleValidationError(
                validationError instanceof Error
                  ? validationError.message
                  : "Subtitle file is invalid",
              );
            }
          }}
        />
      </div>

      <div className="rounded-xl border border-zinc-800/90 bg-zinc-950/40 px-4 py-3 text-sm text-zinc-400">
        <p className="font-medium text-zinc-200">Subtitle contract</p>
        <p className="mt-1">{getHyperframesSubtitleHelpText()}</p>
        {subtitleSummary ? <p className="mt-2 text-emerald-300">Detected: {subtitleSummary}</p> : null}
        {subtitleValidationError ? (
          <p className="mt-2 text-red-300">{subtitleValidationError}</p>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <label className="space-y-2 text-sm text-zinc-300">
          <span className="block font-medium">Template family</span>
          <select
            value={templateFamily}
            disabled={isPending}
            onChange={(event) => setTemplateFamily(event.target.value as HyperframesTemplateFamily)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950/80 px-3 py-2 text-zinc-100"
          >
            <option value="auto">Auto detect</option>
            <option value="vertical">Force vertical</option>
            <option value="horizontal">Force horizontal</option>
          </select>
        </label>
        <label className="space-y-2 text-sm text-zinc-300">
          <span className="block font-medium">Brand preset</span>
          <select
            value={brandTheme}
            disabled={isPending}
            onChange={(event) => setBrandTheme(event.target.value as HyperframesThemeId)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950/80 px-3 py-2 text-zinc-100"
          >
            <option value="default">Default</option>
            <option value="bold">Bold</option>
            <option value="glassmorphism">Glassmorphism</option>
          </select>
        </label>
        <label className="space-y-2 text-sm text-zinc-300">
          <span className="block font-medium">Subtitle preset</span>
          <select
            value={subtitleTheme}
            disabled={isPending}
            onChange={(event) => setSubtitleTheme(event.target.value as HyperframesThemeId)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950/80 px-3 py-2 text-zinc-100"
          >
            <option value="glassmorphism">Glassmorphism</option>
            <option value="default">Default</option>
            <option value="bold">Bold</option>
          </select>
        </label>
      </div>

      {error ? (
        <p className="rounded-md border border-red-900/40 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={isPending}
        className="inline-flex items-center rounded-lg bg-cyan-300 px-4 py-2.5 text-sm font-medium text-zinc-950 transition hover:bg-cyan-200 disabled:opacity-60"
      >
        {isPending ? "Creating project..." : "Create project workspace"}
      </button>
    </form>
  );
}

function UploadField({
  id,
  label,
  accept,
  disabled,
  onChange,
  required = false,
}: {
  id: string;
  label: string;
  accept: string;
  disabled: boolean;
  onChange: (file: File | null) => void;
  required?: boolean;
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-300">
        {label}
      </label>
      <input
        id={id}
        type="file"
        accept={accept}
        required={required}
        disabled={disabled}
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
        className="block w-full text-sm text-zinc-300 file:mr-4 file:rounded-lg file:border-0 file:bg-zinc-100 file:px-4 file:py-2.5 file:text-sm file:font-medium file:text-zinc-900 hover:file:bg-white disabled:opacity-50"
      />
    </div>
  );
}