import { UploadForm } from "@/components/UploadForm";

export default function HomePage() {
  return (
    <main className="space-y-14">
      <header className="space-y-5">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400/90">
          Smart Cut Reel · Local pipeline UI
        </p>
        <h1 className="font-display text-4xl font-semibold tracking-tight text-white sm:text-[2.75rem] sm:leading-[1.1]">
          Automated vertical video from 16:9 sources
        </h1>
        <p className="max-w-2xl text-lg leading-relaxed text-zinc-400">
          This tool runs the Smart Cut Reel orchestrator: it reframes horizontal clips into a{" "}
          <strong className="font-medium text-zinc-200">smooth 9:16</strong> output with
          subject-aware cropping. You can optionally trim long silences, clean up audio, and remove
          filler words before the final render — pick what you need below, then upload and track the
          job on the next screen.
        </p>
      </header>

      <section aria-labelledby="tiers-heading" className="space-y-5">
        <div className="flex flex-col gap-1">
          <h2 id="tiers-heading" className="font-display text-xl font-semibold text-zinc-50">
            What you can turn on
          </h2>
          <p className="text-sm text-zinc-500">
            Options combine into one of three pipeline presets (9, 12, or 14 processing steps).
          </p>
        </div>
        <ul className="grid gap-4 sm:grid-cols-3">
          <li className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5 shadow-sm ring-1 ring-white/[0.03]">
            <p className="font-display text-sm font-semibold text-emerald-300/95">
              Reframe only
            </p>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Vision path only: proxy frames, body tracks, reframing, easing, render — fastest path,
              no audio editing.
            </p>
            <p className="mt-3 font-mono text-[11px] text-zinc-600">9 steps</p>
          </li>
          <li className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5 shadow-sm ring-1 ring-white/[0.03]">
            <p className="font-display text-sm font-semibold text-violet-300/95">
              + Dead air removal
            </p>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Adds extract → VAD → cut planning so long silent gaps can be removed before reframing.
              Recommended for podcasts and talking-head cuts.
            </p>
            <p className="mt-3 font-mono text-[11px] text-zinc-600">12 steps</p>
          </li>
          <li className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5 shadow-sm ring-1 ring-white/[0.03]">
            <p className="font-display text-sm font-semibold text-amber-300/95">
              + Audio quality chain
            </p>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Builds on dead air: ffmpeg cleanup & loudness, Silero VAD, optional faster-whisper ASR
              to drop filler words (“um”, “uh”, Thai fillers). Heaviest runtime.
            </p>
            <p className="mt-3 font-mono text-[11px] text-zinc-600">14 steps</p>
          </li>
        </ul>
      </section>

      <UploadForm />
    </main>
  );
}
