"""Canonical MinIO path resolution for orchestrator flows (Phase 1 + Phase 2 + Phase 3)."""

from __future__ import annotations

import re


JOB_ID_PATTERN = re.compile(r"^job_[A-Za-z0-9_-]+$")
SERVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

_MANIFEST_FILENAMES = {
    "job_manifest": "job_manifest.json",
    "artifact_manifest": "artifact_manifest.json",
    "service_status": "service_status.json",
}

_ARTIFACT_OBJECT_SUFFIXES = {
    "metadata": "artifacts/metadata.json",
    "extracted_audio": "artifacts/extracted_audio.wav",
    "enhanced_audio": "artifacts/enhanced_audio.wav",
    "vad_segments": "artifacts/vad_segments.json",
    "transcript": "artifacts/transcript.json",
    "cut_plan": "artifacts/cut_plan.json",
    "proxy": "artifacts/proxy.mp4",
    "sampled_frames": "artifacts/sampled_frames.json",
    "body_tracks_raw": "artifacts/body_tracks_raw.json",
    "body_tracks_interpolated": "artifacts/body_tracks_interpolated.json",
    "reframe_plan_raw": "artifacts/reframe_plan_raw.json",
    "reframe_plan_smooth": "artifacts/reframe_plan_smooth.json",
    "render_plan": "artifacts/render_plan.json",
    "final_9x16": "outputs/final_9x16.mp4",
}

KNOWN_ARTIFACT_KEYS = tuple(_ARTIFACT_OBJECT_SUFFIXES)


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_PATTERN.match(job_id):
        raise ValueError(
            f"Invalid job_id '{job_id}'. Expected format matches {JOB_ID_PATTERN.pattern}."
        )
    return job_id


def validate_artifact_key(artifact_key: str) -> str:
    if artifact_key not in _ARTIFACT_OBJECT_SUFFIXES:
        allowed_keys = ", ".join(KNOWN_ARTIFACT_KEYS)
        raise KeyError(f"Unknown artifact key '{artifact_key}'. Expected one of: {allowed_keys}.")
    return artifact_key


def job_prefix(job_id: str) -> str:
    return f"jobs/{validate_job_id(job_id)}"


def input_path(job_id: str) -> str:
    return f"{job_prefix(job_id)}/input/source.mp4"


def manifest_path(job_id: str, manifest_name: str) -> str:
    if manifest_name not in _MANIFEST_FILENAMES:
        allowed = ", ".join(sorted(_MANIFEST_FILENAMES))
        raise KeyError(
            f"Unknown manifest name '{manifest_name}'. Expected one of: {allowed}."
        )
    return f"{job_prefix(job_id)}/manifests/{_MANIFEST_FILENAMES[manifest_name]}"


def artifact_path(job_id: str, artifact_key: str) -> str:
    return f"{job_prefix(job_id)}/{_ARTIFACT_OBJECT_SUFFIXES[validate_artifact_key(artifact_key)]}"


def output_path(job_id: str) -> str:
    return artifact_path(job_id, "final_9x16")


def log_path(job_id: str, service_id: str) -> str:
    if not SERVICE_ID_PATTERN.match(service_id):
        raise ValueError(
            f"Invalid service_id '{service_id}'. Expected format matches {SERVICE_ID_PATTERN.pattern}."
        )
    return f"{job_prefix(job_id)}/logs/{service_id}.log"
