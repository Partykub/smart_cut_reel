"""FastAPI adapter for the audio cut QC service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException

from services.audio_cut_qc.service import AudioCutQcService
from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context


def create_app(service: AudioCutQcService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel Audio Cut QC Service", version="0.1.0")
    qc_service = service or AudioCutQcService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = qc_service.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
