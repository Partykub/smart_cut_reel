import Link from "next/link";
import type { Route } from "next";

import { HyperframesRenderDraftButton } from "@/components/HyperframesRenderDraftButton";
import type { HyperframesProjectDetail } from "@/lib/hyperframes-types";

export function HyperframesProjectDashboard({ project }: { project: HyperframesProjectDetail }) {
  const activeRevision = project.revisions.find(
    (revision) => revision.revision_id === project.active_revision_id,
  );
  const renderJobs = project.render_jobs ?? [];
  const latestJob = renderJobs[0] ?? null;
  const studioRoute = `/hyperframes/projects/${project.project_id}/studio` as Route;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">Hyperframes project</p>
          <h1 className="font-display text-3xl text-zinc-100">{project.name}</h1>
          <p className="mt-2 text-sm text-zinc-400">
            Template: <span className="font-mono text-zinc-200">{project.template_family}</span>
            {" · "}
            Variant: <span className="font-mono text-zinc-200">{project.template_variant}</span>
            {" · "}
            Orientation: <span className="font-mono text-zinc-200">{project.orientation_detected}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {activeRevision ? (
            <HyperframesRenderDraftButton
              projectId={project.project_id}
              revisionId={activeRevision.revision_id}
            />
          ) : null}
          <Link
            href={studioRoute}
            className="inline-flex rounded-lg border border-cyan-300/40 px-4 py-2 text-sm text-cyan-200 hover:border-cyan-200 hover:text-cyan-100"
          >
            Open Studio
          </Link>
          {latestJob ? (
            <Link
              href={`/hyperframes/jobs/${latestJob.job_id}`}
              className="inline-flex rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:border-zinc-500"
            >
              Open latest job screen
            </Link>
          ) : null}
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-4">
        <MetricCard label="Active revision" value={project.active_revision_id} />
        <MetricCard label="Template variant" value={project.template_variant} />
        <MetricCard label="Brand preset" value={project.brand_theme} />
        <MetricCard label="Subtitle preset" value={project.subtitle_theme} />
      </section>

      <section className="rounded-2xl border border-zinc-800/90 bg-zinc-950/40 p-5">
        <h2 className="font-display text-lg text-zinc-100">Project assets</h2>
        <div className="mt-4 grid gap-3 text-sm text-zinc-300 sm:grid-cols-2">
          <AssetCard label="Source video" value={project.assets.source_video} />
          <AssetCard label="Logo image" value={project.assets.logo_image ?? "Not provided"} />
          <AssetCard label="Intro asset" value={project.assets.intro_video ?? "Generated / none"} />
          <AssetCard label="Outro asset" value={project.assets.outro_video ?? "Not provided"} />
          <AssetCard label="Subtitle file" value={project.assets.subtitle_file ?? "Not provided"} />
        </div>
      </section>

      <section className="rounded-2xl border border-zinc-800/90 bg-zinc-950/40 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-display text-lg text-zinc-100">Revisions</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Studio edits the active workspace. Draft renders now trace back to this revision and
              appear in the history panel below.
            </p>
          </div>
        </div>
        <div className="mt-4 space-y-3">
          {project.revisions.map((revision) => (
            <div
              key={revision.revision_id}
              className="rounded-xl border border-zinc-800/80 bg-zinc-950/60 px-4 py-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-zinc-100">{revision.revision_name}</p>
                  <p className="mt-1 font-mono text-xs text-zinc-500">{revision.revision_id}</p>
                </div>
                {revision.revision_id === project.active_revision_id ? (
                  <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-xs text-cyan-200">
                    Active
                  </span>
                ) : null}
              </div>
              <div className="mt-3 grid gap-2 text-xs text-zinc-400 sm:grid-cols-2">
                <p>Type: {revision.revision_type}</p>
                <p>Variant: {revision.template_variant}</p>
                <p>Workspace: {revision.workspace_root}</p>
                <p>Family: {revision.template_family}</p>
              </div>
              {activeRevision?.revision_id === revision.revision_id ? (
                <p className="mt-3 text-sm text-zinc-500">
                  Use Studio to edit this workspace now. Render-from-revision wiring will attach to
                  this active revision next.
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-zinc-800/90 bg-zinc-950/40 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-display text-lg text-zinc-100">Render history</h2>
            <p className="mt-1 text-sm text-zinc-500">
              Every render is linked back to the revision that produced it.
            </p>
          </div>
        </div>
        <div className="mt-4 space-y-3">
          {renderJobs.length === 0 ? (
            <p className="text-sm text-zinc-500">No renders yet. Start with a draft render.</p>
          ) : (
            renderJobs.map((job) => (
              <div
                key={job.job_id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-800/80 bg-zinc-950/60 px-4 py-3"
              >
                <div>
                  <p className="font-medium text-zinc-100">{job.render_mode} render</p>
                  <p className="mt-1 font-mono text-xs text-zinc-500">{job.job_id}</p>
                  <p className="mt-2 text-xs text-zinc-400">
                    Revision: <span className="font-mono text-zinc-300">{job.revision_id ?? "legacy"}</span>
                    {" · "}
                    Variant: <span className="font-mono text-zinc-300">{job.template_variant}</span>
                    {" · "}
                    Status: <span className="font-mono text-zinc-300">{job.status}</span>
                  </p>
                </div>
                <Link
                  href={`/hyperframes/jobs/${job.job_id}`}
                  className="inline-flex rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:border-zinc-500"
                >
                  Open job
                </Link>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">
      <p className="text-xs uppercase tracking-widest text-zinc-500">{label}</p>
      <p className="mt-2 font-mono text-base text-zinc-100">{value}</p>
    </div>
  );
}

function AssetCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-950/70 p-4">
      <p className="text-xs uppercase tracking-widest text-zinc-500">{label}</p>
      <p className="mt-2 break-all font-mono text-sm text-zinc-100">{value}</p>
    </div>
  );
}