"""Compile render_plan.json from metadata and smoothed reframe plan."""

from __future__ import annotations

from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


RENDER_PLAN_SCHEMA_VERSION = "1.0.0"


class RenderPlanCompilerService:
    service_id = "render_plan_compiler"

    def run(self, context: ServiceContext) -> RunResponse:
        job_manifest = context.read_json(context.input_key("job_manifest"))
        artifact_manifest = self._artifact_manifest(context)

        artifacts = artifact_manifest.get("artifacts", {})
        meta_entry = artifacts.get("metadata", {})
        smooth_entry = artifacts.get("reframe_plan_smooth", {})
        metadata_key = meta_entry.get("object_key") if isinstance(meta_entry, dict) else None
        smooth_key = smooth_entry.get("object_key") if isinstance(smooth_entry, dict) else None

        if not isinstance(metadata_key, str) or not context.exists(metadata_key):
            raise ValueError("artifact_manifest is missing metadata for render_plan_compiler")
        if not isinstance(smooth_key, str) or not context.exists(smooth_key):
            raise ValueError("artifact_manifest is missing reframe_plan_smooth for render_plan_compiler")

        metadata = context.read_json(metadata_key)
        smooth_plan = context.read_json(smooth_key)

        source_key = job_manifest.get("input", {}).get("source_video", {}).get("object_key")
        output_key_manifest = job_manifest.get("target_output", {}).get("object_key")
        if not isinstance(source_key, str):
            raise ValueError("job_manifest is missing input.source_video.object_key")
        if not isinstance(output_key_manifest, str):
            raise ValueError("job_manifest is missing target_output.object_key")

        config = self._config(context)
        crop_representation = config["crop_representation"]
        audio_policy = config["audio_policy"]

        keyframes = smooth_plan.get("keyframes", [])
        if not isinstance(keyframes, list) or not keyframes:
            raise ValueError("reframe_plan_smooth must contain a non-empty keyframes list")

        crop_width = int(smooth_plan.get("crop_width") or 0)
        crop_height = int(smooth_plan.get("crop_height") or 0)
        if crop_width <= 0 or crop_height <= 0:
            raise ValueError("reframe_plan_smooth must include positive crop_width and crop_height")

        source_res = smooth_plan.get("source_resolution") or {}
        source_width = int(metadata.get("width") or source_res.get("width") or 0)
        source_height = int(metadata.get("height") or source_res.get("height") or 0)
        if source_width <= 0 or source_height <= 0:
            raise ValueError("metadata must include valid source dimensions")

        target_resolution = smooth_plan.get("target_resolution") or job_manifest.get(
            "target_output", {}
        ).get("resolution", {"width": 1080, "height": 1920})

        fps = float(metadata.get("fps") or 0.0)
        duration = float(metadata.get("duration") or 0.0)
        if fps <= 0 or duration <= 0:
            raise ValueError("metadata must include positive fps and duration")

        render_mode = config.get("compiler_render_mode", "smooth_crop")
        if render_mode not in {"static_crop", "smooth_crop"}:
            raise ValueError(f"Invalid compiler_render_mode '{render_mode}'")

        payload: dict[str, Any] = {
            "schema_version": RENDER_PLAN_SCHEMA_VERSION,
            "job_id": context.job_id,
            "crop_representation": crop_representation,
            "audio_policy": audio_policy,
            "source_video": {"object_key": source_key},
            "output": {"object_key": output_key_manifest},
            "target_resolution": target_resolution,
            "metadata": {
                "fps": fps,
                "duration": duration,
                "source_width": source_width,
                "source_height": source_height,
            },
            "crop_plan": {
                "object_key": smooth_key,
                "crop_width": crop_width,
                "crop_height": crop_height,
                "keyframes": keyframes,
            },
            "render_mode": render_mode,
        }

        out_key = context.expected_output_key("render_plan")
        context.write_json(out_key, payload)
        return RunResponse(service_id=self.service_id, outputs={"render_plan": out_key})

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for render_plan_compiler")
        return context.read_json(artifact_manifest_key)

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "crop_representation": "keyframe_list",
            "audio_policy": "copy_if_possible_else_aac",
            "compiler_render_mode": "smooth_crop",
        }
        defaults.update(context.request.config)
        crop_repr = defaults["crop_representation"]
        if crop_repr not in {"keyframe_list", "per_frame_list", "ffmpeg_expression_file"}:
            raise ValueError(f"Invalid crop_representation '{crop_repr}'")
        audio = defaults["audio_policy"]
        if audio not in {"copy_if_possible_else_aac", "aac_transcode"}:
            raise ValueError(f"Invalid audio_policy '{audio}'")
        return defaults
