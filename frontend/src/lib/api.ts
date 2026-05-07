import type { JobStatusResponse } from "./types";

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail =
        typeof body?.detail === "string"
          ? body.detail
          : JSON.stringify(body);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return (await response.json()) as T;
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
