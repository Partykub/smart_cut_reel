import { UploadForm } from "@/components/UploadForm";
import Link from "next/link";
import type { Route } from "next";

const HYPERFRAMES_STUDIO_ROUTE = "/hyperframes" as Route;

export default function HomePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-5">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400/90">
          Smart Cut Reel · Local pipeline UI
        </p>
        <div>
          <Link
            href={HYPERFRAMES_STUDIO_ROUTE}
            className="text-sm text-amber-300 transition hover:text-amber-200"
          >
            Open Hyperframes finishing studio →
          </Link>
        </div>
        <h1 className="font-display text-4xl font-semibold tracking-tight text-white sm:text-[2.75rem] sm:leading-[1.1]">
          Turn 16:9 footage into vertical video
        </h1>
        <p className="max-w-2xl text-lg leading-relaxed text-zinc-400">
          This UI drives the Smart Cut Reel orchestrator: smooth{" "}
          <strong className="font-medium text-zinc-200">9:16 reframes</strong> with subject-aware
          framing. Optionally trim long silence (with an audio prep step before VAD) and remove
          filler words before the final render — pick what you need below, upload, then open the
          job page to track progress.
        </p>
      </header>

      <UploadForm />
    </main>
  );
}
