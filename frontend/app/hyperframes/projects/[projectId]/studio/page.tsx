import Link from "next/link";
import type { Route } from "next";

import { HyperframesRenderDraftButton } from "@/components/HyperframesRenderDraftButton";
import { HyperframesStudioEmbed } from "@/components/HyperframesStudioEmbed";
import { hyperframesServiceUrl } from "@/lib/hyperframes-service";
import type { HyperframesProjectDetail } from "@/lib/hyperframes-types";

export default async function HyperframesProjectStudioPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const response = await fetch(hyperframesServiceUrl(`/projects/${encodeURIComponent(projectId)}`), {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Could not load project ${projectId}`);
  }

  const project = (await response.json()) as HyperframesProjectDetail;
  const projectRoute = `/hyperframes/projects/${project.project_id}` as Route;
  const homeRoute = "/hyperframes" as Route;
  const activeRevision = project.revisions.find(
    (revision) => revision.revision_id === project.active_revision_id,
  );

  return (
    <main className="space-y-6">
      <nav className="flex flex-wrap items-center gap-4 text-sm text-zinc-500">
        <Link href={homeRoute} className="hover:text-zinc-200">
          ← Back to Hyperframes home
        </Link>
        <Link href={projectRoute} className="hover:text-zinc-200">
          Back to project detail
        </Link>
      </nav>

      <section className="rounded-[1.75rem] border border-zinc-800/80 bg-zinc-900/55 p-5 shadow-[0_24px_70px_rgba(0,0,0,0.25)] sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300/80">
              Project Studio
            </p>
            <h1 className="font-display text-3xl text-white">{project.name}</h1>
            <p className="text-sm text-zinc-400">
              Active revision: <span className="font-mono text-zinc-200">{project.active_revision_id}</span>
              {" · "}
              Template: <span className="font-mono text-zinc-200">{project.template_family}</span>
            </p>
            <p className="max-w-3xl text-sm leading-6 text-zinc-400">
              This is the project-scoped Studio surface for preview and detailed edits. The current
              HyperFrames preview server is still shared underneath, but the Smart Cut Reel shell is
              now bound to this project context and revision.
            </p>
          </div>

          <div className="flex flex-wrap items-start gap-3">
            {activeRevision ? (
              <HyperframesRenderDraftButton
                projectId={project.project_id}
                revisionId={activeRevision.revision_id}
              />
            ) : null}
            <Link
              href={projectRoute}
              className="inline-flex rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:border-zinc-500"
            >
              View project detail
            </Link>
          </div>
        </div>

        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <StudioMetric label="Project ID" value={project.project_id} />
          <StudioMetric label="Active revision" value={project.active_revision_id} />
          <StudioMetric label="Brand preset" value={project.brand_theme} />
        </div>
      </section>

      <HyperframesStudioEmbed immersive />
    </main>
  );
}

function StudioMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
      <p className="text-xs uppercase tracking-widest text-zinc-500">{label}</p>
      <p className="mt-2 break-all font-mono text-sm text-zinc-100">{value}</p>
    </div>
  );
}