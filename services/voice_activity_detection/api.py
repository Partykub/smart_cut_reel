"""FastAPI adapter for the Phase 2 voice activity detection service."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException

from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context
from services.voice_activity_detection.service import VoiceActivityDetectionService
from services.voice_activity_detection.service import warmup_silero_model

logger = logging.getLogger(__name__)


def _start_silero_warmup_thread() -> None:
    """Kick off a background thread that loads the Silero VAD ONNX model.

    Skipped entirely when ``VAD_DISABLE_WARMUP`` is truthy (e.g. unit tests
    that should not depend on network access). The energy backend never
    needs warmup.
    """
    if os.getenv("VAD_DISABLE_WARMUP", "").lower() in {"1", "true", "yes"}:
        logger.info("vad warmup disabled by VAD_DISABLE_WARMUP env")
        return

    def _run_warmup() -> None:
        logger.info("vad: warming up Silero VAD ONNX model")
        ok, error = warmup_silero_model()
        if ok:
            logger.info("vad: Silero warmup complete")
        else:
            logger.warning(
                "vad: Silero warmup failed: %s — first silero /run will pay the cost",
                error,
            )

    threading.Thread(target=_run_warmup, name="silero-warmup", daemon=True).start()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _start_silero_warmup_thread()
    yield


def create_app(service: VoiceActivityDetectionService | None = None) -> FastAPI:
    app = FastAPI(
        title="Smart Cut Reel Voice Activity Detection Service",
        version="0.1.0",
        lifespan=_lifespan,
    )
    vad_service = service or VoiceActivityDetectionService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = vad_service.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
