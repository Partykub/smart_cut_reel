export type HyperframesTemplateFamily = "auto" | "vertical" | "horizontal";
export type HyperframesDetectedOrientation = "vertical" | "horizontal" | "manual_required";
export type HyperframesJobStatus = "created" | "queued" | "rendering" | "completed" | "failed";
export type HyperframesRevisionType = "draft" | "named" | "final_candidate";
export type HyperframesRenderMode = "draft" | "final";

export interface HyperframesArtifactEntry {
  artifact_key: string;
  object_key: string;
  content_type: string;
  size_bytes: number | null;
  created_at: string;
}

export interface HyperframesSubtitleWord {
  text: string;
  start: number;
  end: number;
}

export interface HyperframesSubtitleSegment {
  text: string | null;
  start: number | null;
  end: number | null;
  words: HyperframesSubtitleWord[];
}

export interface HyperframesSubtitleDocument {
  words: HyperframesSubtitleWord[];
  segments: HyperframesSubtitleSegment[];
}

export interface HyperframesNormalizedAssets {
  source_video: string;
  intro_video: string | null;
  outro_video: string | null;
  logo_image: string | null;
  subtitle_file: string | null;
}

export interface HyperframesRevisionSummary {
  revision_id: string;
  revision_name: string;
  revision_type: HyperframesRevisionType;
  template_family: "vertical" | "horizontal";
  template_variant: string;
  orientation_detected: HyperframesDetectedOrientation;
  workspace_root: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  notes: string | null;
}

export interface HyperframesProjectSummary {
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  template_family: "vertical" | "horizontal";
  template_variant: string;
  orientation_detected: HyperframesDetectedOrientation;
  brand_theme: string;
  subtitle_theme: string;
  active_revision_id: string;
}

export interface HyperframesProjectDetail extends HyperframesProjectSummary {
  created_by: string | null;
  assets: HyperframesNormalizedAssets;
  revisions: HyperframesRevisionSummary[];
  render_jobs: HyperframesRenderJobSummary[];
}

export interface HyperframesRenderJobSummary {
  job_id: string;
  project_id: string | null;
  revision_id: string | null;
  render_mode: HyperframesRenderMode;
  status: HyperframesJobStatus;
  template_family: "vertical" | "horizontal";
  template_variant: string;
  orientation_detected: HyperframesDetectedOrientation;
  progress_percent: number;
  output_url: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface HyperframesJobCreateResponse {
  job_id: string;
  project_id: string | null;
  revision_id: string | null;
  render_mode: HyperframesRenderMode;
  status: HyperframesJobStatus;
  template_family: "vertical" | "horizontal";
  orientation_detected: HyperframesDetectedOrientation;
  progress_percent: number;
}

export interface HyperframesJobStatusResponse {
  job_id: string;
  project_id: string | null;
  revision_id: string | null;
  render_mode: HyperframesRenderMode;
  status: HyperframesJobStatus;
  template_family: "vertical" | "horizontal";
  template_variant: string;
  orientation_detected: HyperframesDetectedOrientation;
  progress_percent: number;
  output_url: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  artifacts: Record<string, HyperframesArtifactEntry>;
}

export function isTerminalHyperframesStatus(status: HyperframesJobStatus): boolean {
  return status === "completed" || status === "failed";
}
