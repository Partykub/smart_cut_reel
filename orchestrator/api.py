"""FastAPI adapter for the Phase 1 orchestrator service."""

from pathlib import Path

from .object_store import FilesystemObjectStore
from .service import OrchestratorService


def create_app(service: OrchestratorService | None = None):
    try:
        from fastapi import FastAPI
        from fastapi import File
        from fastapi import Form
        from fastapi import HTTPException
        from fastapi import UploadFile
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI runtime dependencies are missing. Install requirements.txt before using orchestrator.api."
        ) from exc

    app = FastAPI(title="Smart Cut Reel Orchestrator", version="0.1.0")
    orchestrator_service = service or OrchestratorService(
        FilesystemObjectStore(Path(".orchestrator-data"))
    )

    @app.post("/jobs")
    async def create_job(
        source: UploadFile = File(...),
        created_by: str = Form("debug_frontend"),
    ) -> dict:
        try:
            return orchestrator_service.create_job(
                source_bytes=await source.read(),
                original_filename=source.filename or "source.mp4",
                content_type=source.content_type or "application/octet-stream",
                created_by=created_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/status")
    async def get_job_status(job_id: str) -> dict:
        try:
            return orchestrator_service.get_job_status(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/jobs/{job_id}/run")
    async def run_job(job_id: str) -> dict:
        try:
            return orchestrator_service.run_job(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
