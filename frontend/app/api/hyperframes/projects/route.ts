import { NextResponse, type NextRequest } from "next/server";

import { hyperframesServiceUrl } from "@/lib/hyperframes-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const incoming = await request.formData();
  const outgoing = new FormData();
  for (const [key, value] of incoming.entries()) {
    outgoing.append(key, value);
  }

  const upstream = await fetch(hyperframesServiceUrl("/projects"), {
    method: "POST",
    body: outgoing,
  });

  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(): Promise<NextResponse> {
  const upstream = await fetch(hyperframesServiceUrl("/projects"), {
    cache: "no-store",
  });
  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}