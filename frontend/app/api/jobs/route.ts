import { NextResponse, type NextRequest } from "next/server";

import { orchestratorUrl } from "@/lib/orchestrator";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const formData = await request.formData();

  const upstream = await fetch(orchestratorUrl("/jobs"), {
    method: "POST",
    body: formData,
  });

  return forwardJson(upstream);
}

async function forwardJson(upstream: Response): Promise<NextResponse> {
  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
