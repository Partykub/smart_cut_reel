import Link from "next/link";
import type { Route } from "next";

import { HyperframesUploadForm } from "@/components/HyperframesUploadForm";
import {
  HYPERFRAMES_TEMPLATE_PRESETS,
  type HyperframesTemplatePreset,
} from "@/lib/hyperframes-catalog";
import { hyperframesServiceUrl } from "@/lib/hyperframes-service";
import type { HyperframesProjectSummary } from "@/lib/hyperframes-types";

const NEW_PROJECT_ROUTE = "/hyperframes/new" as Route;
const SHARED_STUDIO_URL = "http://127.0.0.1:3002";

export default async function HyperframesPage() {
  const projects = await loadProjects();

  return (
    <main className="space-y-8">
      <header className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-amber-300/90">
              Smart Cut Reel · Hyperframes workspaces
            </p>
            <h1 className="font-display text-4xl font-semibold tracking-tight text-white sm:text-[2.75rem] sm:leading-[1.1]">
              Start a new workspace or jump back into an active project
            </h1>
          </div>
          <Link href="/" className="text-sm text-zinc-400 hover:text-zinc-200">
            Back to pipeline UI
          </Link>
        </div>
        <p className="max-w-3xl text-lg leading-relaxed text-zinc-400">
          Choose a template preset, create the workspace, then continue into a project-scoped draft,
          Studio edit, and render flow.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            href={NEW_PROJECT_ROUTE}
            className="inline-flex rounded-full bg-cyan-300 px-4 py-2 text-sm font-medium text-zinc-950 transition hover:bg-cyan-200"
          >
            Create new workspace
          </Link>
          <a
            href={SHARED_STUDIO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex rounded-full border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-500"
          >
            Open shared preview shell
          </a>
        </div>
      </header>

      <section className="relative left-1/2 right-1/2 w-screen -translate-x-1/2 border-y border-zinc-800/70 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.04),transparent_30%),linear-gradient(180deg,#0b0b10_0%,#09090c_100%)] py-6 sm:py-8">
        <div className="mx-auto w-full max-w-[min(1760px,100vw-1.5rem)] px-3 sm:px-5">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4 px-1">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300/80">
                Template catalog
              </p>
              <h2 className="mt-2 font-display text-3xl text-white sm:text-4xl">
                Pick the visual system before you build the workspace
              </h2>
            </div>
            <p className="max-w-xl text-sm leading-6 text-zinc-400">
              Each preset seeds the first workspace with a template family, visual tone, and preset defaults.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {HYPERFRAMES_TEMPLATE_PRESETS.map((preset) => (
              <TemplateCatalogCard key={preset.id} preset={preset} />
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-[1.75rem] border border-zinc-800/80 bg-zinc-900/50 p-6 shadow-[0_24px_70px_rgba(0,0,0,0.2)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">
              Recent workspaces
            </p>
            <h2 className="mt-2 font-display text-2xl text-white">Resume a project</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-400">
              Open project detail or jump straight into the project-scoped Studio route.
            </p>
          </div>
          <Link
            href={NEW_PROJECT_ROUTE}
            className="inline-flex rounded-full border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-500"
          >
            Create another workspace
          </Link>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          {projects.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-950/40 p-5 text-sm text-zinc-400">
              No workspaces yet. Start by creating a new project-first workspace.
            </div>
          ) : (
            projects.map((project) => (
              <WorkspaceCard key={project.project_id} project={project} />
            ))
          )}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[0.84fr_1.16fr]">
        <aside className="rounded-[1.75rem] border border-zinc-800/80 bg-zinc-900/50 p-6 shadow-[0_24px_70px_rgba(0,0,0,0.2)]">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-amber-300/80">
            Utilities
          </p>
          <div className="mt-3 space-y-3 text-sm text-zinc-400">
            <p>Use the shared preview shell only when you need to debug the generic HyperFrames environment.</p>
            <a
              href={SHARED_STUDIO_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex rounded-full border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-500"
            >
              Open shared preview shell
            </a>
          </div>
        </aside>

        <section className="rounded-[1.75rem] border border-zinc-800/80 bg-zinc-900/50 p-6 shadow-[0_24px_70px_rgba(0,0,0,0.2)]">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-zinc-500">
              Legacy direct render
            </p>
            <h2 className="mt-2 font-display text-2xl text-white">Quick upload path</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-400">
              Keep this only for migration and one-off checks. This path does not use the template
              preset selected from the catalog above.
            </p>
            <div className="mt-4 rounded-xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
              Use the project-first flow if you want the selected catalog preset and template
              variant to carry into draft renders.
            </div>
          </div>
          <HyperframesUploadForm />
        </section>
      </section>
    </main>
  );
}

async function loadProjects(): Promise<HyperframesProjectSummary[]> {
  const response = await fetch(hyperframesServiceUrl("/projects"), {
    cache: "no-store",
  });

  if (!response.ok) {
    return [];
  }

  const projects = (await response.json()) as HyperframesProjectSummary[];
  return [...projects].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

function TemplateCatalogCard({ preset }: { preset: HyperframesTemplatePreset }) {
  const presetRoute = `/hyperframes/new?preset=${encodeURIComponent(preset.id)}` as Route;
  const previewAlignClassName =
    preset.previewAlign === "left"
      ? "items-start justify-start"
      : preset.previewAlign === "right"
        ? "items-end justify-end"
        : "items-center justify-center";

  return (
    <Link
      href={presetRoute}
      className="group overflow-hidden rounded-[1.75rem] border border-white/10 bg-[#111114] shadow-[0_30px_80px_rgba(0,0,0,0.45)] transition duration-300 hover:-translate-y-1 hover:border-white/20"
    >
      <div className="relative aspect-[16/10] overflow-hidden border-b border-white/10" style={{ background: preset.background }}>
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src={preset.previewVideoSrc}
          poster={preset.previewPosterSrc}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
        />
        {preset.overlay ? (
          <div className="absolute inset-0" style={{ background: `${preset.overlay}, linear-gradient(180deg, rgba(6,6,10,0.14), rgba(6,6,10,0.36))` }} />
        ) : null}
        <div className={`absolute inset-0 flex p-5 ${previewAlignClassName}`}>
          <div className="w-[68%] rounded-[1.4rem] border border-white/15 bg-black/45 p-4 shadow-[0_18px_40px_rgba(0,0,0,0.3)] backdrop-blur-sm">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.28em] text-white/70">
              <span>{preset.templateFamily}</span>
              <span style={{ color: preset.accent }}>Preview</span>
            </div>
            <div className="mt-6 space-y-3 text-white">
              <p className="font-display text-2xl leading-tight">{preset.title}</p>
              <p className="max-w-[22ch] text-xs leading-5 text-white/75">{preset.subtitle}</p>
            </div>
            <div className="mt-8 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em] text-white/70">
              <span className="rounded-full border border-white/15 px-3 py-1">{preset.durationLabel}</span>
              <span className="rounded-full border border-white/15 px-3 py-1">{preset.canvasLabel}</span>
            </div>
          </div>
        </div>
        <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
        <div
          aria-hidden
          className="absolute right-4 top-4 h-2.5 w-2.5 rounded-full shadow-[0_0_22px_currentColor]"
          style={{ backgroundColor: preset.accent, color: preset.accent }}
        />
      </div>

      <div className="flex items-end justify-between gap-4 p-5">
        <div>
          <h3 className="font-display text-2xl text-white">{preset.title}</h3>
          <p className="mt-2 max-w-[34ch] text-sm leading-6 text-zinc-400">{preset.subtitle}</p>
          <p className="mt-3 text-sm text-zinc-500">
            {preset.durationLabel} · {preset.canvasLabel}
          </p>
          <p className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950/70 px-3 py-2 font-mono text-[11px] leading-5 text-zinc-400">
            {preset.installCommand}
          </p>
          <p className="mt-3 text-xs leading-5 text-zinc-500">
            Intro: {preset.introPreset ?? "none"} · Main: {preset.mainPreset ?? "none"} · Outro: {preset.outroPreset ?? "none"}
          </p>
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            Auto intro {preset.autoGenerateIntro ? "yes" : "no"} · Auto outro {preset.autoGenerateOutro ? "yes" : "no"} · Logo intro subject {preset.usesLogoAsIntroSubject ? "yes" : "no"}
          </p>
        </div>
        <span className="inline-flex rounded-full border border-white/35 px-4 py-2 text-sm text-emerald-300 transition group-hover:border-emerald-300 group-hover:bg-emerald-300 group-hover:text-zinc-950">
          Use preset
        </span>
      </div>
    </Link>
  );
}

function WorkspaceCard({ project }: { project: HyperframesProjectSummary }) {
  const detailRoute = `/hyperframes/projects/${project.project_id}` as Route;
  const studioRoute = `/hyperframes/projects/${project.project_id}/studio` as Route;

  return (
    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-950/50 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Workspace</p>
          <h3 className="mt-2 font-display text-2xl text-white">{project.name}</h3>
          <p className="mt-2 text-sm text-zinc-400">
            Template: <span className="font-mono text-zinc-200">{project.template_family}</span>
            {" · "}
            Variant: <span className="font-mono text-zinc-200">{project.template_variant}</span>
            {" · "}
            Active revision: <span className="font-mono text-zinc-200">{project.active_revision_id}</span>
          </p>
        </div>
        <div className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-300">
          {project.orientation_detected}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        <Link
          href={detailRoute}
          className="inline-flex rounded-full bg-cyan-300 px-4 py-2 text-sm font-medium text-zinc-950 transition hover:bg-cyan-200"
        >
          Open workspace
        </Link>
        <Link
          href={studioRoute}
          className="inline-flex rounded-full border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-500"
        >
          Open Studio
        </Link>
      </div>
    </div>
  );
}
