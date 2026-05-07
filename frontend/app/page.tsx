import { UploadForm } from "@/components/UploadForm";

export default function HomePage() {
  return (
    <main className="space-y-8">
      <header>
        <p className="text-sm uppercase tracking-widest text-zinc-500">
          Smart Cut Reel · Debug
        </p>
        <h1 className="mt-2 text-3xl font-semibold">
          Phase 1 — 16:9 to 9:16 Smooth Reframe
        </h1>
        <p className="mt-2 text-zinc-400">
          Upload a single 16:9 source video to create a job, then run the
          pipeline and inspect each artifact as it lands.
        </p>
      </header>
      <UploadForm />
    </main>
  );
}
