import { NextResponse, type NextRequest } from "next/server";

import { hyperframesServiceUrl } from "@/lib/hyperframes-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
): Promise<NextResponse> {
  const { jobId } = await params;
  const upstream = await fetch(hyperframesServiceUrl(`/jobs/${encodeURIComponent(jobId)}/output`), {
    cache: "no-store",
  });
  if (!upstream.ok) {
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  }
  const blob = await upstream.blob();
  return new NextResponse(blob, {
    status: 200,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "video/mp4",
      "cache-control": "no-store",
    },
  });
}
