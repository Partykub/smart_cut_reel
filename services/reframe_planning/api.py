"""FastAPI adapter for the Phase 1 reframe planning service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException

from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context
from services.reframe_planning.service import ReframePlanningService


def create_app(service: ReframePlanningService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel Reframe Planning Service", version="0.1.0")
    planning_service = service or ReframePlanningService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = planning_service.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
