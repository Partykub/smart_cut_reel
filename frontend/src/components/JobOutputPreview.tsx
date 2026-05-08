"use client";

export function JobOutputPreview({ jobId }: { jobId: string }) {
  const src = `/api/jobs/${encodeURIComponent(jobId)}/output`;

  return (
    <section className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <div>
        <p className="text-xs uppercase tracking-widest text-zinc-500">Output</p>
        <h2 className="text-lg font-medium text-zinc-100">final_9x16.mp4</h2>
      </div>
      <video
        src={src}
        controls
        className="mx-auto max-h-[min(70vh,560px)] w-full max-w-md rounded-md bg-black"
        preload="metadata"
      />
      <div>
        <a
          href={src}
          download={`${jobId}_final_9x16.mp4`}
          className="inline-flex items-center rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white"
        >
          Download MP4
        </a>
      </div>
    </section>
  );
}
