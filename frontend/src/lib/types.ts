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

/** Canonical pipeline presets returned by `GET …/status` (legacy IDs normalized server-side). */
export type PipelineId =
  | "reframe_16x9_to_9x16"
  | "reframe_16x9_to_9x16_smooth_audio"
  | "reframe_16x9_to_9x16_dead_air"
  | "reframe_16x9_to_9x16_dead_air_enhanced"
  | "reframe_16x9_to_9x16_audio_quality";

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

export interface StepProgress {
  current_seconds: number;
  total_seconds: number;
  percent: number;
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
  progress?: StepProgress;
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

export type AudioProfileId = "original" | "podcast" | "social" | "broadcast";

/** Final MP4 mux audio: embedded source track vs mono enhanced WAV timeline. */
export type OutputAudioSourceId = "source_video" | "enhanced_wav";

/** Which WAV Silero VAD analyzes before cut planning. */
export type VadAudioSourceId =
  | "extracted_audio"
  | "enhanced_audio"
  | "enhanced_audio_or_extracted";

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
  /** Set when the client chose an audio preset at job creation. */
  audio_profile?: AudioProfileId | null;
  /** Snapshot of `service_config.audio_enhancement` for dashboards (pipelines with that step). */
  audio_enhancement?: Record<string, unknown> | null;
  /** From `service_config.render_plan_compiler.output_audio_source` when set. */
  output_audio_source?: OutputAudioSourceId | null;
  /** From `service_config.voice_activity_detection.audio_source` when set. */
  vad_audio_source?: VadAudioSourceId | null;
  paths: JobPaths;
}

export const STEP_ORDER_REFRAME_ONLY: StepName[] = [
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

/** Reframe + extract/enhance audio for mux; no VAD or dead-air cuts (11 steps). */
export const STEP_ORDER_SMOOTH_AUDIO: StepName[] = [
  "validation",
  "media_metadata",
  "audio_extraction",
  "audio_enhancement",
  "proxy_frame_sampling",
  "body_detection",
  "track_interpolation",
  "reframe_planning",
  "easing_smoothing",
  "render_plan_compiler",
  "ffmpeg_renderer",
];

export const STEP_ORDER_DEAD_AIR: StepName[] = [
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

/** Dead air + FFmpeg enhancement chain; no ASR / transcription step. */
export const STEP_ORDER_DEAD_AIR_ENHANCED: StepName[] = [
  "validation",
  "media_metadata",
  "audio_extraction",
  "audio_enhancement",
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

export const STEP_ORDER_AUDIO_QUALITY: StepName[] = [
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

/** Default preset: smooth vertical reframe only (9 steps, no audio enhancement). */
export const PIPELINE_ID_REFRAME_ONLY: PipelineId = "reframe_16x9_to_9x16";
/** Smooth reframe + audio extract/enhance for output mux (11 steps). */
export const PIPELINE_ID_REFRAME_SMOOTH_AUDIO: PipelineId = "reframe_16x9_to_9x16_smooth_audio";
/** Reframe + dead-air cutting (VAD + cut plan before vision). */
export const PIPELINE_ID_REFRAME_DEAD_AIR: PipelineId = "reframe_16x9_to_9x16_dead_air";
/** Reframe + dead air + audio enhancement (no transcription step). */
export const PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED: PipelineId =
  "reframe_16x9_to_9x16_dead_air_enhanced";
/** Reframe + dead air + audio enhancement + ASR / filler cuts. */
export const PIPELINE_ID_REFRAME_AUDIO_QUALITY: PipelineId = "reframe_16x9_to_9x16_audio_quality";

/** Fallback step order when API omits `pipeline.steps` */
export const STEP_ORDER = STEP_ORDER_REFRAME_ONLY;

export const TERMINAL_STATUSES: OverallStatus[] = ["success", "failed"];

export function isTerminalStatus(status: OverallStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export const PIPELINE_IDS_WITH_DEAD_AIR: PipelineId[] = [
  PIPELINE_ID_REFRAME_DEAD_AIR,
  PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED,
  PIPELINE_ID_REFRAME_AUDIO_QUALITY,
];

/** Presets that run faster-whisper (transcription step). */
export const PIPELINE_IDS_WITH_TRANSCRIPTION: PipelineId[] = [PIPELINE_ID_REFRAME_AUDIO_QUALITY];

export const PIPELINE_IDS_WITH_AUDIO_QUALITY: PipelineId[] = [PIPELINE_ID_REFRAME_AUDIO_QUALITY];

/** One row from ``vad_segments.json`` (Silero / VAD timeline). */
export interface VadTimelineSegment {
  start: number;
  end: number;
  type: "speech" | "silence";
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
