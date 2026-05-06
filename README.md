# smart_cut_reel

Phase 1 focuses on converting one 16:9 source video into a 9:16 vertical output with subject-aware smooth reframing.

## Current Status

- P1-A01 completed: shared contracts for `job_manifest.json`, `artifact_manifest.json`, and `service_status.json` are defined under `contracts/`.
- P1-A02 completed: the Orchestrator now has canonical MinIO path helpers, object-store abstractions, manifest management, and artifact helpers under `orchestrator/`.
- P1-A03 completed: the Orchestrator now exposes Python service logic plus FastAPI endpoints for create job, get status, and run job.
- P1-A04 completed: `run_job` now supports real sequential `/run` orchestration with per-step failure handling when service endpoints are configured, and otherwise falls back to the mock runner for local development.

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

## Validation

Run the current focused test suite with:

```bash
.venv/bin/python -m unittest -v \
	orchestrator.tests.test_path_resolver \
	orchestrator.tests.test_artifact_helpers \
	orchestrator.tests.test_pipeline_runner \
	orchestrator.tests.test_api
```

## What The Team Should Do Next

### Highest Priority

1. Start P1-C01 and P1-C02 so the first real pipeline steps exist behind the Orchestrator runner.
2. Start P1-B01 and P1-B02 so the team can create jobs and inspect status/artifacts from a debug UI.
3. Add P1-I02 integration coverage that runs the pipeline against mock HTTP services end-to-end.

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
- No Debug Frontend yet.
- No Validation, Media Metadata, or downstream AI/reframe services implemented yet.
- No production deployment or environment configuration is documented yet.

## Recommended Immediate Task Order

1. P1-A04
2. P1-C01
3. P1-C02
4. P1-B01
5. P1-B02