import Link from "next/link";

import { JobDashboard } from "@/components/JobDashboard";

export default async function JobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  return (
    <main className="space-y-6">
      <nav className="text-sm text-zinc-500">
        <Link href="/" className="hover:text-zinc-200">
          ← New job
        </Link>
      </nav>
      <JobDashboard jobId={jobId} />
    </main>
  );
}
