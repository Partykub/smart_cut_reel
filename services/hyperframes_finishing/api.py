from __future__ import annotations

from typing import Annotated

from fastapi import BackgroundTasks
from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import Response

from services.hyperframes_finishing.models import JobCreateResponse
from services.hyperframes_finishing.models import JobStatusResponse
from services.hyperframes_finishing.models import ProjectDetailResponse
from services.hyperframes_finishing.models import ProjectSummaryResponse
from services.hyperframes_finishing.models import RevisionSummaryResponse
from services.hyperframes_finishing.service import CreateProjectInput
from services.hyperframes_finishing.service import CreateJobInput
from services.hyperframes_finishing.service import HyperframesFinishingService
from services.hyperframes_finishing.service import UploadedAsset


def create_app(service: HyperframesFinishingService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel Hyperframes Finishing Service", version="0.1.0")
    finishing_service = service or HyperframesFinishingService()

    @app.post("/jobs")
    async def create_job(
        background_tasks: BackgroundTasks,
        source_video: Annotated[UploadFile, File()],
        template_family: Annotated[str, Form()] = "auto",
        template_variant: Annotated[str, Form()] = "default",
        brand_theme: Annotated[str, Form()] = "default",
        subtitle_theme: Annotated[str, Form()] = "glassmorphism",
        created_by: Annotated[str | None, Form()] = None,
        intro_video: Annotated[UploadFile | None, File()] = None,
        outro_video: Annotated[UploadFile | None, File()] = None,
        logo_image: Annotated[UploadFile | None, File()] = None,
        subtitle_file: Annotated[UploadFile | None, File()] = None,
        start_immediately: Annotated[bool, Form()] = True,
    ) -> JobCreateResponse:
        try:
            response = finishing_service.create_job(
                CreateJobInput(
                    source_video=await _to_asset(source_video),
                    template_family=template_family,  # type: ignore[arg-type]
                    template_variant=template_variant,
                    brand_theme=brand_theme,
                    subtitle_theme=subtitle_theme,
                    created_by=created_by,
                    intro_video=await _to_optional_asset(intro_video),
                    outro_video=await _to_optional_asset(outro_video),
                    logo_image=await _to_optional_asset(logo_image),
                    subtitle_file=await _to_optional_asset(subtitle_file),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if start_immediately:
            background_tasks.add_task(finishing_service.run_job, response.job_id)
        return response

    @app.post("/projects")
    async def create_project(
        project_name: Annotated[str, Form()],
        source_video: Annotated[UploadFile, File()],
        template_family: Annotated[str, Form()] = "auto",
        template_variant: Annotated[str, Form()] = "default",
        brand_theme: Annotated[str, Form()] = "default",
        subtitle_theme: Annotated[str, Form()] = "glassmorphism",
        created_by: Annotated[str | None, Form()] = None,
        intro_video: Annotated[UploadFile | None, File()] = None,
        outro_video: Annotated[UploadFile | None, File()] = None,
        logo_image: Annotated[UploadFile | None, File()] = None,
        subtitle_file: Annotated[UploadFile | None, File()] = None,
    ) -> ProjectDetailResponse:
        try:
            return finishing_service.create_project(
                CreateProjectInput(
                    project_name=project_name,
                    source_video=await _to_asset(source_video),
                    template_family=template_family,  # type: ignore[arg-type]
                    template_variant=template_variant,
                    brand_theme=brand_theme,
                    subtitle_theme=subtitle_theme,
                    created_by=created_by,
                    intro_video=await _to_optional_asset(intro_video),
                    outro_video=await _to_optional_asset(outro_video),
                    logo_image=await _to_optional_asset(logo_image),
                    subtitle_file=await _to_optional_asset(subtitle_file),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/projects")
    async def list_projects() -> list[ProjectSummaryResponse]:
        return finishing_service.list_projects()

    @app.get("/projects/{project_id}")
    async def get_project(project_id: str) -> ProjectDetailResponse:
        try:
            return finishing_service.get_project(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/revisions")
    async def list_project_revisions(project_id: str) -> list[RevisionSummaryResponse]:
        try:
            return finishing_service.list_revisions(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/render-draft")
    async def render_project_draft(
        project_id: str,
        background_tasks: BackgroundTasks,
        revision_id: str | None = None,
        start_immediately: bool = True,
    ) -> JobCreateResponse:
        try:
            response = finishing_service.create_draft_render(project_id, revision_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if start_immediately:
            background_tasks.add_task(finishing_service.run_job, response.job_id)
        return response

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> JobStatusResponse:
        try:
            return finishing_service.get_job_status(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/status")
    async def get_job_status(job_id: str) -> JobStatusResponse:
        try:
            return finishing_service.get_job_status(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/jobs/{job_id}/run")
    async def run_job(job_id: str) -> JobStatusResponse:
        try:
            return finishing_service.run_job(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/output")
    async def get_job_output(job_id: str) -> Response:
        try:
            data = finishing_service.read_output(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=data, media_type="video/mp4")

    @app.get("/jobs/{job_id}/artifacts/{artifact_key}")
    async def get_artifact(job_id: str, artifact_key: str) -> Response:
        try:
            data, content_type = finishing_service.read_artifact(job_id, artifact_key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=data, media_type=content_type)

    return app


async def _to_asset(file: UploadFile) -> UploadedAsset:
    content = await file.read()
    if not content:
        raise ValueError(f"uploaded file '{file.filename or 'unnamed'}' is empty")
    return UploadedAsset(
        filename=file.filename or "upload.bin",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )


async def _to_optional_asset(file: UploadFile | None) -> UploadedAsset | None:
    if file is None:
        return None
    return await _to_asset(file)
