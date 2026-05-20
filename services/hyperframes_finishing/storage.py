from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.object_store import StoredObject


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class JobPaths:
    job_id: str
    root: str
    assets: str
    artifacts: str
    output: str
    status_json: str
    request_json: str


@dataclass(frozen=True)
class ProjectPaths:
    project_id: str
    root: str
    assets: str
    revisions: str
    project_json: str


@dataclass(frozen=True)
class RevisionPaths:
    project_id: str
    revision_id: str
    root: str
    workspace: str
    revision_json: str


class HyperframesFilesystemStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).resolve()

    @classmethod
    def from_env(cls) -> "HyperframesFilesystemStore":
        configured = os.getenv("SMART_CUT_HYPERFRAMES_ROOT")
        if configured:
            return cls(Path(configured))

        fallback = os.getenv("SMART_CUT_OBJECT_STORE_ROOT")
        if fallback:
            return cls(Path(fallback) / "hyperframes-finishing")

        return cls(Path(".hyperframes-finishing-data"))

    def create_job(self) -> JobPaths:
        job_id = f"hf_{uuid4().hex[:12]}"
        root = f"jobs/{job_id}"
        return JobPaths(
            job_id=job_id,
            root=root,
            assets=f"{root}/assets",
            artifacts=f"{root}/artifacts",
            output=f"{root}/output",
            status_json=f"{root}/job_status.json",
            request_json=f"{root}/request.json",
        )

    def create_project(self) -> ProjectPaths:
        project_id = f"hfp_{uuid4().hex[:12]}"
        root = f"projects/{project_id}"
        return ProjectPaths(
            project_id=project_id,
            root=root,
            assets=f"{root}/assets",
            revisions=f"{root}/revisions",
            project_json=f"{root}/project.json",
        )

    def project_paths(self, project_id: str) -> ProjectPaths:
        root = f"projects/{project_id}"
        return ProjectPaths(
            project_id=project_id,
            root=root,
            assets=f"{root}/assets",
            revisions=f"{root}/revisions",
            project_json=f"{root}/project.json",
        )

    def create_revision(self, project_id: str) -> RevisionPaths:
        revision_id = f"rev_{uuid4().hex[:12]}"
        return self.revision_paths(project_id, revision_id)

    def revision_paths(self, project_id: str, revision_id: str) -> RevisionPaths:
        root = f"projects/{project_id}/revisions/{revision_id}"
        return RevisionPaths(
            project_id=project_id,
            revision_id=revision_id,
            root=root,
            workspace=f"{root}/workspace",
            revision_json=f"{root}/revision.json",
        )

    def job_paths(self, job_id: str) -> JobPaths:
        root = f"jobs/{job_id}"
        return JobPaths(
            job_id=job_id,
            root=root,
            assets=f"{root}/assets",
            artifacts=f"{root}/artifacts",
            output=f"{root}/output",
            status_json=f"{root}/job_status.json",
            request_json=f"{root}/request.json",
        )

    def write_bytes(self, object_key: str, data: bytes) -> None:
        local_path = self._local_path(object_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)

    def read_bytes(self, object_key: str) -> bytes:
        local_path = self._local_path(object_key)
        if not local_path.exists():
            raise FileNotFoundError(object_key)
        return local_path.read_bytes()

    def write_json(self, object_key: str, payload: dict[str, Any]) -> None:
        import json

        self.write_bytes(object_key, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))

    def read_json(self, object_key: str) -> dict[str, Any]:
        import json

        return json.loads(self.read_bytes(object_key).decode("utf-8"))

    def exists(self, object_key: str) -> bool:
        return self._local_path(object_key).exists()

    def stat(self, object_key: str) -> StoredObject:
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

    def list_project_ids(self) -> list[str]:
        projects_dir = self.root_dir / "projects"
        if not projects_dir.exists():
            return []
        return sorted(path.name for path in projects_dir.iterdir() if path.is_dir())

    def list_job_ids(self) -> list[str]:
        jobs_dir = self.root_dir / "jobs"
        if not jobs_dir.exists():
            return []
        return sorted(path.name for path in jobs_dir.iterdir() if path.is_dir())

    def list_revision_ids(self, project_id: str) -> list[str]:
        revisions_dir = self.root_dir / "projects" / project_id / "revisions"
        if not revisions_dir.exists():
            return []
        return sorted(path.name for path in revisions_dir.iterdir() if path.is_dir())

    def _local_path(self, object_key: str) -> Path:
        return self.root_dir.joinpath(*object_key.split("/"))
