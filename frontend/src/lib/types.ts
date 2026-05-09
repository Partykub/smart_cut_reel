export type StepName =
  | "validation"
  | "media_metadata"
  | "audio_extraction"
  | "audio_enhancement"
  | "voice_activity_detection"
  | "transcription"
  | "dead_air_cut_planning"
  | "proxy_frame_sampling"
  | "body_detection"
  | "track_interpolation"
  | "reframe_planning"
  | "easing_smoothing"
  | "render_plan_compiler"
  | "ffmpeg_renderer";

export type StepStatus = "pending" | "running" | "success" | "failed";

export type OverallStatus = StepStatus;

export type PipelineId =
  | "phase1_smooth_reframe_16x9_to_9x16"
  | "phase2_smooth_reframe_dead_air_cut"
  | "phase3_audio_quality_cut";

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
  steps: Partial<Record<StepName, StepState>>;
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

export interface PipelineSummary {
  pipeline_id: PipelineId;
  steps: StepName[];
}

export interface EnabledFeatures {
  remove_dead_air?: boolean;
  enhance_audio?: boolean;
  remove_filler_words?: boolean;
}

export interface JobStatusResponse {
  job_id: string;
  service_status: ServiceStatus;
  artifacts: Record<string, ArtifactEntry>;
  pipeline?: PipelineSummary;
  enabled_features?: EnabledFeatures;
  paths: JobPaths;
}

export const PHASE_1_STEP_ORDER: StepName[] = [
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

export const PHASE_2_STEP_ORDER: StepName[] = [
  "validation",
  "media_metadata",
  "audio_extraction",
  "voice_activity_detection",
  "dead_air_cut_planning",
  "proxy_frame_sampling",
  "body_detection",
  "track_interpolation",
  "reframe_planning",
  "easing_smoothing",
  "render_plan_compiler",
  "ffmpeg_renderer",
];

export const PHASE_3_STEP_ORDER: StepName[] = [
  "validation",
  "media_metadata",
  "audio_extraction",
  "audio_enhancement",
  "voice_activity_detection",
  "transcription",
  "dead_air_cut_planning",
  "proxy_frame_sampling",
  "body_detection",
  "track_interpolation",
  "reframe_planning",
  "easing_smoothing",
  "render_plan_compiler",
  "ffmpeg_renderer",
];

export const PHASE_1_PIPELINE_ID: PipelineId = "phase1_smooth_reframe_16x9_to_9x16";
export const PHASE_2_PIPELINE_ID: PipelineId = "phase2_smooth_reframe_dead_air_cut";
export const PHASE_3_PIPELINE_ID: PipelineId = "phase3_audio_quality_cut";

export const STEP_ORDER = PHASE_1_STEP_ORDER;

export const TERMINAL_STATUSES: OverallStatus[] = ["success", "failed"];

export function isTerminalStatus(status: OverallStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export interface CutPlanSegment {
  source_start: number;
  source_end: number;
}

export interface CutPlan {
  schema_version: string;
  job_id: string;
  feature_enabled: boolean;
  source_duration_seconds: number;
  config_used: {
    silence_threshold_seconds: number;
    keep_padding_before: number;
    keep_padding_after: number;
    min_keep_segment_seconds: number;
    filler_padding_before?: number;
    filler_padding_after?: number;
    merge_adjacent_cuts_within_seconds?: number;
  };
  keep_segments: CutPlanSegment[];
  metrics: {
    total_kept_seconds: number;
    total_removed_seconds: number;
    removed_silence_seconds?: number;
    removed_filler_seconds?: number;
    filler_word_count?: number;
    cut_count: number;
    compression_ratio: number;
  };
  plan_warnings?: Array<Record<string, unknown>>;
}

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  confidence: number | null;
  is_filler?: boolean;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  words: TranscriptWord[];
}

export interface Transcript {
  schema_version: string;
  job_id: string;
  audio_object_key: string;
  model: string;
  compute_type: string;
  language: string;
  segments: TranscriptSegment[];
  metrics: {
    total_words: number;
    filler_word_count: number;
    average_confidence: number | null;
    skipped_reason?: string;
    speech_segment_count_input?: number;
  };
}
