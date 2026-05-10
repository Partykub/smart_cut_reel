import { NextResponse, type NextRequest } from "next/server";

import { orchestratorUrl } from "@/lib/orchestrator";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const incoming = await request.formData();
  // Rebuild FormData: forwarding the Request's FormData directly to `fetch` has
  // been observed to drop non-file fields in some Node/undici + Next versions,
  // which makes FastAPI fall back to default `pipeline_id` (reframe-only preset).
  const outgoing = new FormData();
  for (const [key, value] of incoming.entries()) {
    outgoing.append(key, value);
  }

  const upstream = await fetch(orchestratorUrl("/jobs"), {
    method: "POST",
    body: outgoing,
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
