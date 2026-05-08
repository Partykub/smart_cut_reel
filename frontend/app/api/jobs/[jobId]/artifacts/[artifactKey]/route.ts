import { NextResponse, type NextRequest } from "next/server";

import { orchestratorUrl } from "@/lib/orchestrator";

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
        orchestratorUrl(
            `/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactKey)}`,
        ),
        { cache: "no-store" },
    );

    if (!upstream.ok) {
        const body = await upstream.text();
        return new NextResponse(body, {
            status: upstream.status,
            headers: {
                "content-type":
                    upstream.headers.get("content-type") ?? "application/json",
            },
        });
    }

    const blob = await upstream.blob();
    return new NextResponse(blob, {
        status: 200,
        headers: {
            "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
            "cache-control": "no-store",
        },
    });
}