import { NextResponse, type NextRequest } from "next/server";

import { orchestratorUrl } from "@/lib/orchestrator";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
): Promise<NextResponse> {
  const { jobId } = await params;

  const upstream = await fetch(
    orchestratorUrl(`/jobs/${encodeURIComponent(jobId)}/status`),
    { cache: "no-store" },
  );

  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
