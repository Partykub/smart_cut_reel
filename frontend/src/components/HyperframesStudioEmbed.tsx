const studioUrl = "http://127.0.0.1:3002";
const studioStartCommand = "cd services/hyperframes_finishing/hyperframes && npm run studio";

export function HyperframesStudioEmbed({ immersive = false }: { immersive?: boolean }) {
  const sectionClassName = immersive
    ? "space-y-5"
    : "space-y-5 rounded-[2rem] border border-zinc-800/80 bg-zinc-900/55 p-4 shadow-2xl ring-1 ring-white/[0.04] sm:p-6";
  const frameShellClassName = immersive
    ? "overflow-hidden rounded-[1.5rem] border border-zinc-800 bg-black shadow-[0_30px_90px_rgba(0,0,0,0.35)]"
    : "overflow-hidden rounded-[1.75rem] border border-zinc-800 bg-black shadow-[0_30px_90px_rgba(0,0,0,0.35)]";
  const frameClassName = immersive
    ? "h-[calc(100vh-14rem)] min-h-[780px] w-full bg-black"
    : "h-[78vh] min-h-[720px] w-full bg-black";

  return (
    <section className={sectionClassName}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-cyan-300/80">
            Hyperframes Studio
          </p>
          <h2 className="font-display text-2xl font-semibold tracking-tight text-white sm:text-3xl">
            {immersive
              ? "Full-screen workspace for timeline and preview work"
              : "Embedded editor shell for timeline and preview work"}
          </h2>
          <p className="max-w-3xl text-sm leading-6 text-zinc-400 sm:text-base">
            This mounts the real Hyperframes Studio preview server in an iframe so we can keep the
            official editor UI now, then replace scenes and controls incrementally inside our own
            workflow later.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <a
            href={studioUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex rounded-full border border-cyan-300/40 px-4 py-2 text-sm font-medium text-cyan-200 transition hover:border-cyan-200 hover:text-cyan-100"
          >
            Open studio in new tab
          </a>
        </div>
      </div>

      <div className="rounded-3xl border border-zinc-800/80 bg-zinc-950/70 p-4 text-sm text-zinc-300">
        <p className="font-medium text-zinc-100">Start the local studio preview</p>
        <p className="mt-1 text-zinc-500">
          Run this once if the embedded frame is blank or the studio server is not running.
        </p>
        <pre className="mt-3 overflow-x-auto rounded-2xl bg-black/40 px-4 py-3 font-mono text-xs text-cyan-200">
          {studioStartCommand}
        </pre>
      </div>

      <div className={frameShellClassName}>
        <iframe
          title="Hyperframes Studio"
          src={studioUrl}
          allow="autoplay; fullscreen"
          className={frameClassName}
        />
      </div>
    </section>
  );
}