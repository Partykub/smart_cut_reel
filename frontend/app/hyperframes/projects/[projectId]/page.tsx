import Link from "next/link";
import type { Route } from "next";

import { HyperframesProjectDashboard } from "@/components/HyperframesProjectDashboard";
import { hyperframesServiceUrl } from "@/lib/hyperframes-service";
import type { HyperframesProjectDetail } from "@/lib/hyperframes-types";

const HYPERFRAMES_HOME_ROUTE = "/hyperframes" as Route;

export default async function HyperframesProjectDetailPage({
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

  return (
    <main className="space-y-6">
      <nav className="text-sm text-zinc-500">
        <Link href={HYPERFRAMES_HOME_ROUTE} className="hover:text-zinc-200">
          ← Back to Hyperframes home
        </Link>
      </nav>
      <HyperframesProjectDashboard project={project} />
    </main>
  );
}