import type {
  HyperframesJobCreateResponse,
  HyperframesJobStatusResponse,
  HyperframesProjectDetail,
  HyperframesProjectSummary,
} from "./hyperframes-types";

async function unwrap<T>(response: Response): Promise<T> {
  const rawText = await response.text();
  if (!response.ok) {
    let detail = rawText;
    if (rawText) {
      try {
        const body = JSON.parse(rawText) as { detail?: unknown };
        if (typeof body?.detail === "string") {
          detail = body.detail;
        }
      } catch {
        // Keep raw text
      }
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  if (!rawText) {
    throw new Error("Empty response body");
  }
  return JSON.parse(rawText) as T;
}

export async function createHyperframesJob(formData: FormData): Promise<HyperframesJobCreateResponse> {
  const response = await fetch("/api/hyperframes/jobs", {
    method: "POST",
    body: formData,
  });
  return unwrap<HyperframesJobCreateResponse>(response);
}

export async function createHyperframesProject(formData: FormData): Promise<HyperframesProjectDetail> {
  const response = await fetch("/api/hyperframes/projects", {
    method: "POST",
    body: formData,
  });
  return unwrap<HyperframesProjectDetail>(response);
}

export async function listHyperframesProjects(): Promise<HyperframesProjectSummary[]> {
  const response = await fetch("/api/hyperframes/projects", {
    cache: "no-store",
  });
  return unwrap<HyperframesProjectSummary[]>(response);
}

export async function getHyperframesProject(
  projectId: string,
): Promise<HyperframesProjectDetail> {
  const response = await fetch(`/api/hyperframes/projects/${encodeURIComponent(projectId)}`, {
    cache: "no-store",
  });
  return unwrap<HyperframesProjectDetail>(response);
}

export async function renderHyperframesProjectDraft(
  projectId: string,
  revisionId?: string,
): Promise<HyperframesJobCreateResponse> {
  const query = revisionId
    ? `?revision_id=${encodeURIComponent(revisionId)}`
    : "";
  const response = await fetch(`/api/hyperframes/projects/${encodeURIComponent(projectId)}/render-draft${query}`, {
    method: "POST",
  });
  return unwrap<HyperframesJobCreateResponse>(response);
}

export async function getHyperframesJobStatus(
  jobId: string,
): Promise<HyperframesJobStatusResponse> {
  const response = await fetch(`/api/hyperframes/jobs/${encodeURIComponent(jobId)}/status`, {
    cache: "no-store",
  });
  return unwrap<HyperframesJobStatusResponse>(response);
}

export async function runHyperframesJob(jobId: string): Promise<HyperframesJobStatusResponse> {
  const response = await fetch(`/api/hyperframes/jobs/${encodeURIComponent(jobId)}/run`, {
    method: "POST",
  });
  return unwrap<HyperframesJobStatusResponse>(response);
}
