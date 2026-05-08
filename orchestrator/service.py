"""Core orchestration service for job creation, status lookup, and pipeline execution."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from typing import Any
from uuid import uuid4

from .artifact_helper import ArtifactHelper
from .contracts import repo_root
from .manifest_manager import ManifestManager
from .manifest_manager import utc_now
from .object_store import ObjectStore
from .contracts import ARTIFACT_CONTENT_TYPES
from .path_resolver import artifact_path
from .path_resolver import input_path
from .path_resolver import job_prefix
from .path_resolver import manifest_path
from .path_resolver import output_path
from .path_resolver import validate_artifact_key
from .path_resolver import validate_job_id
from .pipeline_runner import HttpPipelineRunner
from .pipeline_runner import MockPipelineRunner
from .pipeline_runner import PipelineRunner
from .pipeline_runner import artifact_keys_for_step


class OrchestratorService:
    def __init__(
        self,
        store: ObjectStore,
        *,
        runner: PipelineRunner | None = None,
        job_manifest_template: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.manifest_manager = ManifestManager(store)
        self.artifact_helper = ArtifactHelper(store, self.manifest_manager)
        self.runner = runner or _build_default_runner()
        self.job_manifest_template = job_manifest_template or _load_job_manifest_template()

    def create_job(
        self,
        *,
        source_bytes: bytes,
        original_filename: str,
        content_type: str = "video/mp4",
        created_by: str = "debug_frontend",
        job_id: str | None = None,
    ) -> dict[str, Any]:
        if not source_bytes:
            raise ValueError("source_bytes must not be empty.")

        created_at = utc_now()
        resolved_job_id = validate_job_id(job_id or f"job_{uuid4().hex[:12]}")
        resolved_filename = original_filename or "source.mp4"

        job_manifest = self._build_job_manifest(
            job_id=resolved_job_id,
            created_at=created_at,
            created_by=created_by,
            original_filename=resolved_filename,
            content_type=content_type,
            checksum_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )

        self.artifact_helper.upload_source_video(
            resolved_job_id,
            source_bytes,
            content_type=content_type,
        )
        self.manifest_manager.create_initial_job_state(job_manifest)
        return self.get_job_status(resolved_job_id)

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        resolved_job_id = validate_job_id(job_id)
        self._reconcile_completed_final_render(resolved_job_id)
        service_status = self.manifest_manager.read_service_status(resolved_job_id)
        artifact_manifest = self.manifest_manager.read_artifact_manifest(resolved_job_id)
        return {
            "job_id": resolved_job_id,
            "service_status": service_status,
            "artifacts": artifact_manifest["artifacts"],
            "paths": {
                "job_prefix": job_prefix(resolved_job_id),
                "input": input_path(resolved_job_id),
                "job_manifest": manifest_path(resolved_job_id, "job_manifest"),
                "artifact_manifest": manifest_path(resolved_job_id, "artifact_manifest"),
                "service_status": manifest_path(resolved_job_id, "service_status"),
                "output": output_path(resolved_job_id),
            },
        }

    def _reconcile_completed_final_render(self, job_id: str) -> None:
        service_status = self.manifest_manager.read_service_status(job_id)
        if service_status.get("status") != "running":
            return
        if service_status.get("current_step") != "ffmpeg_renderer":
            return

        final_step = service_status["steps"].get("ffmpeg_renderer", {})
        if final_step.get("status") != "running":
            return

        expected_artifacts = artifact_keys_for_step("ffmpeg_renderer")
        if not all(self.store.exists(artifact_path(job_id, artifact_key)) for artifact_key in expected_artifacts):
            return

        artifact_manifest = self.manifest_manager.read_artifact_manifest(job_id)
        for artifact_key in expected_artifacts:
            if artifact_key not in artifact_manifest.get("artifacts", {}):
                self.manifest_manager.register_artifact(job_id, artifact_key, produced_by="ffmpeg_renderer")

        self.manifest_manager.set_step_state(
            job_id,
            "ffmpeg_renderer",
            step_status="success",
            finished_at=utc_now(),
            overall_status="success",
            current_step=None,
        )

    def read_artifact_bytes(self, job_id: str, artifact_key: str) -> tuple[bytes, str]:
        """Return artifact bytes and Content-Type for a registered artifact."""
        resolved_job_id = validate_job_id(job_id)
        artifact_key = validate_artifact_key(artifact_key)
        manifest = self.manifest_manager.read_artifact_manifest(resolved_job_id)
        artifacts = manifest.get("artifacts", {})
        meta = artifacts.get(artifact_key)
        if not isinstance(meta, dict):
            raise FileNotFoundError(f"Artifact '{artifact_key}' is not registered for job '{resolved_job_id}'.")
        object_key = meta.get("object_key")
        if not isinstance(object_key, str):
            raise FileNotFoundError(f"Artifact '{artifact_key}' has no object_key.")
        if not self.store.exists(object_key):
            raise FileNotFoundError(f"Object '{object_key}' does not exist in storage.")
        content_type = ARTIFACT_CONTENT_TYPES.get(artifact_key, "application/octet-stream")
        return self.store.download_bytes(object_key), content_type

    def run_job(self, job_id: str) -> dict[str, Any]:
        resolved_job_id = validate_job_id(job_id)
        self.manifest_manager.read_job_manifest(resolved_job_id)
        self.runner.run(
            job_id=resolved_job_id,
            manifest_manager=self.manifest_manager,
            artifact_helper=self.artifact_helper,
        )
        return self.get_job_status(resolved_job_id)

    def _build_job_manifest(
        self,
        *,
        job_id: str,
        created_at: str,
        created_by: str,
        original_filename: str,
        content_type: str,
        checksum_sha256: str,
    ) -> dict[str, Any]:
        manifest = deepcopy(self.job_manifest_template)
        manifest["job_id"] = job_id
        manifest["created_at"] = created_at
        manifest["created_by"] = created_by
        manifest["input"]["source_video"]["object_key"] = input_path(job_id)
        manifest["input"]["source_video"]["original_filename"] = original_filename
        manifest["input"]["source_video"]["uploaded_at"] = created_at
        manifest["input"]["source_video"]["content_type"] = content_type
        manifest["input"]["source_video"]["checksum_sha256"] = checksum_sha256
        manifest["target_output"]["object_key"] = output_path(job_id)
        return manifest


def _load_job_manifest_template() -> dict[str, Any]:
    template_path = repo_root() / "contracts" / "examples" / "job_manifest.sample.json"
    return json.loads(template_path.read_text(encoding="utf-8"))


def _build_default_runner() -> PipelineRunner:
    raw_service_endpoints = os.getenv("ORCHESTRATOR_SERVICE_ENDPOINTS")
    if not raw_service_endpoints:
        return MockPipelineRunner()

    raw_request_timeout_seconds = os.getenv("ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS")
    request_timeout_seconds: float | None
    if raw_request_timeout_seconds is None or raw_request_timeout_seconds.strip() in {"", "0", "none", "None"}:
        request_timeout_seconds = None
    else:
        try:
            request_timeout_seconds = float(raw_request_timeout_seconds)
        except ValueError as exc:
            raise RuntimeError(
                "ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS must be a number, or 0/none to disable the timeout."
            ) from exc
        if request_timeout_seconds <= 0:
            raise RuntimeError(
                "ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS must be a positive number, or 0/none to disable the timeout."
            )

    try:
        service_endpoints = json.loads(raw_service_endpoints)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "ORCHESTRATOR_SERVICE_ENDPOINTS must be a JSON object mapping step IDs to service URLs."
        ) from exc

    if not isinstance(service_endpoints, dict) or not all(
        isinstance(step_id, str) and isinstance(endpoint, str)
        for step_id, endpoint in service_endpoints.items()
    ):
        raise RuntimeError(
            "ORCHESTRATOR_SERVICE_ENDPOINTS must be a JSON object mapping step IDs to service URLs."
        )

    return HttpPipelineRunner(
        service_endpoints=service_endpoints,
        minio_bucket=os.getenv("ORCHESTRATOR_MINIO_BUCKET", "smart-cut"),
        request_timeout_seconds=request_timeout_seconds,
    )
