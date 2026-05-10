# Shared Contracts

This directory is the source of truth for the cross-service contract.

Status:

- P1-A01 completed on 2026-05-06 — Phase 1 (single 16:9 → 9:16 smooth reframe).
- P2-A01/A02 completed — Phase 2 adds audio extraction, voice activity detection, and dead air cut planning while keeping Phase 1 manifests valid.

## Scope

- Phase 1: one input video, one 9:16 output video, no database, no multi-cam, no auth, no timeline editing contract.
- Phase 2: same single-input/single-output shape as Phase 1 plus three audio-driven steps that produce a cut plan; renderer extends to trim+crop+concat in one pass.
- The contract package covers `job_manifest.json`, `artifact_manifest.json`, and `service_status.json`.
- Per-service `/run` request and response payloads stay implementation-defined per service.

## Files

- `job_manifest.schema.json`: orchestrator-owned job configuration. Supports both Phase 1 and Phase 2 jobs via `pipeline.oneOf`.
- `artifact_manifest.schema.json`: orchestrator-owned registry of artifacts. Phase 2 adds `extracted_audio`, `vad_segments`, `cut_plan`.
- `service_status.schema.json`: orchestrator-owned pipeline execution state. Phase 2 adds three new step states via `oneOf` between Phase 1 and Phase 2 step shapes.
- `examples/`: sample JSON files for job creation, mid-pipeline execution, and completion (Phase 1 + Phase 2 sample job).

## Shared Rules

- `schema_version` is `1.0.0` for Phase 1 manifests and `2.0.0` for Phase 2 manifests. Both values are accepted by the schemas.
- `job_id` uses the form `job_<suffix>` and is embedded into every MinIO object key.
- All timestamps use ISO 8601 UTC strings.
- Orchestrator is the single writer for manifest files and `service_status.json`.
- Each service writes only its own artifact or output object and returns that location to Orchestrator.
- `artifact_manifest.json` records only artifacts that already exist. Pending work stays in `service_status.json`.
- Warnings are structured objects with `code`, `message`, `step`, and `created_at`.
- Errors are plain strings at the top level of `service_status.json`.
- Spatial coordinates in downstream artifacts must use source-video resolution, even when detection runs on proxy media.
- Time coordinates in `vad_segments.json` and `cut_plan.json` are measured against the source-video timeline.

## Pipeline Step IDs

These step IDs are canonical and must be used consistently across Orchestrator, services, fixtures, and UI.

### Smooth vertical reframe only (`pipeline_id = reframe_16x9_to_9x16`)

1. `validation`
2. `media_metadata`
3. `proxy_frame_sampling`
4. `body_detection`
5. `track_interpolation`
6. `reframe_planning`
7. `easing_smoothing`
8. `render_plan_compiler`
9. `ffmpeg_renderer`

### Reframe + dead-air cuts (`pipeline_id = reframe_16x9_to_9x16_dead_air`)

1. `validation`
2. `media_metadata`
3. `audio_extraction`
4. `voice_activity_detection`
5. `dead_air_cut_planning`
6. `proxy_frame_sampling`
7. `body_detection`
8. `track_interpolation`
9. `reframe_planning`
10. `easing_smoothing`
11. `render_plan_compiler`
12. `ffmpeg_renderer`

### Reframe + dead-air + audio quality (`pipeline_id = reframe_16x9_to_9x16_audio_quality`)

1. `validation`
2. `media_metadata`
3. `audio_extraction`
4. `audio_enhancement`
5. `voice_activity_detection`
6. `transcription`
7. `dead_air_cut_planning`
8. `proxy_frame_sampling`
9. `body_detection`
10. `track_interpolation`
11. `reframe_planning`
12. `easing_smoothing`
13. `render_plan_compiler`
14. `ffmpeg_renderer`

Manifest `schema_version` is `3.0.0`.

## Artifact Registry Keys

