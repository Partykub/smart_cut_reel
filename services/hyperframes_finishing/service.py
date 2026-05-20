from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
import shutil
from typing import BinaryIO

from services.hyperframes_finishing.models import ArtifactEntry
from services.hyperframes_finishing.models import CompositionConfig
from services.hyperframes_finishing.models import DetectedOrientation
from services.hyperframes_finishing.models import JobCreateResponse
from services.hyperframes_finishing.models import JobStatusResponse
from services.hyperframes_finishing.models import NormalizedAssets
from services.hyperframes_finishing.models import NormalizedRenderSpec
from services.hyperframes_finishing.models import parse_subtitle_document
from services.hyperframes_finishing.models import ProjectDetailResponse
from services.hyperframes_finishing.models import ProjectRecord
from services.hyperframes_finishing.models import ProjectSummaryResponse
from services.hyperframes_finishing.models import RenderJobRecord
from services.hyperframes_finishing.models import RenderJobSummaryResponse
from services.hyperframes_finishing.models import RevisionRecord
from services.hyperframes_finishing.models import RevisionSummaryResponse
from services.hyperframes_finishing.models import TemplateFamily
from services.hyperframes_finishing.rendering import HyperframesCliRenderExecutor
from services.hyperframes_finishing.rendering import MockHyperframesRenderExecutor
from services.hyperframes_finishing.rendering import RenderExecutor
from services.hyperframes_finishing.storage import HyperframesFilesystemStore
from services.hyperframes_finishing.storage import JobPaths
from services.hyperframes_finishing.storage import ProjectPaths
from services.hyperframes_finishing.storage import RevisionPaths
from services.hyperframes_finishing.storage import utc_now
from services.hyperframes_finishing.template_router import detect_orientation
from services.hyperframes_finishing.template_router import resolve_template_family


@dataclass(frozen=True)
class UploadedAsset:
    filename: str
    content: bytes
    content_type: str


@dataclass(frozen=True)
class CreateJobInput:
    source_video: UploadedAsset
    template_family: TemplateFamily = "auto"
    template_variant: str = "default"
    brand_theme: str = "default"
    subtitle_theme: str = "glassmorphism"
    created_by: str | None = None
    intro_video: UploadedAsset | None = None
    outro_video: UploadedAsset | None = None
    logo_image: UploadedAsset | None = None
    subtitle_file: UploadedAsset | None = None
    project_id: str | None = None
    revision_id: str | None = None
    render_mode: str = "draft"


@dataclass(frozen=True)
class CreateProjectInput:
    project_name: str
    source_video: UploadedAsset
    template_family: TemplateFamily = "auto"
    template_variant: str = "default"
    brand_theme: str = "default"
    subtitle_theme: str = "glassmorphism"
    created_by: str | None = None
    intro_video: UploadedAsset | None = None
    outro_video: UploadedAsset | None = None
    logo_image: UploadedAsset | None = None
    subtitle_file: UploadedAsset | None = None


