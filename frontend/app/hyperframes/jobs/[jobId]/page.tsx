import Link from "next/link";
import type { Route } from "next";

import { HyperframesJobDashboard } from "@/components/HyperframesJobDashboard";

const HYPERFRAMES_STUDIO_ROUTE = "/hyperframes" as Route;

export default async function HyperframesJobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  return (
    <main className="space-y-6">
      <nav className="text-sm text-zinc-500">
        <Link href={HYPERFRAMES_STUDIO_ROUTE} className="hover:text-zinc-200">
          ← Back to Hyperframes studio
        </Link>
      </nav>
      <HyperframesJobDashboard jobId={jobId} />
    </main>
  );
}
