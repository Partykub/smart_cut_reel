# Phase 1 Shared Contracts

This directory is the source of truth for P1-A01.

Status: P1-A01 completed on 2026-05-06.

## Scope

- Phase 1 only: one input video, one 9:16 output video, no database, no multi-cam, no auth, no timeline editing contract.
- The contract package covers only `job_manifest.json`, `artifact_manifest.json`, and `service_status.json`.
- Per-service `/run` request and response payloads are explicitly out of scope for this task.

## Files

- `job_manifest.schema.json`: orchestrator-owned job configuration for a single 16:9 to 9:16 smooth reframe job.
- `artifact_manifest.schema.json`: orchestrator-owned registry of artifacts and the final output that have been successfully produced.
- `service_status.schema.json`: orchestrator-owned pipeline execution state.
- `examples/`: sample JSON files for job creation, mid-pipeline execution, and completion.

## Shared Rules

- `schema_version` is `1.0.0` for every manifest in this package.
- `job_id` uses the form `job_<suffix>` and is embedded into every MinIO object key.
- All timestamps use ISO 8601 UTC strings.
- Orchestrator is the single writer for manifest files and `service_status.json`.
- Each service writes only its own artifact or output object and returns that location to Orchestrator.
- `artifact_manifest.json` records only artifacts that already exist. Pending work stays in `service_status.json`.
- Warnings are structured objects with `code`, `message`, `step`, and `created_at`.
- Errors are plain strings at the top level of `service_status.json`.
- Spatial coordinates in downstream artifacts must use source-video resolution, even when detection runs on proxy media.

## Pipeline Step IDs

These step IDs are canonical and must be used consistently across Orchestrator, services, fixtures, and UI:

1. `validation`
2. `media_metadata`
3. `proxy_frame_sampling`
4. `body_detection`
5. `track_interpolation`
6. `reframe_planning`
7. `easing_smoothing`
8. `render_plan_compiler`
9. `ffmpeg_renderer`

## Artifact Registry Keys

| Key | Object Key Pattern | Produced By | Consumer Examples |
| --- | --- | --- | --- |
| `metadata` | `jobs/{job_id}/artifacts/metadata.json` | `media_metadata` | validation, reframe planning, render plan compiler |
| `proxy` | `jobs/{job_id}/artifacts/proxy.mp4` | `proxy_frame_sampling` | body detection |
| `sampled_frames` | `jobs/{job_id}/artifacts/sampled_frames.json` | `proxy_frame_sampling` | body detection |
| `body_tracks_raw` | `jobs/{job_id}/artifacts/body_tracks_raw.json` | `body_detection` | track interpolation |
| `body_tracks_interpolated` | `jobs/{job_id}/artifacts/body_tracks_interpolated.json` | `track_interpolation` | reframe planning |
| `reframe_plan_raw` | `jobs/{job_id}/artifacts/reframe_plan_raw.json` | `reframe_planning` | easing and smoothing |
| `reframe_plan_smooth` | `jobs/{job_id}/artifacts/reframe_plan_smooth.json` | `easing_smoothing` | render plan compiler |
| `render_plan` | `jobs/{job_id}/artifacts/render_plan.json` | `render_plan_compiler` | ffmpeg renderer |
| `final_9x16` | `jobs/{job_id}/outputs/final_9x16.mp4` | `ffmpeg_renderer` | debug frontend, download flow |

## Manifest Lifecycle

1. Job creation writes `job_manifest.json`, initializes an empty `artifact_manifest.json`, and writes `service_status.json` with every step marked `pending`.
2. Before a step starts, Orchestrator updates `service_status.json` so the overall job is `running` and `current_step` matches the step ID.
3. When a step succeeds, the service writes its output object, Orchestrator appends the output to `artifact_manifest.json`, and then marks the step `success` in `service_status.json`.
4. If a step fails hard, Orchestrator writes a plain-string error to `service_status.json`, marks the failing step `failed`, sets the overall job status to `failed`, and stops the pipeline.
5. Soft fallbacks such as missing body detections should still produce the expected artifact and emit a structured warning instead of failing the job.

## Ownership Boundaries

- Services must not write other services' artifact keys.
- `service_status.json` must not duplicate artifact locations.
- `artifact_manifest.json` must not invent new keys outside the fixed registry without a contract update.
- `job_manifest.json` is the request contract and should stay small; runtime metrics and derived metadata belong in artifacts.

## Example Fixtures

- `examples/job_manifest.sample.json`: representative Phase 1 job request.
- `examples/artifact_manifest.created.sample.json`: initial empty registry.
- `examples/artifact_manifest.running.sample.json`: partial registry after early media steps.
- `examples/artifact_manifest.completed.sample.json`: full registry including the final output.
- `examples/service_status.created.sample.json`: initial pending state.
- `examples/service_status.running.sample.json`: mid-pipeline state while body detection is running.
- `examples/service_status.completed.sample.json`: completed state with one non-fatal warning.

## Exclusions

- No multi-camera roles or speaker diarization fields.
- No Phase 2 timeline contracts.
- No render-command schema beyond the render plan artifact reference.
- No database schema, auth schema, or frontend view-model schema.