export type StepName =
  | "validation"
  | "media_metadata"
  | "proxy_frame_sampling"
  | "body_detection"
  | "track_interpolation"
  | "reframe_planning"
  | "easing_smoothing"
  | "render_plan_compiler"
  | "ffmpeg_renderer";

export type StepStatus = "pending" | "running" | "success" | "failed";

export type OverallStatus = StepStatus;

export interface StepState {
  status: StepStatus;
  started_at: string | null;
  finished_at: string | null;
}

export interface ServiceWarning {
  code: string;
  message: string;
  step: StepName;
  created_at: string;
}

export interface ServiceStatus {
  schema_version: string;
  job_id: string;
  status: OverallStatus;
  current_step: StepName | null;
  updated_at: string;
  steps: Record<StepName, StepState>;
  warnings: ServiceWarning[];
  errors: string[];
}

export interface ArtifactEntry {
  object_key: string;
  produced_by: StepName;
  created_at: string;
  content_type?: string;
  size_bytes?: number;
}

export interface JobPaths {
  job_prefix: string;
  input: string;
  job_manifest: string;
  artifact_manifest: string;
  service_status: string;
  output: string;
}

export interface JobStatusResponse {
  job_id: string;
  service_status: ServiceStatus;
  artifacts: Record<string, ArtifactEntry>;
  paths: JobPaths;
}

export const STEP_ORDER: StepName[] = [
  "validation",
  "media_metadata",
  "proxy_frame_sampling",
  "body_detection",
  "track_interpolation",
  "reframe_planning",
  "easing_smoothing",
  "render_plan_compiler",
  "ffmpeg_renderer",
];

export const TERMINAL_STATUSES: OverallStatus[] = ["success", "failed"];

export function isTerminalStatus(status: OverallStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}
