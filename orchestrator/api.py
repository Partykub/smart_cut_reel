"""FastAPI adapter for the Smart Cut Reel orchestrator."""

import asyncio
import json
from pathlib import Path

from .object_store import FilesystemObjectStore
from .service import OrchestratorService

from .audio_profile import coerce_audio_enhancement_partial


def create_app(service: OrchestratorService | None = None):
    try:
        from fastapi import FastAPI
        from fastapi import File
        from fastapi import Form
        from fastapi import HTTPException
        from fastapi import UploadFile
        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import Response
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
        pipeline_id: str = Form("reframe_16x9_to_9x16"),
        enabled_features: str | None = Form(None),
        audio_profile: str | None = Form(None),
        audio_enhancement: str | None = Form(None),
        output_audio_source: str | None = Form(None),
        vad_audio_source: str | None = Form(None),
        service_config: str | None = Form(None),
    ) -> dict:
        feature_overrides = _parse_enabled_features(enabled_features)
        profile = _parse_audio_profile(audio_profile)
        enhancement_partial = _parse_audio_enhancement_json(audio_enhancement)
        out_audio = _parse_optional_enum_field(
            output_audio_source,
            field="output_audio_source",
            allowed=frozenset({"source_video", "enhanced_wav"}),
        )
        vad_audio = _parse_optional_enum_field(
            vad_audio_source,
            field="vad_audio_source",
            allowed=frozenset(
                {"extracted_audio", "enhanced_audio", "enhanced_audio_or_extracted"}
            ),
        )
        service_config_overrides = _parse_service_config(service_config)
        source_bytes = await source.read()
        try:
            # Disk writes for large uploads can be tens of MB; off-load to a
            # worker thread so the event loop is free for /status polls.
            return await asyncio.to_thread(
                orchestrator_service.create_job,
                source_bytes=source_bytes,
                original_filename=source.filename or "source.mp4",
                content_type=source.content_type or "application/octet-stream",
                created_by=created_by,
                pipeline_id=pipeline_id,
                enabled_features=feature_overrides,
                audio_profile=profile,
                audio_enhancement_partial=enhancement_partial,
                output_audio_source=out_audio,
                vad_audio_source=vad_audio,
                service_config=service_config_overrides,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/status")
    async def get_job_status(job_id: str) -> dict:
        try:
            return await run_in_threadpool(orchestrator_service.get_job_status, job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/jobs/{job_id}/run")
    async def run_job(job_id: str) -> dict:
        # ``run_job`` performs synchronous HTTP calls into the worker services
        # (with model downloads/inference that can take minutes). Running it
        # directly on the FastAPI event loop blocks every other endpoint —
        # including ``POST /jobs`` and ``GET /jobs/{id}/status`` — making the
        # UI appear frozen while a job is in progress. Off-loading to the
        # default thread executor keeps the loop responsive so users can
        # create new jobs and poll status concurrently.
        try:
            return await asyncio.to_thread(orchestrator_service.run_job, job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job_id '{job_id}'.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/artifacts/{artifact_key}")
    async def get_job_artifact(job_id: str, artifact_key: str) -> Response:
        try:
            data, media_type = await run_in_threadpool(
                orchestrator_service.read_artifact_bytes,
                job_id,
                artifact_key,
            )
            return Response(content=data, media_type=media_type)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def _parse_enabled_features(raw: str | None) -> dict[str, bool] | None:
    """Parse the optional ``enabled_features`` form field.

    The frontend sends this as a JSON object (e.g.
    ``{"remove_dead_air": true, "enhance_audio": true}`` for the default
    dead-air upload path) so flags can override the pipeline template.
    Empty / null values mean "use template defaults" — no override.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        from fastapi import HTTPException

        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"enabled_features must be a JSON object: {exc.msg}",
        ) from exc
    if not isinstance(parsed, dict):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="enabled_features must be a JSON object of boolean flags.",
        )
    coerced: dict[str, bool] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="enabled_features keys must be strings.",
            )
        coerced[key] = bool(value)
    return coerced


def _parse_optional_enum_field(
    raw: str | None,
    *,
    field: str,
    allowed: frozenset[str],
) -> str | None:
    if raw is None:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    from fastapi import HTTPException

    if text not in allowed:
        opts = ", ".join(sorted(allowed))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field} '{raw}'. Expected one of: {opts}.",
        )
    return text


def _parse_audio_profile(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    from fastapi import HTTPException

    from .audio_profile import KNOWN_AUDIO_PROFILE_IDS

    if text not in KNOWN_AUDIO_PROFILE_IDS:
        allowed = ", ".join(sorted(KNOWN_AUDIO_PROFILE_IDS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid audio_profile '{raw}'. Expected one of: {allowed}.",
        )
    return text


def _parse_audio_enhancement_json(raw: str | None) -> dict[str, object] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        from fastapi import HTTPException

        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"audio_enhancement must be a JSON object: {exc.msg}",
        ) from exc
    if not isinstance(parsed, dict):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="audio_enhancement must be a JSON object.",
        )
    try:
        coerced = coerce_audio_enhancement_partial(parsed)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return coerced or None


def _parse_service_config(raw: str | None) -> dict[str, dict[str, object]] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        from fastapi import HTTPException

        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"service_config must be a JSON object: {exc.msg}",
        ) from exc
    if not isinstance(parsed, dict):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="service_config must be a JSON object keyed by step ID.",
        )
    coerced: dict[str, dict[str, object]] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="service_config keys must be strings.",
            )
        if not isinstance(value, dict):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="service_config values must be JSON objects.",
            )
        coerced[key] = dict(value)
    return coerced
