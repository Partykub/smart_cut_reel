# Orchestrator Helpers

This package currently implements P1-A02 and P1-A03 foundations for Phase 1.

## Entry Points

- `orchestrator.path_resolver`: canonical Phase 1 MinIO object key resolution.
- `orchestrator.object_store`: object-store abstraction with filesystem and MinIO backends.
- `orchestrator.manifest_manager`: schema-aware read/write helpers for `job_manifest.json`, `artifact_manifest.json`, and `service_status.json`.
- `orchestrator.artifact_helper`: higher-level helper for source uploads, artifact uploads, artifact reads, and artifact listing.
- `orchestrator.service`: core create-job, get-status, and run-job service flow.
- `orchestrator.pipeline_runner`: runner abstraction plus temporary mock runner used until P1-A04.
- `orchestrator.api`: FastAPI app factory exposing `/jobs`, `/jobs/{job_id}/status`, and `/jobs/{job_id}/run`.

## Integration Rule

P1-A03 uses these helpers instead of constructing MinIO paths or mutating manifests inline.

Until P1-A04 lands, `run_job` uses a mock pipeline runner that exercises status transitions without calling real downstream services.