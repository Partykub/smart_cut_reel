import { NextResponse, type NextRequest } from "next/server";

import { hyperframesServiceUrl } from "@/lib/hyperframes-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  {
    params,
  }: { params: Promise<{ jobId: string; artifactKey: string }> },
): Promise<NextResponse> {
  const { jobId, artifactKey } = await params;
  const upstream = await fetch(
    hyperframesServiceUrl(
      `/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactKey)}`
    ),
    { cache: "no-store" },
  );

  const body = await upstream.arrayBuffer();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "cache-control": "no-store",
    },
  });
}