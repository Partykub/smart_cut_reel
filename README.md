# smart_cut_reel

Phase 1 focuses on converting one 16:9 source video into a 9:16 vertical output with subject-aware smooth reframing.

## Current Status

- P1-A01 completed: shared contracts for `job_manifest.json`, `artifact_manifest.json`, and `service_status.json` are defined under `contracts/`.
- P1-A02 completed: the Orchestrator now has canonical MinIO path helpers, object-store abstractions, manifest management, and artifact helpers under `orchestrator/`.
- P1-A03 completed: the Orchestrator now exposes Python service logic plus FastAPI endpoints for create job, get status, and run job.
- P1-A04 completed: `run_job` now supports real sequential `/run` orchestration with per-step failure handling when service endpoints are configured, and otherwise falls back to the mock runner for local development.
- P1-C01 through P1-G03 now have baseline implementations for the early pipeline: validation, media metadata, proxy sampling, detector-backed body detection with fallback, track interpolation, reframe planning, and easing/smoothing.
- P1-H01–P1-H03 and P1-B03 have baseline implementations: `services/render_plan_compiler/` emits `render_plan.json`; `services/ffmpeg_renderer/` renders static or segmented smooth crop to `final_9x16.mp4`; the orchestrator exposes `GET /jobs/{job_id}/artifacts/{artifact_key}` and the debug frontend can preview/download via `/api/jobs/[jobId]/output`.

## Source Of Truth

- `Phase 1 Todo - 16x9 to 9x16 Smooth Reframe.md`: main planning doc and task board.
- `contracts/CONTRACTS.md`: shared contract rules, MinIO layout, manifest lifecycle, and artifact registry keys.
- `contracts/*.schema.json`: JSON Schemas for the three Phase 1 manifests.
- `contracts/examples/`: sample manifests for created, running, and completed states.
- `orchestrator/README.md`: implementation notes for the current Orchestrator package.

## Implemented So Far

### Contracts

- Phase 1 manifest schemas are in `contracts/job_manifest.schema.json`, `contracts/artifact_manifest.schema.json`, and `contracts/service_status.schema.json`.
- Artifact registry keys and pipeline step IDs are fixed and should not be renamed ad hoc.
- `artifact_manifest.json` is success-only state. In-progress execution stays in `service_status.json`.

### Orchestrator Package

- `orchestrator/path_resolver.py`: canonical object-key resolution for inputs, manifests, artifacts, outputs, and logs.
- `orchestrator/object_store.py`: filesystem-backed object store for tests and a MinIO-backed implementation for real usage.
- `orchestrator/manifest_manager.py`: schema-validated read/write helpers for manifests and status updates.
- `orchestrator/artifact_helper.py`: higher-level helpers for source uploads, artifact uploads, artifact reads, and artifact listing.
- `orchestrator/service.py`: create-job, get-status, and run-job service layer.
- `orchestrator/api.py`: FastAPI app factory exposing `POST /jobs`, `GET /jobs/{job_id}/status`, and `POST /jobs/{job_id}/run`.
- `orchestrator/pipeline_runner.py`: configurable HTTP pipeline runner for P1-A04 plus the mock fallback runner for local development.

### Downstream Services

- `services/validation/`: validates source input, target output config, and basic media readability.
- `services/media_metadata/`: probes source media with `ffprobe` and writes `metadata.json`.
- `services/proxy_frame_sampling/`: creates `proxy.mp4` and `sampled_frames.json` from source media.
- `services/body_detection/`: runs an OpenCV HOG-based person detector on proxy frames and falls back to centered tracks when detections are missing.
- `services/track_interpolation/`: fills short gaps, applies hold/center fallback, and suppresses large outlier jumps.
- `services/reframe_planning/`: converts interpolated tracks into clamped 9:16 crop keyframes.
- `services/easing_smoothing/`: smooths raw reframe keyframes with easing, dead-zone handling, and bounded motion.
- `services/render_plan_compiler/`: builds `artifacts/render_plan.json` from metadata + `reframe_plan_smooth.json` (supports `compiler_render_mode` `static_crop` or `smooth_crop` in `job_manifest.service_config.render_plan_compiler`).
- `services/ffmpeg_renderer/`: renders `outputs/final_9x16.mp4` via FFmpeg (`static_crop` uses the first keyframe; `smooth_crop` slices segments between keyframes, concatenates, then muxes audio).

## Local Setup

Use a local virtual environment for Python work in this repo.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

To enable the real P1-A04 HTTP runner, configure service URLs before starting the Orchestrator:

```bash
export ORCHESTRATOR_SERVICE_ENDPOINTS='{
	"validation": "http://validation:8000",
	"media_metadata": "http://media-metadata:8000",
	"proxy_frame_sampling": "http://proxy-frame-sampling:8000",
	"body_detection": "http://body-detection:8000",
	"track_interpolation": "http://track-interpolation:8000",
	"reframe_planning": "http://reframe-planning:8000",
	"easing_smoothing": "http://easing-smoothing:8000",
	"render_plan_compiler": "http://render-plan-compiler:8000",
	"ffmpeg_renderer": "http://ffmpeg-renderer:8000"
}'
export ORCHESTRATOR_MINIO_BUCKET='smart-cut'
```

