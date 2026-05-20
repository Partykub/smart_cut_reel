import { NextResponse, type NextRequest } from "next/server";

import { hyperframesServiceUrl } from "@/lib/hyperframes-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await params;
  const upstream = await fetch(
    hyperframesServiceUrl(`/projects/${encodeURIComponent(projectId)}/revisions`),
    {
      cache: "no-store",
    },
  );
  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}