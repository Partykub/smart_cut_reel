# Orchestrator Helpers

This package currently implements the P1-A02, P1-A03, and P1-A04 Orchestrator foundations for Phase 1.

## Entry Points

- `orchestrator.path_resolver`: canonical Phase 1 MinIO object key resolution.
- `orchestrator.object_store`: object-store abstraction with filesystem and MinIO backends.
- `orchestrator.manifest_manager`: schema-aware read/write helpers for `job_manifest.json`, `artifact_manifest.json`, and `service_status.json`.
- `orchestrator.artifact_helper`: higher-level helper for source uploads, artifact uploads, artifact reads, and artifact listing.
- `orchestrator.service`: core create-job, get-status, and run-job service flow.
- `orchestrator.pipeline_runner`: runner abstraction, configurable HTTP `/run` orchestration for P1-A04, and the mock fallback runner.
- `orchestrator.api`: FastAPI app factory exposing `/jobs`, `/jobs/{job_id}/status`, and `/jobs/{job_id}/run`.

## Integration Rule

P1-A03 uses these helpers instead of constructing MinIO paths or mutating manifests inline.

When `ORCHESTRATOR_SERVICE_ENDPOINTS` is set, `run_job` uses `HttpPipelineRunner` to call each service's `/run` endpoint in pipeline order, register the returned artifacts, persist warnings, and stop the job on hard failure.

Without that environment variable, `run_job` still falls back to `MockPipelineRunner` so the local API remains usable before every downstream service exists.