If `ORCHESTRATOR_SERVICE_ENDPOINTS` is not set, the API keeps using `MockPipelineRunner` so local development still works before every downstream service exists.

### Run the full HTTP pipeline locally (real `final_9x16.mp4`)

Requires **ffmpeg** and **ffprobe** on your PATH.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/start_local_stack.sh
```

This starts all nine microservices on `127.0.0.1:8010–8018` and the orchestrator on **`http://127.0.0.1:8000`**, using `SMART_CUT_OBJECT_STORE_ROOT` (default: `.orchestrator-data/` under the repo). Press **Ctrl+C** to stop every process.

Background mode:

```bash
./scripts/start_local_stack.sh --detach
./scripts/stop_local_stack.sh
```

Then start the debug UI (separate terminal):

```bash
cd frontend && cp -n .env.local.example .env.local && npm install && npm run dev
```

Open **http://localhost:3000**, upload a 16:9 clip, run the pipeline, then preview/download when `final_9x16` appears.

To use segmented smooth rendering instead of a single static crop, set `compiler_render_mode` to `"smooth_crop"` under `service_config.render_plan_compiler` in [`contracts/examples/job_manifest.sample.json`](contracts/examples/job_manifest.sample.json) (orchestrator copies this template when creating jobs).

## Validation

Run the current focused test suite with:

```bash
.venv/bin/python -m unittest -v \
	services.validation.tests.test_validation_service \
	services.validation.tests.test_validation_api \
	services.media_metadata.tests.test_media_metadata_service \
	services.media_metadata.tests.test_media_metadata_api \
	services.proxy_frame_sampling.tests.test_proxy_frame_sampling_service \
	services.proxy_frame_sampling.tests.test_proxy_frame_sampling_api \
	services.body_detection.tests.test_body_detection_service \
	services.body_detection.tests.test_body_detection_api \
	services.track_interpolation.tests.test_track_interpolation_service \
	services.track_interpolation.tests.test_track_interpolation_api \
	services.reframe_planning.tests.test_reframe_planning_service \
	services.reframe_planning.tests.test_reframe_planning_api \
	services.easing_smoothing.tests.test_smoothing_service \
	services.easing_smoothing.tests.test_smoothing_api \
	services.render_plan_compiler.tests.test_compiler_service \
	services.render_plan_compiler.tests.test_compiler_api \
	services.ffmpeg_renderer.tests.test_ffmpeg_renderer_service \
	orchestrator.tests.test_path_resolver \
	orchestrator.tests.test_artifact_helpers \
	orchestrator.tests.test_pipeline_runner \
	orchestrator.tests.test_api
```

## What The Team Should Do Next

### Highest Priority

1. Wire `ORCHESTRATOR_SERVICE_ENDPOINTS` for `render_plan_compiler` and `ffmpeg_renderer` when running the full HTTP pipeline (implementations live under `services/render_plan_compiler/` and `services/ffmpeg_renderer/`).
2. Add P1-I01 and P1-I02 fixtures/integration coverage around the full pipeline (mock + real services).

### Orchestrator Team

- Keep all MinIO path construction inside `orchestrator/path_resolver.py`.
- Keep all manifest writes inside `ManifestManager`; do not update manifests inline inside controllers.
- Keep `HttpPipelineRunner` as the production path and retain `MockPipelineRunner` only as a local fallback.
- Preserve the existing step IDs from the contracts when wiring service execution.

### Service Teams

- Read the contracts first before writing any service output.
- Write only each service's own artifact or output object.
- Return deterministic output locations that match the Phase 1 contract.
- Do not invent new artifact keys without updating the shared contracts first.

### Frontend Team

- Use `GET /jobs/{job_id}/status` as the primary source for service state.
- Read artifact links from `artifact_manifest.json` rather than guessing object paths.
- Expect `run_job` to use real service calls only when `ORCHESTRATOR_SERVICE_ENDPOINTS` is configured; otherwise it falls back to the mock runner.

### QA And Integration

- Build fixtures and integration tests against the contract examples in `contracts/examples/`.
- Reuse the current Python tests as the baseline for helper and API behavior.
- Add pipeline-level tests around mock HTTP services first, then extend them to real services as they land.

## Known Limitations

- Real HTTP orchestration depends on `ORCHESTRATOR_SERVICE_ENDPOINTS`; without it, `run_job` still falls back to the mock runner.
- Debug Frontend under `frontend/` supports upload, status, run, and preview/download of `final_9x16.mp4` when that artifact exists (via orchestrator artifact GET).
- Body detection uses OpenCV HOG plus fallback logic — sufficient for Phase 1 baseline, not the final quality bar for hard clips.
- Smooth rendering uses segment concat between keyframes — acceptable MVP; per-frame expressions are not required yet.
- Production deployment (Docker/K8s, shared MinIO, CI) is not fully documented here.

## Recommended Immediate Task Order

1. P1-A04 through P1-H03 and P1-B03 (baseline done)
2. P1-I01 / P1-I02 / P1-I03 (fixtures, integration, e2e video)