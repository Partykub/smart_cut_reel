"""High-level artifact and input helpers for the Orchestrator."""

from __future__ import annotations

import json
from typing import Any

from .contracts import ARTIFACT_CONTENT_TYPES
from .manifest_manager import ManifestManager
from .manifest_manager import utc_now
from .object_store import ObjectStore
from .path_resolver import artifact_path
from .path_resolver import input_path
from .path_resolver import job_prefix
from .path_resolver import validate_artifact_key
from .path_resolver import validate_job_id


class ArtifactHelper:
    def __init__(self, store: ObjectStore, manifest_manager: ManifestManager | None = None) -> None:
        self.store = store
        self.manifest_manager = manifest_manager or ManifestManager(store)

    def upload_source_video(
        self,
        job_id: str,
        data: bytes,
        *,
        content_type: str = "video/mp4",
    ) -> str:
        object_key = input_path(validate_job_id(job_id))
        self.store.upload_bytes(object_key, data, content_type=content_type)
        return object_key

    def upload_artifact(
        self,
        job_id: str,
        artifact_key: str,
        data: bytes,
        *,
        produced_by: str | None = None,
        content_type: str | None = None,
        checksum_sha256: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        artifact_key = validate_artifact_key(artifact_key)
        object_key = artifact_path(validate_job_id(job_id), artifact_key)
        self.store.upload_bytes(
            object_key,
            data,
            content_type=content_type or ARTIFACT_CONTENT_TYPES[artifact_key],
        )
        return self.manifest_manager.register_artifact(
            job_id,
            artifact_key,
            produced_by=produced_by,
            created_at=created_at or utc_now(),
            content_type=content_type,
            checksum_sha256=checksum_sha256,
        )

    def upload_json_artifact(
        self,
        job_id: str,
        artifact_key: str,
        payload: dict[str, Any],
        *,
        produced_by: str | None = None,
        checksum_sha256: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        return self.upload_artifact(
            job_id,
            artifact_key,
            serialized,
            produced_by=produced_by,
            content_type="application/json",
            checksum_sha256=checksum_sha256,
            created_at=created_at,
        )

    def read_artifact(self, job_id: str, artifact_key: str, *, deserialize_json: bool = False) -> Any:
        object_key = artifact_path(validate_job_id(job_id), validate_artifact_key(artifact_key))
        data = self.store.download_bytes(object_key)
        if deserialize_json:
            return json.loads(data.decode("utf-8"))
        return data

    def artifact_exists(self, job_id: str, artifact_key: str) -> bool:
        object_key = artifact_path(validate_job_id(job_id), validate_artifact_key(artifact_key))
        return self.store.exists(object_key)

    def list_artifacts(self, job_id: str) -> dict[str, Any]:
        return self.manifest_manager.read_artifact_manifest(validate_job_id(job_id))["artifacts"]

    def list_job_objects(self, job_id: str) -> list[str]:
        return [stored.object_key for stored in self.store.list_objects(job_prefix(validate_job_id(job_id)))]