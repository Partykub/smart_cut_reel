"""Object-store abstraction for Phase 1 orchestrator helpers."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
import io
import json
from pathlib import Path
from typing import Any
from typing import Mapping


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    size_bytes: int


class ObjectStore(ABC):
    @abstractmethod
    def upload_bytes(self, object_key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def download_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def stat_object(self, object_key: str) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    def list_objects(self, prefix: str) -> list[StoredObject]:
        raise NotImplementedError

    def exists(self, object_key: str) -> bool:
        try:
            self.stat_object(object_key)
        except FileNotFoundError:
            return False
        return True

    def upload_json(self, object_key: str, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.upload_bytes(object_key, serialized, content_type="application/json")

    def download_json(self, object_key: str) -> dict[str, Any]:
        return json.loads(self.download_bytes(object_key).decode("utf-8"))


class FilesystemObjectStore(ObjectStore):
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    def upload_bytes(self, object_key: str, data: bytes, content_type: str) -> None:
        del content_type
        local_path = self._local_path(object_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)

    def download_bytes(self, object_key: str) -> bytes:
        local_path = self._local_path(object_key)
        if not local_path.exists():
            raise FileNotFoundError(object_key)
        return local_path.read_bytes()

    def stat_object(self, object_key: str) -> StoredObject:
        local_path = self._local_path(object_key)
        if not local_path.exists():
            raise FileNotFoundError(object_key)
        return StoredObject(object_key=object_key, size_bytes=local_path.stat().st_size)

    def list_objects(self, prefix: str) -> list[StoredObject]:
        local_prefix = self._local_path(prefix)
        if not local_prefix.exists():
            return []

        objects: list[StoredObject] = []
        for local_path in sorted(path for path in local_prefix.rglob("*") if path.is_file()):
            relative_key = str(local_path.relative_to(self.root_dir)).replace("\\", "/")
            objects.append(StoredObject(object_key=relative_key, size_bytes=local_path.stat().st_size))
        return objects

    def _local_path(self, object_key: str) -> Path:
        return self.root_dir.joinpath(*object_key.split("/"))


class MinIOObjectStore(ObjectStore):
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError(
                "The 'minio' package is required to use MinIOObjectStore."
            ) from exc

        self.bucket = bucket
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def upload_bytes(self, object_key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            self.bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def download_bytes(self, object_key: str) -> bytes:
        response = self._client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def stat_object(self, object_key: str) -> StoredObject:
        try:
            stat = self._client.stat_object(self.bucket, object_key)
        except Exception as exc:
            if exc.__class__.__name__ == "S3Error" and getattr(exc, "code", None) in {
                "NoSuchKey",
                "NoSuchObject",
            }:
                raise FileNotFoundError(object_key) from exc
            raise
        return StoredObject(object_key=object_key, size_bytes=stat.size)

    def list_objects(self, prefix: str) -> list[StoredObject]:
        objects = self._client.list_objects(self.bucket, prefix=prefix, recursive=True)
        return [
            StoredObject(object_key=stored.object_name, size_bytes=stored.size)
            for stored in objects
        ]