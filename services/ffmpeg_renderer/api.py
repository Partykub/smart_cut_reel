"""FastAPI adapter for the Phase 1 FFmpeg renderer service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException

from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context
from services.ffmpeg_renderer.service import FFmpegRendererService


def create_app(service: FFmpegRendererService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel FFmpeg Renderer", version="0.1.0")
    renderer = service or FFmpegRendererService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = renderer.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
