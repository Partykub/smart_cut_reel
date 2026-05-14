"""Core orchestration service for job creation, status lookup, and pipeline execution."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from typing import Any
from uuid import uuid4

from .artifact_helper import ArtifactHelper
from .audio_profile import merge_audio_enhancement_service_config
from .contracts import ARTIFACT_CONTENT_TYPES
from .contracts import KNOWN_PIPELINE_IDS
from .contracts import PIPELINE_ID_REFRAME_16X9_TO_9X16
from .contracts import PIPELINE_ID_REFRAME_16X9_TO_9X16_SMOOTH_AUDIO
from .contracts import PIPELINE_ID_REFRAME_AUDIO_QUALITY
from .contracts import PIPELINE_ID_REFRAME_DEAD_AIR
from .contracts import PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED
from .contracts import PIPELINE_STEPS_BY_ID
from .contracts import repo_root
from .manifest_manager import ManifestManager
from .manifest_manager import utc_now
from .object_store import ObjectStore
from .path_resolver import artifact_path
from .path_resolver import input_path
from .path_resolver import job_prefix
from .path_resolver import manifest_path
from .path_resolver import output_path
from .path_resolver import validate_artifact_key
from .path_resolver import validate_job_id
from .pipeline_runner import HttpPipelineRunner
from .pipeline_runner import MockPipelineRunner
from .pipeline_runner import PipelineRunner
from .pipeline_runner import artifact_keys_for_step


_JOB_MANIFEST_TEMPLATES_BY_PIPELINE_ID = {
    PIPELINE_ID_REFRAME_16X9_TO_9X16: "contracts/examples/job_manifest.reframe_16x9_to_9x16.sample.json",
    PIPELINE_ID_REFRAME_16X9_TO_9X16_SMOOTH_AUDIO: "contracts/examples/job_manifest.reframe_16x9_to_9x16_smooth_audio.sample.json",
    # Legacy ID kept for templates/tests; create_job maps this to dead_air_enhanced.
    PIPELINE_ID_REFRAME_DEAD_AIR: "contracts/examples/job_manifest.reframe_16x9_to_9x16_dead_air.sample.json",
    PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED: "contracts/examples/job_manifest.reframe_16x9_to_9x16_dead_air_enhanced.sample.json",
    PIPELINE_ID_REFRAME_AUDIO_QUALITY: "contracts/examples/job_manifest.reframe_16x9_to_9x16_audio_quality.sample.json",
}


class OrchestratorService:
    def __init__(
        self,
        store: ObjectStore,
        *,
        runner: PipelineRunner | None = None,
        job_manifest_template: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.manifest_manager = ManifestManager(store)
        self.artifact_helper = ArtifactHelper(store, self.manifest_manager)
        self.runner = runner or _build_default_runner()
        self.job_manifest_templates: dict[str, dict[str, Any]] = {
            pipeline_id: _load_job_manifest_template(path)
            for pipeline_id, path in _JOB_MANIFEST_TEMPLATES_BY_PIPELINE_ID.items()
        }
        if job_manifest_template is not None:
            override_pipeline_id = job_manifest_template.get("pipeline", {}).get(
                "pipeline_id", PIPELINE_ID_REFRAME_16X9_TO_9X16
            )
            self.job_manifest_templates[override_pipeline_id] = job_manifest_template

    def create_job(
        self,
        *,
        source_bytes: bytes,
        original_filename: str,
        content_type: str = "video/mp4",
        created_by: str = "debug_frontend",
        job_id: str | None = None,
        pipeline_id: str = PIPELINE_ID_REFRAME_16X9_TO_9X16,
        enabled_features: dict[str, bool] | None = None,
        audio_profile: str | None = None,
        audio_enhancement_partial: dict[str, Any] | None = None,
        output_audio_source: str | None = None,
        vad_audio_source: str | None = None,
    ) -> dict[str, Any]:
        if not source_bytes:
            raise ValueError("source_bytes must not be empty.")
        if pipeline_id not in KNOWN_PIPELINE_IDS:
            allowed = ", ".join(sorted(KNOWN_PIPELINE_IDS))
            raise ValueError(
                f"Unknown pipeline_id '{pipeline_id}'. Expected one of: {allowed}."
            )

        pipeline_id, enabled_features = _coerce_dead_air_pipeline_to_enhanced(
            pipeline_id, enabled_features
        )

        created_at = utc_now()
        resolved_job_id = validate_job_id(job_id or f"job_{uuid4().hex[:12]}")
        resolved_filename = original_filename or "source.mp4"

        job_manifest = self._build_job_manifest(
            pipeline_id=pipeline_id,
            job_id=resolved_job_id,
            created_at=created_at,
            created_by=created_by,
            original_filename=resolved_filename,
            content_type=content_type,
            checksum_sha256=hashlib.sha256(source_bytes).hexdigest(),
            enabled_features_overrides=enabled_features,
            audio_profile=audio_profile,
            audio_enhancement_partial=audio_enhancement_partial,
            output_audio_source=output_audio_source,
            vad_audio_source=vad_audio_source,
        )

        self.artifact_helper.upload_source_video(
            resolved_job_id,
            source_bytes,
            content_type=content_type,
        )
        self.manifest_manager.create_initial_job_state(job_manifest)
        return self.get_job_status(resolved_job_id)

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        resolved_job_id = validate_job_id(job_id)
        self._reconcile_completed_final_render(resolved_job_id)
        service_status = self.manifest_manager.read_service_status(resolved_job_id)
        artifact_manifest = self.manifest_manager.read_artifact_manifest(resolved_job_id)
        job_manifest = self.manifest_manager.read_job_manifest(resolved_job_id)
        pipeline = job_manifest.get("pipeline", {})
        raw_pipeline_id = pipeline.get("pipeline_id", PIPELINE_ID_REFRAME_16X9_TO_9X16)
        service_cfg = job_manifest.get("service_config")
        audio_enhancement = None
        if isinstance(service_cfg, dict):
            ae = service_cfg.get("audio_enhancement")
            if isinstance(ae, dict):
                audio_enhancement = ae

        return {
            "job_id": resolved_job_id,
            "service_status": service_status,
            "artifacts": artifact_manifest["artifacts"],
            "pipeline": {
                "pipeline_id": str(raw_pipeline_id),
                "steps": pipeline.get("steps", []),
            },
            "enabled_features": job_manifest.get("enabled_features", {}),
            "audio_profile": job_manifest.get("audio_profile"),
            "audio_enhancement": audio_enhancement,
            "output_audio_source": (
                (service_cfg.get("render_plan_compiler") or {}).get("output_audio_source")
                if isinstance(service_cfg, dict)
                else None
            ),
            "vad_audio_source": (
                (service_cfg.get("voice_activity_detection") or {}).get("audio_source")
                if isinstance(service_cfg, dict)
                else None
            ),
            "paths": {
                "job_prefix": job_prefix(resolved_job_id),
                "input": input_path(resolved_job_id),
                "job_manifest": manifest_path(resolved_job_id, "job_manifest"),
                "artifact_manifest": manifest_path(resolved_job_id, "artifact_manifest"),
                "service_status": manifest_path(resolved_job_id, "service_status"),
                "output": output_path(resolved_job_id),
            },
        }

    def _reconcile_completed_final_render(self, job_id: str) -> None:
        service_status = self.manifest_manager.read_service_status(job_id)
        if service_status.get("status") != "running":
            return
        if service_status.get("current_step") != "ffmpeg_renderer":
            return

        final_step = service_status["steps"].get("ffmpeg_renderer", {})
        if final_step.get("status") != "running":
            return

        expected_artifacts = artifact_keys_for_step("ffmpeg_renderer")
        if not all(self.store.exists(artifact_path(job_id, artifact_key)) for artifact_key in expected_artifacts):
            return

        artifact_manifest = self.manifest_manager.read_artifact_manifest(job_id)
        for artifact_key in expected_artifacts:
            if artifact_key not in artifact_manifest.get("artifacts", {}):
                self.manifest_manager.register_artifact(job_id, artifact_key, produced_by="ffmpeg_renderer")

        self.manifest_manager.set_step_state(
            job_id,
            "ffmpeg_renderer",
            step_status="success",
            finished_at=utc_now(),
            overall_status="success",
            current_step=None,
        )

    def read_artifact_bytes(self, job_id: str, artifact_key: str) -> tuple[bytes, str]:
        """Return artifact bytes and Content-Type for a registered artifact."""
        resolved_job_id = validate_job_id(job_id)
        artifact_key = validate_artifact_key(artifact_key)
        manifest = self.manifest_manager.read_artifact_manifest(resolved_job_id)
        artifacts = manifest.get("artifacts", {})
        meta = artifacts.get(artifact_key)
        if not isinstance(meta, dict):
            raise FileNotFoundError(f"Artifact '{artifact_key}' is not registered for job '{resolved_job_id}'.")
        object_key = meta.get("object_key")
        if not isinstance(object_key, str):
            raise FileNotFoundError(f"Artifact '{artifact_key}' has no object_key.")
        if not self.store.exists(object_key):
            raise FileNotFoundError(f"Object '{object_key}' does not exist in storage.")
        content_type = ARTIFACT_CONTENT_TYPES.get(artifact_key, "application/octet-stream")
        return self.store.download_bytes(object_key), content_type

    def run_job(self, job_id: str) -> dict[str, Any]:
        resolved_job_id = validate_job_id(job_id)
        self.manifest_manager.read_job_manifest(resolved_job_id)
        self.runner.run(
            job_id=resolved_job_id,
            manifest_manager=self.manifest_manager,
            artifact_helper=self.artifact_helper,
        )
        return self.get_job_status(resolved_job_id)

    def _build_job_manifest(
        self,
        *,
        pipeline_id: str,
        job_id: str,
        created_at: str,
        created_by: str,
        original_filename: str,
        content_type: str,
        checksum_sha256: str,
        enabled_features_overrides: dict[str, bool] | None = None,
        audio_profile: str | None = None,
        audio_enhancement_partial: dict[str, Any] | None = None,
        output_audio_source: str | None = None,
        vad_audio_source: str | None = None,
    ) -> dict[str, Any]:
        template = self.job_manifest_templates.get(pipeline_id)
        if template is None:
            raise ValueError(
                f"No job manifest template registered for pipeline_id '{pipeline_id}'."
            )
        manifest = deepcopy(template)
        manifest["job_id"] = job_id
        manifest["created_at"] = created_at
        manifest["created_by"] = created_by
        manifest["input"]["source_video"]["object_key"] = input_path(job_id)
        manifest["input"]["source_video"]["original_filename"] = original_filename
        manifest["input"]["source_video"]["uploaded_at"] = created_at
        manifest["input"]["source_video"]["content_type"] = content_type
        manifest["input"]["source_video"]["checksum_sha256"] = checksum_sha256
        manifest["target_output"]["object_key"] = output_path(job_id)
        manifest["pipeline"]["pipeline_id"] = pipeline_id
        manifest["pipeline"]["steps"] = list(PIPELINE_STEPS_BY_ID[pipeline_id])

        if enabled_features_overrides:
            existing = manifest.get("enabled_features")
            if not isinstance(existing, dict):
                existing = {}
            for feature_key, value in enabled_features_overrides.items():
                if value:
                    existing[feature_key] = True
                else:
                    existing.pop(feature_key, None)
            manifest["enabled_features"] = existing

        steps = manifest.get("pipeline", {}).get("steps") or []
        has_audio_enhancement = "audio_enhancement" in steps
        if audio_profile or audio_enhancement_partial:
            if not has_audio_enhancement:
                raise ValueError(
                    "audio_profile and audio_enhancement are only allowed for pipelines "
                    "that include the audio_enhancement step."
                )
            service_config = manifest.setdefault("service_config", {})
            base_ae = service_config.get("audio_enhancement")
            if not isinstance(base_ae, dict):
                base_ae = {}
            service_config["audio_enhancement"] = merge_audio_enhancement_service_config(
                base_ae,
                profile_id=audio_profile,
                partial=audio_enhancement_partial,
            )
        if audio_profile:
            manifest["audio_profile"] = audio_profile
        else:
            manifest.pop("audio_profile", None)

        # Loudness/denoise presets (podcast / social / broadcast) bake into
        # ``enhanced_audio.wav``; muxing final MP4 from source video would hide
        # that work. When the client omits ``output_audio_source``, default the
        # render plan to ``enhanced_wav`` for those profiles. Explicit
        # ``output_audio_source`` always wins (e.g. force source track).
        if output_audio_source is None and audio_profile in {
            "podcast",
            "social",
            "broadcast",
        }:
            if has_audio_enhancement:
                rpc = manifest.setdefault("service_config", {}).setdefault(
                    "render_plan_compiler", {}
                )
                rpc["output_audio_source"] = "enhanced_wav"

        _apply_output_audio_source_manifest(
            manifest,
            output_audio_source=output_audio_source,
        )
        _apply_vad_audio_source_manifest(manifest, vad_audio_source=vad_audio_source)

        return manifest


_VALID_OUTPUT_AUDIO_SOURCE_IDS = frozenset({"source_video", "enhanced_wav"})
_VALID_VAD_AUDIO_SOURCE_IDS = frozenset(
    {"extracted_audio", "enhanced_audio", "enhanced_audio_or_extracted"}
)


def _apply_output_audio_source_manifest(
    manifest: dict[str, Any],
    *,
    output_audio_source: str | None,
) -> None:
    if output_audio_source is None:
        return
    if output_audio_source not in _VALID_OUTPUT_AUDIO_SOURCE_IDS:
        allowed = ", ".join(sorted(_VALID_OUTPUT_AUDIO_SOURCE_IDS))
        raise ValueError(
            f"Invalid output_audio_source '{output_audio_source}'. Expected one of: {allowed}."
        )
    steps = manifest.get("pipeline", {}).get("steps") or []
    if output_audio_source == "enhanced_wav" and "audio_enhancement" not in steps:
        raise ValueError(
            "output_audio_source=enhanced_wav requires a pipeline that includes "
            "the audio_enhancement step."
        )
    service_config = manifest.setdefault("service_config", {})
    rpc = service_config.setdefault("render_plan_compiler", {})
    rpc["output_audio_source"] = output_audio_source


def _apply_vad_audio_source_manifest(
    manifest: dict[str, Any],
    *,
    vad_audio_source: str | None,
) -> None:
    if vad_audio_source is None:
        return
    if vad_audio_source not in _VALID_VAD_AUDIO_SOURCE_IDS:
        allowed = ", ".join(sorted(_VALID_VAD_AUDIO_SOURCE_IDS))
        raise ValueError(
            f"Invalid vad_audio_source '{vad_audio_source}'. Expected one of: {allowed}."
        )
    steps = manifest.get("pipeline", {}).get("steps") or []
    if "voice_activity_detection" not in steps:
        raise ValueError(
            "vad_audio_source is only allowed for pipelines that include voice_activity_detection."
        )
    service_config = manifest.setdefault("service_config", {})
    vad = service_config.setdefault("voice_activity_detection", {})
    vad["audio_source"] = vad_audio_source


def _load_job_manifest_template(relative_path: str) -> dict[str, Any]:
    template_path = repo_root() / relative_path
    return json.loads(template_path.read_text(encoding="utf-8"))


def _coerce_dead_air_pipeline_to_enhanced(
    pipeline_id: str,
    enabled_features: dict[str, bool] | None,
) -> tuple[str, dict[str, bool] | None]:
    """Use the dead-air + FFmpeg prep pipeline whenever the legacy dead-air id is requested.

    Callers may still pass ``reframe_16x9_to_9x16_dead_air`` for compatibility; job manifests
    always materialize as ``reframe_16x9_to_9x16_dead_air_enhanced`` with ``enhance_audio`` on.
    """
    if pipeline_id != PIPELINE_ID_REFRAME_DEAD_AIR:
        return pipeline_id, enabled_features
    merged: dict[str, bool] = dict(enabled_features) if enabled_features else {}
    merged["enhance_audio"] = True
    return PIPELINE_ID_REFRAME_DEAD_AIR_ENHANCED, merged


_DEFAULT_STEP_TIMEOUTS_SECONDS: dict[str, float] = {
    "audio_enhancement": 600.0,
    "voice_activity_detection": 600.0,
    "transcription": 1800.0,
    "body_detection": 1800.0,
    "ffmpeg_renderer": 1800.0,
    "proxy_frame_sampling": 600.0,
}


def _parse_step_timeouts_env() -> dict[str, float]:
    raw = os.getenv("ORCHESTRATOR_STEP_TIMEOUTS_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "ORCHESTRATOR_STEP_TIMEOUTS_JSON must be a JSON object mapping step IDs to timeout seconds."
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            "ORCHESTRATOR_STEP_TIMEOUTS_JSON must be a JSON object mapping step IDs to timeout seconds."
        )
    overrides: dict[str, float] = {}
    for step_id, value in parsed.items():
        if not isinstance(step_id, str):
            raise RuntimeError(
                "ORCHESTRATOR_STEP_TIMEOUTS_JSON keys must be step ID strings."
            )
        try:
            overrides[step_id] = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"ORCHESTRATOR_STEP_TIMEOUTS_JSON value for '{step_id}' must be a number."
            ) from exc
    return overrides


def _build_default_runner() -> PipelineRunner:
    raw_service_endpoints = os.getenv("ORCHESTRATOR_SERVICE_ENDPOINTS")
    if not raw_service_endpoints:
        return MockPipelineRunner()

    raw_request_timeout_seconds = os.getenv("ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS")
    request_timeout_seconds: float | None
    if raw_request_timeout_seconds is None or raw_request_timeout_seconds.strip() in {"", "0", "none", "None"}:
        request_timeout_seconds = None
    else:
        try:
            request_timeout_seconds = float(raw_request_timeout_seconds)
        except ValueError as exc:
            raise RuntimeError(
                "ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS must be a number, or 0/none to disable the timeout."
            ) from exc
        if request_timeout_seconds <= 0:
            raise RuntimeError(
                "ORCHESTRATOR_REQUEST_TIMEOUT_SECONDS must be a positive number, or 0/none to disable the timeout."
            )

    try:
        service_endpoints = json.loads(raw_service_endpoints)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "ORCHESTRATOR_SERVICE_ENDPOINTS must be a JSON object mapping step IDs to service URLs."
        ) from exc

    if not isinstance(service_endpoints, dict) or not all(
        isinstance(step_id, str) and isinstance(endpoint, str)
        for step_id, endpoint in service_endpoints.items()
    ):
        raise RuntimeError(
            "ORCHESTRATOR_SERVICE_ENDPOINTS must be a JSON object mapping step IDs to service URLs."
        )

    step_timeouts: dict[str, float] = dict(_DEFAULT_STEP_TIMEOUTS_SECONDS)
    step_timeouts.update(_parse_step_timeouts_env())

    return HttpPipelineRunner(
        service_endpoints=service_endpoints,
        minio_bucket=os.getenv("ORCHESTRATOR_MINIO_BUCKET", "smart-cut"),
        request_timeout_seconds=request_timeout_seconds,
        step_timeouts_seconds=step_timeouts,
    )
