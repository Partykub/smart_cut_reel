"""FastAPI adapter for the Phase 1 render plan compiler service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException

from services.common.api_models import ApiRunRequest
from services.common.api_models import ApiRunResponse
from services.common.runtime import build_context
from services.render_plan_compiler.service import RenderPlanCompilerService


def create_app(service: RenderPlanCompilerService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Cut Reel Render Plan Compiler", version="0.1.0")
    compiler = service or RenderPlanCompilerService()

    @app.post("/run")
    async def run(request: ApiRunRequest) -> ApiRunResponse:
        try:
            response = compiler.run(build_context(request.to_runtime()))
            return ApiRunResponse.from_runtime(response)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
