"""FastAPI adapter for the Phase 2 dead air cut planning service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException

from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context
from services.dead_air_cut_planning.service import DeadAirCutPlanningService


def create_app(service: DeadAirCutPlanningService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel Dead Air Cut Planning Service", version="0.1.0")
    cut_service = service or DeadAirCutPlanningService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = cut_service.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
