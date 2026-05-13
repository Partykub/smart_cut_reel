"use client";

export function JobOutputPreview({
  jobId,
  artifactKey,
  title,
  eyebrow = "Output",
  downloadName,
  videoClassName = "mx-auto max-h-[min(70vh,560px)] w-full max-w-md rounded-md bg-black",
  optionsSummary,
}: {
  jobId: string;
  artifactKey: string;
  title: string;
  eyebrow?: string;
  downloadName: string;
  videoClassName?: string;
  /** Multi-line Thai summary: preset flags + audio mux mode (shown above the player). */
  optionsSummary?: string | null;
}) {
  const src = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactKey)}`;

  return (
    <section className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <div>
        <p className="text-xs uppercase tracking-widest text-zinc-500">{eyebrow}</p>
        <h2 className="text-lg font-medium text-zinc-100">{title}</h2>
      </div>
      {optionsSummary ? (
        <p className="whitespace-pre-line rounded-md border border-zinc-800/90 bg-zinc-950/70 px-3 py-2 text-xs leading-relaxed text-zinc-300">
          {optionsSummary}
        </p>
      ) : null}
      <video
        src={src}
        controls
        className={videoClassName}
        preload="metadata"
      />
      <div>
        <a
          href={src}
          download={downloadName}
          className="inline-flex items-center rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white"
        >
          Download MP4
        </a>
      </div>
    </section>
  );
}
