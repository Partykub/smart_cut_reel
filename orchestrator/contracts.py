"""Shared contract constants and schema validation helpers.

Pipeline presets use feature-oriented ``pipeline_id`` strings (reframe-only,
dead-air cuts, audio-quality chain). Only those identifiers are valid in APIs
and manifests.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Mapping


SCHEMA_VERSION = "1.0.0"
SCHEMA_VERSION_JOB_MANIFEST_V2 = "2.0.0"
SCHEMA_VERSION_JOB_MANIFEST_V3 = "3.0.0"

# Canonical pipeline identifiers (feature-oriented).
PIPELINE_ID_REFRAME_16X9_TO_9X16 = "reframe_16x9_to_9x16"
# Smooth reframe + mono audio extract/enhance for mux; no VAD or dead-air cuts (11 steps).
PIPELINE_ID_REFRAME_16X9_TO_9X16_SMOOTH_AUDIO = "reframe_16x9_to_9x16_smooth_audio"
# Still accepted on APIs; ``OrchestratorService.create_job`` maps this to ``PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED``.
PIPELINE_ID_REFRAME_DEAD_AIR = "reframe_16x9_to_9x16_dead_air"
PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED = "reframe_16x9_to_9x16_dead_air_enhanced"
PIPELINE_ID_REFRAME_AUDIO_QUALITY = "reframe_16x9_to_9x16_audio_quality"

KNOWN_PIPELINE_IDS: frozenset[str] = frozenset(
    {
        PIPELINE_ID_REFRAME_16X9_TO_9X16,
        PIPELINE_ID_REFRAME_16X9_TO_9X16_SMOOTH_AUDIO,
        PIPELINE_ID_REFRAME_DEAD_AIR,
        PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED,
        PIPELINE_ID_REFRAME_AUDIO_QUALITY,
    }
)

REFRAME_ONLY_STEP_IDS: tuple[str, ...] = (
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

REFRAME_DEAD_AIR_STEP_IDS: tuple[str, ...] = (
    "validation",
    "media_metadata",
    "audio_extraction",
    "voice_activity_detection",
    "dead_air_cut_planning",
    "proxy_frame_sampling",
    "body_detection",
    "track_interpolation",
    "reframe_planning",
    "easing_smoothing",
    "render_plan_compiler",
    "ffmpeg_renderer",
)

REFRAME_DEAD_AIR_ENHANCED_STEP_IDS: tuple[str, ...] = (
    "validation",
    "media_metadata",
    "audio_extraction",
    "audio_enhancement",
    "voice_activity_detection",
    "dead_air_cut_planning",
    "proxy_frame_sampling",
    "body_detection",
    "track_interpolation",
    "reframe_planning",
    "easing_smoothing",
    "render_plan_compiler",
    "ffmpeg_renderer",
)

REFRAME_AUDIO_QUALITY_STEP_IDS: tuple[str, ...] = (
    "validation",
    "media_metadata",
    "audio_extraction",
    "audio_enhancement",
    "voice_activity_detection",
    "transcription",
    "dead_air_cut_planning",
    "proxy_frame_sampling",
    "body_detection",
    "track_interpolation",
    "reframe_planning",
    "easing_smoothing",
    "render_plan_compiler",
    "ffmpeg_renderer",
)

REFRAME_SMOOTH_AUDIO_STEP_IDS: tuple[str, ...] = (
    "validation",
    "media_metadata",
    "audio_extraction",
    "audio_enhancement",
    "proxy_frame_sampling",
    "body_detection",
    "track_interpolation",
    "reframe_planning",
    "easing_smoothing",
    "render_plan_compiler",
    "ffmpeg_renderer",
)

PIPELINE_STEP_IDS = REFRAME_ONLY_STEP_IDS

PIPELINE_STEPS_BY_ID: dict[str, tuple[str, ...]] = {
    PIPELINE_ID_REFRAME_16X9_TO_9X16: REFRAME_ONLY_STEP_IDS,
    PIPELINE_ID_REFRAME_16X9_TO_9X16_SMOOTH_AUDIO: REFRAME_SMOOTH_AUDIO_STEP_IDS,
    PIPELINE_ID_REFRAME_DEAD_AIR: REFRAME_DEAD_AIR_STEP_IDS,
    PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED: REFRAME_DEAD_AIR_ENHANCED_STEP_IDS,
    PIPELINE_ID_REFRAME_AUDIO_QUALITY: REFRAME_AUDIO_QUALITY_STEP_IDS,
}

KNOWN_PIPELINE_STEP_IDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        REFRAME_ONLY_STEP_IDS
        + REFRAME_SMOOTH_AUDIO_STEP_IDS
        + REFRAME_DEAD_AIR_STEP_IDS
        + REFRAME_DEAD_AIR_ENHANCED_STEP_IDS
        + REFRAME_AUDIO_QUALITY_STEP_IDS
    )
)

ARTIFACT_PRODUCERS: dict[str, str] = {
    "metadata": "media_metadata",
    "extracted_audio": "audio_extraction",
    "enhanced_audio": "audio_enhancement",
    "vad_segments": "voice_activity_detection",
    "transcript": "transcription",
    "cut_plan": "dead_air_cut_planning",
    "proxy": "proxy_frame_sampling",
    "sampled_frames": "proxy_frame_sampling",
    "body_tracks_raw": "body_detection",
    "body_tracks_interpolated": "track_interpolation",
    "reframe_plan_raw": "reframe_planning",
    "reframe_plan_smooth": "easing_smoothing",
    "render_plan": "render_plan_compiler",
    "final_9x16": "ffmpeg_renderer",
    "source_overlay": "ffmpeg_renderer",
}

ARTIFACT_CONTENT_TYPES: dict[str, str] = {
    "metadata": "application/json",
    "extracted_audio": "audio/wav",
    "enhanced_audio": "audio/wav",
    "vad_segments": "application/json",
    "transcript": "application/json",
    "cut_plan": "application/json",
    "proxy": "video/mp4",
    "sampled_frames": "application/json",
    "body_tracks_raw": "application/json",
    "body_tracks_interpolated": "application/json",
    "reframe_plan_raw": "application/json",
    "reframe_plan_smooth": "application/json",
    "render_plan": "application/json",
    "final_9x16": "video/mp4",
    "source_overlay": "video/mp4",
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


def steps_for_pipeline(pipeline_id: str) -> tuple[str, ...]:
    try:
        return PIPELINE_STEPS_BY_ID[pipeline_id]
    except KeyError as exc:
        allowed = ", ".join(sorted(KNOWN_PIPELINE_IDS))
        raise KeyError(
            f"Unknown pipeline_id '{pipeline_id}'. Expected one of: {allowed}."
        ) from exc


def schema_version_for_pipeline(pipeline_id: str) -> str:
    if pipeline_id == PIPELINE_ID_REFRAME_AUDIO_QUALITY:
        return SCHEMA_VERSION_JOB_MANIFEST_V3
    if pipeline_id == PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED:
        return SCHEMA_VERSION_JOB_MANIFEST_V3
    if pipeline_id == PIPELINE_ID_REFRAME_DEAD_AIR:
        return SCHEMA_VERSION_JOB_MANIFEST_V2
    return SCHEMA_VERSION


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