class HyperframesFinishingService:
    def __init__(
        self,
        *,
        store: HyperframesFilesystemStore | None = None,
        renderer: RenderExecutor | None = None,
    ) -> None:
        self.store = store or HyperframesFilesystemStore.from_env()
        if renderer is not None:
            self.renderer = renderer
        elif os.getenv("SMART_CUT_HYPERFRAMES_RENDERER", "cli").lower() == "mock":
            self.renderer = MockHyperframesRenderExecutor()
        else:
            self.renderer = HyperframesCliRenderExecutor()

    def create_job(self, payload: CreateJobInput) -> JobCreateResponse:
        paths = self.store.create_job()
        if payload.subtitle_file is not None:
            parse_subtitle_document(payload.subtitle_file.filename, payload.subtitle_file.content)
        detected, _width, _height, _rotation = detect_orientation(
            payload.source_video.content,
            suffix=_file_suffix(payload.source_video.filename),
        )
        resolved_family = resolve_template_family(requested=payload.template_family, detected=detected)
        created_at = utc_now()

        assets = self._persist_assets(paths, payload)
        request_payload = {
            "job_id": paths.job_id,
            "project_id": payload.project_id,
            "revision_id": payload.revision_id,
            "render_mode": payload.render_mode,
            "template_family": resolved_family,
            "template_variant": payload.template_variant,
            "orientation_detected": detected,
            "brand_theme": payload.brand_theme,
            "subtitle_theme": payload.subtitle_theme,
            "created_by": payload.created_by,
            "assets": assets,
        }
        self.store.write_json(paths.request_json, request_payload)

        record = RenderJobRecord(
            job_id=paths.job_id,
            project_id=payload.project_id,
            revision_id=payload.revision_id,
            render_mode=payload.render_mode,
            status="queued",
            created_at=created_at,
            updated_at=created_at,
            template_family=resolved_family,
            template_variant=payload.template_variant,
            orientation_detected=detected,
            progress_percent=0,
            created_by=payload.created_by,
        )
        self._write_record(paths, record)
        return JobCreateResponse(
            job_id=record.job_id,
            project_id=record.project_id,
            revision_id=record.revision_id,
            render_mode=record.render_mode,
            status=record.status,
            template_family=record.template_family,
            orientation_detected=record.orientation_detected,
            progress_percent=record.progress_percent,
        )

    def create_project(self, payload: CreateProjectInput) -> ProjectDetailResponse:
        project_paths = self.store.create_project()
        revision_paths = self.store.create_revision(project_paths.project_id)
        if payload.subtitle_file is not None:
            parse_subtitle_document(payload.subtitle_file.filename, payload.subtitle_file.content)
        detected, _width, _height, _rotation = detect_orientation(
            payload.source_video.content,
            suffix=_file_suffix(payload.source_video.filename),
        )
        resolved_family = resolve_template_family(requested=payload.template_family, detected=detected)
        created_at = utc_now()
        assets = NormalizedAssets.model_validate(
            self._persist_project_assets(project_paths, payload)
        )

        revision = RevisionRecord(
            revision_id=revision_paths.revision_id,
            project_id=project_paths.project_id,
            revision_name="Initial Draft",
            revision_type="draft",
            template_family=resolved_family,
            template_variant=payload.template_variant,
            orientation_detected=detected,
            workspace_root=revision_paths.workspace,
            created_at=created_at,
            updated_at=created_at,
            created_by=payload.created_by,
        )
        self._scaffold_revision_workspace(
            revision_paths=revision_paths,
            project_name=payload.project_name,
            revision=revision,
            assets=assets,
            brand_theme=payload.brand_theme,
            subtitle_theme=payload.subtitle_theme,
        )
        self.store.write_json(revision_paths.revision_json, revision.model_dump(mode="json"))

        project = ProjectRecord(
            project_id=project_paths.project_id,
            name=payload.project_name.strip(),
            created_at=created_at,
            updated_at=created_at,
            template_family=resolved_family,
            template_variant=payload.template_variant,
            orientation_detected=detected,
            brand_theme=payload.brand_theme,
            subtitle_theme=payload.subtitle_theme,
            created_by=payload.created_by,
            active_revision_id=revision.revision_id,
            assets=assets,
        )
        self.store.write_json(project_paths.project_json, project.model_dump(mode="json"))
        return self.get_project(project.project_id)

    def list_projects(self) -> list[ProjectSummaryResponse]:
        projects: list[ProjectSummaryResponse] = []
        for project_id in self.store.list_project_ids():
            project_paths = self.store.project_paths(project_id)
            if not self.store.exists(project_paths.project_json):
                continue
            project = ProjectRecord.model_validate(self.store.read_json(project_paths.project_json))
            projects.append(self._project_summary(project))
        return projects

    def get_project(self, project_id: str) -> ProjectDetailResponse:
        project_paths = self.store.project_paths(project_id)
        if not self.store.exists(project_paths.project_json):
            raise FileNotFoundError(f"project '{project_id}' was not found")
        project = ProjectRecord.model_validate(self.store.read_json(project_paths.project_json))
        revisions = self.list_revisions(project_id)
        return ProjectDetailResponse(
            **self._project_summary(project).model_dump(),
            created_by=project.created_by,
            assets=project.assets,
            revisions=revisions,
            render_jobs=self.list_render_jobs(project_id),
        )

    def list_revisions(self, project_id: str) -> list[RevisionSummaryResponse]:
        project_paths = self.store.project_paths(project_id)
        if not self.store.exists(project_paths.project_json):
            raise FileNotFoundError(f"project '{project_id}' was not found")
        revisions: list[RevisionSummaryResponse] = []
        for revision_id in self.store.list_revision_ids(project_id):
            revision_paths = self.store.revision_paths(project_id, revision_id)
            if not self.store.exists(revision_paths.revision_json):
                continue
            revision = RevisionRecord.model_validate(self.store.read_json(revision_paths.revision_json))
            revisions.append(RevisionSummaryResponse.model_validate(revision.model_dump()))
        revisions.sort(key=lambda item: item.created_at)
        return revisions

    def list_render_jobs(self, project_id: str) -> list[RenderJobSummaryResponse]:
        project_paths = self.store.project_paths(project_id)
        if not self.store.exists(project_paths.project_json):
            raise FileNotFoundError(f"project '{project_id}' was not found")

        jobs: list[RenderJobSummaryResponse] = []
        for job_id in self.store.list_job_ids():
            status_json = self.store.job_paths(job_id).status_json
            if not self.store.exists(status_json):
                continue
            record = RenderJobRecord.model_validate(self.store.read_json(status_json))
            if record.project_id != project_id:
                continue
            jobs.append(self._job_summary(record))

        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs

    def create_draft_render(self, project_id: str, revision_id: str | None = None) -> JobCreateResponse:
        project = self._read_project(project_id)
        target_revision_id = revision_id or project.active_revision_id
        revision = self._read_revision(project_id, target_revision_id)

        return self.create_job(
            CreateJobInput(
                source_video=self._load_project_asset(project.assets.source_video),
                template_family=revision.template_family,
                template_variant=revision.template_variant,
                brand_theme=project.brand_theme,
                subtitle_theme=project.subtitle_theme,
                created_by=project.created_by,
                intro_video=self._load_optional_project_asset(project.assets.intro_video),
                outro_video=self._load_optional_project_asset(project.assets.outro_video),
                logo_image=self._load_optional_project_asset(project.assets.logo_image),
                subtitle_file=self._load_optional_project_asset(project.assets.subtitle_file),
                project_id=project.project_id,
                revision_id=revision.revision_id,
                render_mode="draft",
            )
        )

    def get_job_status(self, job_id: str) -> JobStatusResponse:
        record = self._read_record(self.store.job_paths(job_id))
        return JobStatusResponse.model_validate(record.model_dump())

    def run_job(self, job_id: str) -> JobStatusResponse:
        paths = self.store.job_paths(job_id)
        record = self._read_record(paths)
        if record.status == "completed":
            return JobStatusResponse.model_validate(record.model_dump())

        request_payload = self.store.read_json(paths.request_json)
        spec = self._build_spec(paths, record, request_payload)

        record.status = "rendering"
        record.progress_percent = 5
        record.updated_at = utc_now()
        spec_key = f"{paths.artifacts}/normalized_render_spec.json"
        self.store.write_json(spec_key, spec.model_dump(mode="json"))
        record.artifacts["normalized_render_spec"] = self._artifact_entry(
            artifact_key="normalized_render_spec",
            object_key=spec_key,
            content_type="application/json",
        )
        self._write_record(paths, record)

        try:
            result = self.renderer.render(spec=spec, store=self.store, paths=paths)
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            record.updated_at = utc_now()
            record.error_code = "render_failed"
            record.error_message = str(exc)
            self._write_record(paths, record)
            return JobStatusResponse.model_validate(record.model_dump())

        record.status = "completed"
        record.progress_percent = 100
        record.updated_at = utc_now()
        record.output_url = f"/api/hyperframes/jobs/{job_id}/output"
        record.artifacts["output_video"] = self._artifact_entry(
            artifact_key="output_video",
            object_key=result.output_key,
            content_type="video/mp4",
        )
        for artifact_key, object_key in result.artifact_keys.items():
            record.artifacts[artifact_key] = self._artifact_entry(
                artifact_key=artifact_key,
                object_key=object_key,
                content_type="application/json",
            )
        self._write_record(paths, record)
        return JobStatusResponse.model_validate(record.model_dump())

    def read_output(self, job_id: str) -> bytes:
        paths = self.store.job_paths(job_id)
        record = self._read_record(paths)
        try:
            output_entry = record.artifacts["output_video"]
        except KeyError as exc:
            raise FileNotFoundError("output video is not available yet") from exc
        return self.store.read_bytes(output_entry.object_key)

    def read_artifact(self, job_id: str, artifact_key: str) -> tuple[bytes, str]:
        paths = self.store.job_paths(job_id)
        record = self._read_record(paths)
        try:
            entry = record.artifacts[artifact_key]
        except KeyError as exc:
            raise FileNotFoundError(f"artifact '{artifact_key}' was not found") from exc
        return self.store.read_bytes(entry.object_key), entry.content_type

    def list_queued_job_ids(self) -> list[str]:
        jobs_dir = self.store.root_dir / "jobs"
        if not jobs_dir.exists():
            return []
        queued: list[str] = []
        for job_dir in sorted(path for path in jobs_dir.iterdir() if path.is_dir()):
            status_path = job_dir / "job_status.json"
            if not status_path.exists():
                continue
            record = RenderJobRecord.model_validate_json(status_path.read_text())
            if record.status == "queued":
                queued.append(record.job_id)
        return queued

    def _persist_assets(self, paths: JobPaths, payload: CreateJobInput) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        out["source_video"] = self._save_asset(paths, "source_video", payload.source_video)
        out["intro_video"] = self._save_optional_asset(paths, "intro_video", payload.intro_video)
        out["outro_video"] = self._save_optional_asset(paths, "outro_video", payload.outro_video)
        out["logo_image"] = self._save_optional_asset(paths, "logo_image", payload.logo_image)
        out["subtitle_file"] = self._save_optional_asset(paths, "subtitle_file", payload.subtitle_file)
        return out

    def _persist_project_assets(
        self,
        paths: ProjectPaths,
        payload: CreateProjectInput,
    ) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        out["source_video"] = self._save_project_asset(paths, "source_video", payload.source_video)
        out["intro_video"] = self._save_optional_project_asset(paths, "intro_video", payload.intro_video)
        out["outro_video"] = self._save_optional_project_asset(paths, "outro_video", payload.outro_video)
        out["logo_image"] = self._save_optional_project_asset(paths, "logo_image", payload.logo_image)
        out["subtitle_file"] = self._save_optional_project_asset(paths, "subtitle_file", payload.subtitle_file)
        return out

    def _save_optional_asset(self, paths: JobPaths, slot: str, asset: UploadedAsset | None) -> str | None:
        if asset is None:
            return None
        return self._save_asset(paths, slot, asset)

    def _save_optional_project_asset(
        self,
        paths: ProjectPaths,
        slot: str,
        asset: UploadedAsset | None,
    ) -> str | None:
        if asset is None:
            return None
        return self._save_project_asset(paths, slot, asset)

    def _save_asset(self, paths: JobPaths, slot: str, asset: UploadedAsset) -> str:
        object_key = f"{paths.assets}/{slot}{_file_suffix(asset.filename)}"
        self.store.write_bytes(object_key, asset.content)
        return object_key

    def _save_project_asset(self, paths: ProjectPaths, slot: str, asset: UploadedAsset) -> str:
        object_key = f"{paths.assets}/{slot}{_file_suffix(asset.filename)}"
        self.store.write_bytes(object_key, asset.content)
        return object_key

    def _build_spec(
        self,
        paths: JobPaths,
        record: RenderJobRecord,
        request_payload: dict[str, object],
    ) -> NormalizedRenderSpec:
        safe_zone_profile = (
            "vertical_default" if record.template_family == "vertical" else "horizontal_default"
        )
        assets = request_payload["assets"]
        if not isinstance(assets, dict):
            raise ValueError("request payload assets must be a dict")
        return NormalizedRenderSpec(
            job_id=paths.job_id,
            template_family=record.template_family,
            template_variant=record.template_variant,
            orientation_detected=record.orientation_detected,
            assets=NormalizedAssets.model_validate(assets),
            composition=CompositionConfig(
                brand_theme=str(request_payload.get("brand_theme") or "default"),
                subtitle_theme=str(request_payload.get("subtitle_theme") or "glassmorphism"),
                safe_zone_profile=safe_zone_profile,
            ),
        )

    def _artifact_entry(self, *, artifact_key: str, object_key: str, content_type: str) -> ArtifactEntry:
        stat = self.store.stat(object_key)
        return ArtifactEntry(
            artifact_key=artifact_key,
            object_key=object_key,
            content_type=content_type,
            size_bytes=stat.size_bytes,
            created_at=utc_now(),
        )

    def _write_record(self, paths: JobPaths, record: RenderJobRecord) -> None:
        self.store.write_json(paths.status_json, record.model_dump(mode="json"))

    def _read_record(self, paths: JobPaths) -> RenderJobRecord:
        return RenderJobRecord.model_validate(self.store.read_json(paths.status_json))

    def _read_project(self, project_id: str) -> ProjectRecord:
        project_paths = self.store.project_paths(project_id)
        if not self.store.exists(project_paths.project_json):
            raise FileNotFoundError(f"project '{project_id}' was not found")
        return ProjectRecord.model_validate(self.store.read_json(project_paths.project_json))

    def _read_revision(self, project_id: str, revision_id: str) -> RevisionRecord:
        revision_paths = self.store.revision_paths(project_id, revision_id)
        if not self.store.exists(revision_paths.revision_json):
            raise FileNotFoundError(f"revision '{revision_id}' was not found for project '{project_id}'")
        return RevisionRecord.model_validate(self.store.read_json(revision_paths.revision_json))

    def _load_project_asset(self, object_key: str) -> UploadedAsset:
        content_type = mimetypes.guess_type(object_key)[0] or "application/octet-stream"
        return UploadedAsset(
            filename=Path(object_key).name,
            content=self.store.read_bytes(object_key),
            content_type=content_type,
        )

    def _load_optional_project_asset(self, object_key: str | None) -> UploadedAsset | None:
        if object_key is None:
            return None
        return self._load_project_asset(object_key)

    def _job_summary(self, record: RenderJobRecord) -> RenderJobSummaryResponse:
        return RenderJobSummaryResponse(
            job_id=record.job_id,
            project_id=record.project_id,
            revision_id=record.revision_id,
            render_mode=record.render_mode,
            status=record.status,
            template_family=record.template_family,
            template_variant=record.template_variant,
            orientation_detected=record.orientation_detected,
            progress_percent=record.progress_percent,
            output_url=record.output_url,
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _project_summary(self, project: ProjectRecord) -> ProjectSummaryResponse:
        return ProjectSummaryResponse(
            project_id=project.project_id,
            name=project.name,
            created_at=project.created_at,
            updated_at=project.updated_at,
            template_family=project.template_family,
            template_variant=project.template_variant,
            orientation_detected=project.orientation_detected,
            brand_theme=project.brand_theme,
            subtitle_theme=project.subtitle_theme,
            active_revision_id=project.active_revision_id,
        )

    def _scaffold_revision_workspace(
        self,
        *,
        revision_paths: RevisionPaths,
        project_name: str,
        revision: RevisionRecord,
        assets: NormalizedAssets,
        brand_theme: str,
        subtitle_theme: str,
    ) -> None:
        workspace_root = self.store.root_dir.joinpath(*revision_paths.workspace.split("/"))
        workspace_root.mkdir(parents=True, exist_ok=True)
        studio_seed = Path(__file__).resolve().parent / "hyperframes" / "studio"
        if studio_seed.exists():
            shutil.copytree(studio_seed, workspace_root, dirs_exist_ok=True)

        manifest = {
            "project_name": project_name,
            "project_id": revision.project_id,
            "revision_id": revision.revision_id,
            "template_family": revision.template_family,
            "template_variant": revision.template_variant,
            "orientation_detected": revision.orientation_detected,
            "brand_theme": brand_theme,
            "subtitle_theme": subtitle_theme,
            "assets": assets.model_dump(mode="json"),
        }
        self.store.write_json(f"{revision_paths.workspace}/project.manifest.json", manifest)

        workspace_meta = {
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "paths": {
                "assets": "assets",
                "blocks": "compositions",
                "components": "compositions/components",
            },
        }
        self.store.write_json(f"{revision_paths.workspace}/hyperframes.json", workspace_meta)


def _file_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.strip()
    return suffix or ".bin"
