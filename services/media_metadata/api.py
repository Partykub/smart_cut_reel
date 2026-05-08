"""FastAPI adapter for the Phase 1 media metadata service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException

from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context
from services.media_metadata.service import MediaMetadataService


def create_app(service: MediaMetadataService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel Media Metadata Service", version="0.1.0")
    metadata_service = service or MediaMetadataService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = metadata_service.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
