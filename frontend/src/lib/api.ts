import type { JobStatusResponse } from "./types";

async function unwrap<T>(response: Response): Promise<T> {
  const rawBody = await response.text();

  if (!response.ok) {
    let detail = rawBody;
    try {
      const body = JSON.parse(rawBody) as { detail?: unknown };
      detail =
        typeof body?.detail === "string"
          ? body.detail
          : JSON.stringify(body);
    } catch {
      // Keep the raw response body when it is not valid JSON.
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return JSON.parse(rawBody) as T;
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
