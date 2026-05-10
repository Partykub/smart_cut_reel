"""Schema-aware manifest helpers for orchestrator state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from datetime import timezone
from typing import Any

from .contracts import ARTIFACT_CONTENT_TYPES
from .contracts import ARTIFACT_PRODUCERS
from .contracts import KNOWN_PIPELINE_STEP_IDS
from .contracts import PIPELINE_ID_REFRAME_16X9_TO_9X16
from .contracts import REFRAME_ONLY_STEP_IDS
from .contracts import PIPELINE_STEPS_BY_ID
from .contracts import schema_version_for_pipeline
from .contracts import validate_document
from .object_store import ObjectStore
from .path_resolver import artifact_path
from .path_resolver import manifest_path
from .path_resolver import validate_artifact_key
from .path_resolver import validate_job_id


_UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ManifestManager:
    def __init__(self, store: ObjectStore) -> None:
        self.store = store

    def read_job_manifest(self, job_id: str) -> dict[str, Any]:
        return self._read_manifest(job_id, "job_manifest")

    def read_artifact_manifest(self, job_id: str) -> dict[str, Any]:
        return self._read_manifest(job_id, "artifact_manifest")

    def read_service_status(self, job_id: str) -> dict[str, Any]:
        return self._read_manifest(job_id, "service_status")

    def write_job_manifest(self, job_id: str, document: dict[str, Any]) -> None:
        self._write_manifest(job_id, "job_manifest", document)

    def write_artifact_manifest(self, job_id: str, document: dict[str, Any]) -> None:
        self._write_manifest(job_id, "artifact_manifest", document)

    def write_service_status(self, job_id: str, document: dict[str, Any]) -> None:
        self._write_manifest(job_id, "service_status", document)

    def pipeline_steps(self, job_id: str) -> tuple[str, ...]:
        manifest = self.read_job_manifest(job_id)
        steps = manifest.get("pipeline", {}).get("steps")
        if not isinstance(steps, list) or not steps:
            return REFRAME_ONLY_STEP_IDS
        return tuple(str(step) for step in steps)

    def create_initial_job_state(self, job_manifest: dict[str, Any]) -> None:
        job_id = validate_job_id(job_manifest["job_id"])
        created_at = job_manifest.get("created_at", utc_now())
        pipeline_id = job_manifest.get("pipeline", {}).get(
            "pipeline_id", PIPELINE_ID_REFRAME_16X9_TO_9X16
        )
        if pipeline_id in PIPELINE_STEPS_BY_ID:
            steps = PIPELINE_STEPS_BY_ID[pipeline_id]
        else:
            steps = tuple(job_manifest["pipeline"]["steps"])

        schema_version = schema_version_for_pipeline(pipeline_id)
        self.write_job_manifest(job_id, deepcopy(job_manifest))

        artifact_manifest = {
            "schema_version": schema_version,
            "job_id": job_id,
            "updated_at": created_at,
            "artifacts": {},
        }
        self.write_artifact_manifest(job_id, artifact_manifest)

        service_status = {
            "schema_version": schema_version,
            "job_id": job_id,
            "status": "pending",
            "current_step": None,
            "updated_at": created_at,
            "steps": {
                step_id: {
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                }
                for step_id in steps
            },
            "warnings": [],
            "errors": [],
        }
        self.write_service_status(job_id, service_status)

    def register_artifact(
        self,
        job_id: str,
        artifact_key: str,
        *,
        produced_by: str | None = None,
        created_at: str | None = None,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
    ) -> dict[str, Any]:
        job_id = validate_job_id(job_id)
        artifact_key = validate_artifact_key(artifact_key)
        object_key = artifact_path(job_id, artifact_key)
        stored_object = self.store.stat_object(object_key)

        manifest = self.read_artifact_manifest(job_id)
        timestamp = created_at or utc_now()
        entry = {
            "object_key": object_key,
            "produced_by": produced_by or ARTIFACT_PRODUCERS[artifact_key],
            "created_at": timestamp,
            "content_type": content_type or ARTIFACT_CONTENT_TYPES[artifact_key],
            "size_bytes": stored_object.size_bytes,
        }
        if checksum_sha256 is not None:
            entry["checksum_sha256"] = checksum_sha256

        manifest["artifacts"][artifact_key] = entry
        manifest["updated_at"] = timestamp
        self.write_artifact_manifest(job_id, manifest)
        return entry

    def set_step_state(
        self,
        job_id: str,
        step_id: str,
        *,
        step_status: str,
        started_at: str | object = _UNSET,
        finished_at: str | object = _UNSET,
        overall_status: str | None = None,
        current_step: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        if step_id not in KNOWN_PIPELINE_STEP_IDS:
            allowed = ", ".join(KNOWN_PIPELINE_STEP_IDS)
            raise KeyError(f"Unknown step_id '{step_id}'. Expected one of: {allowed}.")

        status_document = self.read_service_status(job_id)
        if step_id not in status_document["steps"]:
            allowed = ", ".join(sorted(status_document["steps"]))
            raise KeyError(
                f"Step '{step_id}' is not part of this job's pipeline. Job pipeline steps: {allowed}."
            )

        status_document["steps"][step_id]["status"] = step_status
        if started_at is not _UNSET:
            status_document["steps"][step_id]["started_at"] = started_at
        if finished_at is not _UNSET:
            status_document["steps"][step_id]["finished_at"] = finished_at
        if overall_status is not None:
            status_document["status"] = overall_status
        if current_step is not _UNSET:
            status_document["current_step"] = current_step
        status_document["updated_at"] = utc_now()

        self.write_service_status(job_id, status_document)
        return status_document

    def append_warning(
        self,
        job_id: str,
        *,
        code: str,
        message: str,
        step: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if step not in KNOWN_PIPELINE_STEP_IDS:
            allowed = ", ".join(KNOWN_PIPELINE_STEP_IDS)
            raise KeyError(f"Unknown step '{step}'. Expected one of: {allowed}.")

        status_document = self.read_service_status(job_id)
        status_document["warnings"].append(
            {
                "code": code,
                "message": message,
                "step": step,
                "created_at": created_at or utc_now(),
            }
        )
        status_document["updated_at"] = utc_now()
        self.write_service_status(job_id, status_document)
        return status_document

    def append_error(self, job_id: str, message: str) -> dict[str, Any]:
        status_document = self.read_service_status(job_id)
        status_document["errors"].append(message)
        status_document["updated_at"] = utc_now()
        self.write_service_status(job_id, status_document)
        return status_document

    def _read_manifest(self, job_id: str, manifest_name: str) -> dict[str, Any]:
        validate_job_id(job_id)
        return self.store.download_json(manifest_path(job_id, manifest_name))

    def _write_manifest(self, job_id: str, schema_name: str, document: dict[str, Any]) -> None:
        validate_job_id(job_id)
        if document.get("job_id") != job_id:
            raise ValueError(
                f"Document job_id '{document.get('job_id')}' does not match requested job_id '{job_id}'."
            )
        validate_document(document, schema_name)
        self.store.upload_json(manifest_path(job_id, schema_name), document)
