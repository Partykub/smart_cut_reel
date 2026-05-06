"""Shared Phase 1 contract constants and schema validation helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Mapping


SCHEMA_VERSION = "1.0.0"

PIPELINE_STEP_IDS = (
    "validation",
    "media_metadata",
    "proxy_frame_sampling",
    "body_detection",
    "track_interpolation",
    "reframe_planning",
    "easing_smoothing",
    "render_plan_compiler",
    "ffmpeg_renderer",
)

ARTIFACT_PRODUCERS = {
    "metadata": "media_metadata",
    "proxy": "proxy_frame_sampling",
    "sampled_frames": "proxy_frame_sampling",
    "body_tracks_raw": "body_detection",
    "body_tracks_interpolated": "track_interpolation",
    "reframe_plan_raw": "reframe_planning",
    "reframe_plan_smooth": "easing_smoothing",
    "render_plan": "render_plan_compiler",
    "final_9x16": "ffmpeg_renderer",
}

ARTIFACT_CONTENT_TYPES = {
    "metadata": "application/json",
    "proxy": "video/mp4",
    "sampled_frames": "application/json",
    "body_tracks_raw": "application/json",
    "body_tracks_interpolated": "application/json",
    "reframe_plan_raw": "application/json",
    "reframe_plan_smooth": "application/json",
    "render_plan": "application/json",
    "final_9x16": "video/mp4",
}

_SCHEMA_FILENAMES = {
    "job_manifest": "job_manifest.schema.json",
    "artifact_manifest": "artifact_manifest.schema.json",
    "service_status": "service_status.schema.json",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def contracts_dir() -> Path:
    return repo_root() / "contracts"


def schema_path(schema_name: str) -> Path:
    if schema_name not in _SCHEMA_FILENAMES:
        allowed = ", ".join(sorted(_SCHEMA_FILENAMES))
        raise KeyError(f"Unknown schema '{schema_name}'. Expected one of: {allowed}.")
    return contracts_dir() / _SCHEMA_FILENAMES[schema_name]


@lru_cache(maxsize=len(_SCHEMA_FILENAMES))
def load_schema(schema_name: str) -> dict[str, Any]:
    return json.loads(schema_path(schema_name).read_text(encoding="utf-8"))


def validate_document(document: Mapping[str, Any], schema_name: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError(
            "jsonschema is required to validate orchestrator manifests. Install the 'jsonschema' package."
        ) from exc

    validator = jsonschema.Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first_error = errors[0]
        location = ".".join(str(part) for part in first_error.path) or "<root>"
        raise ValueError(
            f"{schema_name} validation failed at {location}: {first_error.message}"
        )