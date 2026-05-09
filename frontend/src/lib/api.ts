import type { JobStatusResponse } from "./types";

async function unwrap<T>(response: Response): Promise<T> {
  // Read the body as text first so we can fall back to a plain string when the
  // response isn't valid JSON. Calling response.json() then response.text()
  // throws "body stream already read" because the underlying ReadableStream
  // can only be consumed once.
  const rawText = await response.text();

  if (!response.ok) {
    let detail = rawText;
    if (rawText) {
      try {
        const body = JSON.parse(rawText) as { detail?: unknown };
        if (typeof body?.detail === "string") {
          detail = body.detail;
        } else if (body && typeof body === "object") {
          detail = JSON.stringify(body);
        }
      } catch {
        // rawText is already the best we have
      }
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  if (!rawText) {
    throw new Error("Empty response body");
  }
  return JSON.parse(rawText) as T;
}

export async function createJob(formData: FormData): Promise<JobStatusResponse> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    body: formData,
  });
  return unwrap<JobStatusResponse>(response);
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/status`, {
    cache: "no-store",
  });
  return unwrap<JobStatusResponse>(response);
}

export async function runJob(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/run`, {
    method: "POST",
  });
  return unwrap<JobStatusResponse>(response);
}
