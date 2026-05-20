import Link from "next/link";
import type { Route } from "next";

import { HyperframesProjectSetupForm } from "@/components/HyperframesProjectSetupForm";
import { getHyperframesTemplatePreset } from "@/lib/hyperframes-catalog";

const HYPERFRAMES_HOME_ROUTE = "/hyperframes" as Route;

export default async function HyperframesNewProjectPage({
  searchParams,
}: {
  searchParams: Promise<{ preset?: string }>;
}) {
  const { preset: presetId } = await searchParams;
  const preset = getHyperframesTemplatePreset(presetId);

  return (
    <main className="space-y-8">
      <nav className="text-sm text-zinc-500">
        <Link href={HYPERFRAMES_HOME_ROUTE} className="hover:text-zinc-200">
          ← Back to Hyperframes home
        </Link>
      </nav>
      <header className="space-y-4">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300/80">
          Hyperframes Project Setup
        </p>
        <h1 className="font-display text-4xl font-semibold tracking-tight text-white sm:text-[2.75rem] sm:leading-[1.1]">
          Create a project before editing or rendering
        </h1>
        <p className="max-w-3xl text-lg leading-relaxed text-zinc-400">
          This step creates the source-of-truth workspace that the next project-first flow will use
          for Studio edits, revisions, and render jobs.
        </p>
      </header>
      <HyperframesProjectSetupForm preset={preset} />
    </main>
  );
}