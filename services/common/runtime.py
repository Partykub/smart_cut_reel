"""Runtime helpers shared by Phase 1 downstream services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
import os
from pathlib import Path
from typing import Any
from typing import Literal

from orchestrator.object_store import FilesystemObjectStore
from orchestrator.object_store import MinIOObjectStore
from orchestrator.object_store import ObjectStore


@dataclass(slots=True)
class RunMinIO:
    bucket: str
    prefix: str


@dataclass(slots=True)
class RunRequest:
    job_id: str
    step_id: str
    minio: RunMinIO
    inputs: dict[str, str]
    expected_outputs: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ServiceWarning:
    code: str
    message: str
    step: str | None = None
    created_at: str | None = None


@dataclass(slots=True)
class RunResponse:
    service_id: str
    status: Literal["success"] = "success"
    outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[ServiceWarning] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class ServiceContext:
    def __init__(
        self,
        request: RunRequest,
        store: ObjectStore,
        heartbeat_fn: Callable[[], None] | None = None,
    ) -> None:
        self.request = request
        self.store = store
        self._heartbeat_fn = heartbeat_fn

    def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        """Touch service_status.updated_at so the UI knows the service is alive.

        Pass optional *progress* to surface current/total seconds to the UI.
        """
        if self._heartbeat_fn is not None:
            try:
                self._heartbeat_fn(progress)
            except Exception:  # noqa: BLE001 - heartbeat must never crash a service
                pass

    @property
    def job_id(self) -> str:
        return self.request.job_id

    def input_key(self, name: str) -> str:
        try:
            return self.request.inputs[name]
        except KeyError as exc:
            raise ValueError(f"request is missing input '{name}'") from exc

    def expected_output_key(self, name: str) -> str:
        try:
            return self.request.expected_outputs[name]
        except KeyError as exc:
            raise ValueError(f"request is missing expected output '{name}'") from exc

    def read_bytes(self, object_key: str) -> bytes:
        return self.store.download_bytes(object_key)

    def read_json(self, object_key: str) -> dict[str, Any]:
        return self.store.download_json(object_key)

    def write_json(self, object_key: str, payload: dict[str, Any]) -> None:
        self.store.upload_json(object_key, payload)

    def write_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        self.store.upload_bytes(object_key, data, content_type=content_type)

    def exists(self, object_key: str) -> bool:
        return self.store.exists(object_key)


def build_object_store(bucket: str) -> ObjectStore:
    root_dir = os.getenv("SMART_CUT_OBJECT_STORE_ROOT")
    if root_dir:
        return FilesystemObjectStore(Path(root_dir))

    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    if endpoint and access_key and secret_key:
        return MinIOObjectStore(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket=bucket,
            secure=_bool_env("MINIO_SECURE"),
        )

    raise RuntimeError(
        "Set SMART_CUT_OBJECT_STORE_ROOT for local filesystem storage or MINIO_* env vars for MinIO."
    )


def build_context(request: RunRequest, store: ObjectStore | None = None) -> ServiceContext:
    from orchestrator.manifest_manager import ManifestManager

    object_store = store or build_object_store(request.minio.bucket)
    manager = ManifestManager(object_store)

    def _heartbeat(progress: dict[str, Any] | None = None) -> None:
        manager.touch_service_status(request.job_id, progress=progress)

    return ServiceContext(request=request, store=object_store, heartbeat_fn=_heartbeat)


def _bool_env(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}