| Key | Object Key Pattern | Produced By | Consumer Examples |
| --- | --- | --- | --- |
| `metadata` | `jobs/{job_id}/artifacts/metadata.json` | `media_metadata` | validation, reframe planning, render plan compiler |
| `extracted_audio` | `jobs/{job_id}/artifacts/extracted_audio.wav` | `audio_extraction` | voice activity detection |
| `vad_segments` | `jobs/{job_id}/artifacts/vad_segments.json` | `voice_activity_detection` | dead air cut planning |
| `cut_plan` | `jobs/{job_id}/artifacts/cut_plan.json` | `dead_air_cut_planning` | render plan compiler, debug frontend |
| `proxy` | `jobs/{job_id}/artifacts/proxy.mp4` | `proxy_frame_sampling` | body detection |
| `sampled_frames` | `jobs/{job_id}/artifacts/sampled_frames.json` | `proxy_frame_sampling` | body detection |
| `body_tracks_raw` | `jobs/{job_id}/artifacts/body_tracks_raw.json` | `body_detection` | track interpolation |
| `body_tracks_interpolated` | `jobs/{job_id}/artifacts/body_tracks_interpolated.json` | `track_interpolation` | reframe planning |
| `reframe_plan_raw` | `jobs/{job_id}/artifacts/reframe_plan_raw.json` | `reframe_planning` | easing and smoothing |
| `reframe_plan_smooth` | `jobs/{job_id}/artifacts/reframe_plan_smooth.json` | `easing_smoothing` | render plan compiler |
| `render_plan` | `jobs/{job_id}/artifacts/render_plan.json` | `render_plan_compiler` | ffmpeg renderer |
| `final_9x16` | `jobs/{job_id}/outputs/final_9x16.mp4` | `ffmpeg_renderer` | debug frontend, download flow |

## Manifest Lifecycle

1. Job creation writes `job_manifest.json`, initializes an empty `artifact_manifest.json`, and writes `service_status.json` with every step from `pipeline.steps` marked `pending`.
2. Before a step starts, Orchestrator updates `service_status.json` so the overall job is `running` and `current_step` matches the step ID.
3. When a step succeeds, the service writes its output object, Orchestrator appends the output to `artifact_manifest.json`, and then marks the step `success` in `service_status.json`.
4. If a step fails hard, Orchestrator writes a plain-string error to `service_status.json`, marks the failing step `failed`, sets the overall job status to `failed`, and stops the pipeline.
5. Soft fallbacks such as missing body detections or feature-disabled cut plans should still produce the expected artifact and emit a structured warning instead of failing the job.

## Dead-air feature toggle

- Dead-air preset jobs may include `enabled_features.remove_dead_air`. When `false`, `dead_air_cut_planning` still runs and emits an identity cut plan (one keep segment covering the full duration), so the renderer can fall back to reframe-only behavior without conditional pipeline branches.
- Reframe-only preset jobs do not include `enabled_features` at all; the schema treats it as optional.

## Ownership Boundaries

- Services must not write other services' artifact keys.
- `service_status.json` must not duplicate artifact locations.
- `artifact_manifest.json` must not invent new keys outside the fixed registry without a contract update.
- `job_manifest.json` is the request contract and should stay small; runtime metrics and derived metadata belong in artifacts.

## Example Fixtures

- `examples/job_manifest.reframe_16x9_to_9x16.sample.json`: representative reframe-only job (`schema_version 1.0.0`).
- `examples/job_manifest.reframe_16x9_to_9x16_dead_air.sample.json`: dead-air preset with `remove_dead_air = true` and `compiler_render_mode = smooth_crop_with_cuts`.
- `examples/job_manifest.reframe_16x9_to_9x16_audio_quality.sample.json`: audio-quality preset (`schema_version 3.0.0`).
- `examples/artifact_manifest.created.sample.json`: initial empty registry.
- `examples/artifact_manifest.running.sample.json`: partial registry after early media steps.
- `examples/artifact_manifest.completed.sample.json`: full Phase 1 registry including the final output.
- `examples/service_status.created.sample.json`: initial pending state.
- `examples/service_status.running.sample.json`: mid-pipeline state while body detection is running.
- `examples/service_status.completed.sample.json`: completed state with one non-fatal warning.

## Exclusions

- No multi-camera roles or speaker diarization fields.
- No extra timeline contracts beyond these presets (split-screen, reaction shot, professional export).
- No render-command schema beyond the render plan artifact reference.
- No database schema, auth schema, or frontend view-model schema.
