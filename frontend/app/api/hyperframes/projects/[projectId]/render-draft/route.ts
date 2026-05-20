import { NextResponse, type NextRequest } from "next/server";

import { hyperframesServiceUrl } from "@/lib/hyperframes-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await params;
  const revisionId = request.nextUrl.searchParams.get("revision_id");
  const upstreamUrl = new URL(hyperframesServiceUrl(`/projects/${encodeURIComponent(projectId)}/render-draft`));
  upstreamUrl.searchParams.set("start_immediately", "true");
  if (revisionId) {
    upstreamUrl.searchParams.set("revision_id", revisionId);
  }

  const upstream = await fetch(upstreamUrl, {
    method: "POST",
  });

  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}