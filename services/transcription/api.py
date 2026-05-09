"""FastAPI adapter for the Phase 3 transcription service."""

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
from services.transcription.service import TranscriptionService
from services.transcription.service import warmup_model

logger = logging.getLogger(__name__)


def _start_warmup_thread() -> None:
    """Kick off a background thread that downloads/loads the Whisper model.

    We run the warmup in a daemon thread so uvicorn startup is not blocked on
    the (potentially slow) model download. The cache inside ``warmup_model``
    means the first ``/run`` call will pick up the already-loaded model.
    """
    if os.getenv("TRANSCRIPTION_DISABLE_WARMUP", "").lower() in {"1", "true", "yes"}:
        logger.info("transcription warmup disabled by TRANSCRIPTION_DISABLE_WARMUP env")
        return

    model_name = os.getenv("TRANSCRIPTION_WARMUP_MODEL", "small")
    compute_type = os.getenv("TRANSCRIPTION_WARMUP_COMPUTE_TYPE", "int8")

    def _run_warmup() -> None:
        logger.info(
            "transcription: warming up faster-whisper model=%s compute_type=%s",
            model_name,
            compute_type,
        )
        ok, error = warmup_model(model_name=model_name, compute_type=compute_type)
        if ok:
            logger.info("transcription: warmup complete (model=%s)", model_name)
        else:
            logger.warning(
                "transcription: warmup failed (model=%s): %s — first /run will pay the cost",
                model_name,
                error,
            )

    threading.Thread(target=_run_warmup, name="whisper-warmup", daemon=True).start()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _start_warmup_thread()
    yield


def create_app(service: TranscriptionService | None = None) -> FastAPI:
    app = FastAPI(
        title="Smart Cut Reel Transcription Service",
        version="0.1.0",
        lifespan=_lifespan,
    )
    transcription_service = service or TranscriptionService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = transcription_service.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
