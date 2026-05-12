import http from "node:http";
import https from "node:https";

import { NextResponse, type NextRequest } from "next/server";

import { orchestratorUrl } from "@/lib/orchestrator";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
): Promise<NextResponse> {
  const { jobId } = await params;

  const upstream = await postWithoutHeadersTimeout(
    orchestratorUrl(`/jobs/${encodeURIComponent(jobId)}/run`),
  );

  return new NextResponse(upstream.body, {
    status: upstream.statusCode,
    headers: {
      "content-type":
        upstream.headers["content-type"] ?? "application/json",
    },
  });
}

type UpstreamResponse = {
  statusCode: number;
  headers: Record<string, string>;
  body: string;
};

function postWithoutHeadersTimeout(url: string): Promise<UpstreamResponse> {
  const target = new URL(url);
  const transport = target.protocol === "https:" ? https : http;

  return new Promise((resolve, reject) => {
    const request = transport.request(
      target,
      {
        method: "POST",
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk: Buffer | string) => {
          chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
        });
        response.on("end", () => {
          const headers: Record<string, string> = {};
          for (const [key, value] of Object.entries(response.headers)) {
            if (typeof value === "string") {
              headers[key] = value;
            } else if (Array.isArray(value)) {
              headers[key] = value.join(", ");
            }
          }
          resolve({
            statusCode: response.statusCode ?? 500,
            headers,
            body: Buffer.concat(chunks).toString("utf-8"),
          });
        });
      },
    );

    request.on("error", reject);
    request.end();
  });
}
