"""Compile ``render_plan.json`` from metadata, smoothed reframe plan, and (optionally) cut plan.

Phase 1 emits a single keep segment covering the whole source so the renderer
falls back to its existing crop+concat behavior. Jobs with dead-air cuts use
``smooth_crop_with_cuts`` to project easing output onto each keep segment.

``full_frame_with_cuts`` is an optional compiler mode that skips a stored
``reframe_plan_smooth`` file and synthesizes a full-frame crop from metadata
(useful for experiments or audio-only renders).
"""

from __future__ import annotations

from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


RENDER_PLAN_SCHEMA_VERSION = "1.1.0"

_VALID_OUTPUT_AUDIO_SOURCES = frozenset({"source_video", "enhanced_wav"})

_VALID_COMPILER_RENDER_MODES = frozenset(
    {"static_crop", "smooth_crop", "smooth_crop_with_cuts", "full_frame_with_cuts"}
)


class RenderPlanCompilerService:
    service_id = "render_plan_compiler"

    def run(self, context: ServiceContext) -> RunResponse:
        job_manifest = context.read_json(context.input_key("job_manifest"))
        artifact_manifest = self._artifact_manifest(context)
        artifacts = artifact_manifest.get("artifacts", {})

        metadata_key = self._artifact_key(artifacts, "metadata")

        if not isinstance(metadata_key, str) or not context.exists(metadata_key):
            raise ValueError("artifact_manifest is missing metadata for render_plan_compiler")

        metadata = context.read_json(metadata_key)

        config = self._config(context)
        compiler_mode = config["compiler_render_mode"]
        if compiler_mode not in _VALID_COMPILER_RENDER_MODES:
            raise ValueError(f"Invalid compiler_render_mode '{compiler_mode}'")

        if compiler_mode == "full_frame_with_cuts":
            duration_probe = float(metadata.get("duration") or 0.0)
            smooth_plan = self._synthetic_full_frame_smooth(metadata, duration_probe, job_manifest)
            smooth_key = metadata_key
        else:
            smooth_key = self._artifact_key(artifacts, "reframe_plan_smooth")
            if not isinstance(smooth_key, str) or not context.exists(smooth_key):
                raise ValueError("artifact_manifest is missing reframe_plan_smooth for render_plan_compiler")
            smooth_plan = context.read_json(smooth_key)

        source_key = job_manifest.get("input", {}).get("source_video", {}).get("object_key")
        output_key_manifest = job_manifest.get("target_output", {}).get("object_key")
        if not isinstance(source_key, str):
            raise ValueError("job_manifest is missing input.source_video.object_key")
        if not isinstance(output_key_manifest, str):
            raise ValueError("job_manifest is missing target_output.object_key")

        crop_representation = config["crop_representation"]
        audio_policy = config["audio_policy"]
        output_render_mode = (
            "smooth_crop_with_cuts"
            if compiler_mode in {"smooth_crop_with_cuts", "full_frame_with_cuts"}
            else compiler_mode
        )

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

        keep_segments = self._resolve_keep_segments(
            artifacts=artifacts,
            context=context,
            compiler_mode=compiler_mode,
            duration=duration,
        )

        sorted_keyframes = sorted(keyframes, key=lambda k: float(k.get("t") or 0.0))
        segments = [
            {
                "source_start": round(float(seg["source_start"]), 6),
                "source_end": round(float(seg["source_end"]), 6),
                "crop_keyframes": _slice_keyframes(
                    sorted_keyframes,
                    seg_start=float(seg["source_start"]),
                    seg_end=float(seg["source_end"]),
                ),
            }
            for seg in keep_segments
        ]

        rendered_duration = round(
            sum(seg["source_end"] - seg["source_start"] for seg in segments),
            6,
        )

        output_audio_source = str(config.get("output_audio_source") or "source_video")
        if output_audio_source not in _VALID_OUTPUT_AUDIO_SOURCES:
            allowed = ", ".join(sorted(_VALID_OUTPUT_AUDIO_SOURCES))
            raise ValueError(
                f"Invalid render_plan_compiler.output_audio_source '{output_audio_source}'. "
                f"Allowed: {allowed}."
            )
        output_audio = self._resolve_output_audio_payload(
            output_audio_source=output_audio_source,
            artifacts=artifacts,
            context=context,
        )

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
                "rendered_duration": rendered_duration,
            },
            "crop_plan": {
                "object_key": smooth_key,
                "crop_width": crop_width,
                "crop_height": crop_height,
                "keyframes": sorted_keyframes,
            },
            "segments": segments,
            "render_mode": output_render_mode,
            "output_audio": output_audio,
        }

        out_key = context.expected_output_key("render_plan")
        context.write_json(out_key, payload)
        return RunResponse(service_id=self.service_id, outputs={"render_plan": out_key})

    def _resolve_keep_segments(
        self,
        *,
        artifacts: dict[str, Any],
        context: ServiceContext,
        compiler_mode: str,
        duration: float,
    ) -> list[dict[str, float]]:
        if compiler_mode not in {"smooth_crop_with_cuts", "full_frame_with_cuts"}:
            return [{"source_start": 0.0, "source_end": duration}]

        cut_plan_key = self._artifact_key(artifacts, "cut_plan")
        if not isinstance(cut_plan_key, str) or not context.exists(cut_plan_key):
            raise ValueError(
                "cut-based compiler modes require the cut_plan artifact to be registered before render_plan_compiler"
            )
        cut_plan = context.read_json(cut_plan_key)
        keep_raw = cut_plan.get("keep_segments") or []
        if not isinstance(keep_raw, list) or not keep_raw:
            raise ValueError("cut_plan must include a non-empty keep_segments list")

        normalized: list[dict[str, float]] = []
        for entry in keep_raw:
            if not isinstance(entry, dict):
                continue
            start = max(0.0, float(entry.get("source_start") or 0.0))
            end = min(duration, float(entry.get("source_end") or 0.0))
            if end > start:
                normalized.append({"source_start": start, "source_end": end})
        if not normalized:
            raise ValueError("cut_plan keep_segments collapsed to an empty range")
        normalized.sort(key=lambda seg: seg["source_start"])
        return normalized

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for render_plan_compiler")
        return context.read_json(artifact_manifest_key)

    def _artifact_key(self, artifacts: dict[str, Any], artifact_name: str) -> Any:
        entry = artifacts.get(artifact_name) or {}
        if isinstance(entry, dict):
            return entry.get("object_key")
        return None

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "crop_representation": "keyframe_list",
            "audio_policy": "copy_if_possible_else_aac",
            "compiler_render_mode": "smooth_crop",
            "output_audio_source": "source_video",
        }
        defaults.update(context.request.config)

        crop_repr = defaults["crop_representation"]
        if crop_repr not in {"keyframe_list", "per_frame_list", "ffmpeg_expression_file"}:
            raise ValueError(f"Invalid crop_representation '{crop_repr}'")
        audio = defaults["audio_policy"]
        if audio not in {"copy_if_possible_else_aac", "aac_transcode"}:
            raise ValueError(f"Invalid audio_policy '{audio}'")
        compiler_mode = defaults["compiler_render_mode"]
        if compiler_mode not in _VALID_COMPILER_RENDER_MODES:
            raise ValueError(f"Invalid compiler_render_mode '{compiler_mode}'")
        return defaults

    def _resolve_output_audio_payload(
        self,
        *,
        output_audio_source: str,
        artifacts: dict[str, Any],
        context: ServiceContext,
    ) -> dict[str, Any]:
        if output_audio_source == "source_video":
            return {"source": "source_video", "object_key": None}
        enhanced_key = self._artifact_key(artifacts, "enhanced_audio")
        if not isinstance(enhanced_key, str) or not context.exists(enhanced_key):
            raise ValueError(
                "output_audio_source=enhanced_wav requires a registered enhanced_audio "
                "artifact that exists in storage before render_plan_compiler runs."
            )
        return {"source": "external_wav", "object_key": enhanced_key}

    def _synthetic_full_frame_smooth(
        self,
        metadata: dict[str, Any],
        duration: float,
        job_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        source_width = int(metadata.get("width") or 0)
        source_height = int(metadata.get("height") or 0)
        if source_width <= 0 or source_height <= 0:
            raise ValueError("metadata must include valid source dimensions for full_frame_with_cuts")

        crop_w = source_width - (source_width % 2)
        crop_h = source_height - (source_height % 2)
        target_resolution = job_manifest.get("target_output", {}).get(
            "resolution", {"width": 1080, "height": 1920}
        )
        tw = int(target_resolution.get("width") or 1080)
        th = int(target_resolution.get("height") or 1920)

        return {
            "crop_width": crop_w,
            "crop_height": crop_h,
            "source_resolution": {"width": source_width, "height": source_height},
            "target_resolution": {"width": tw, "height": th},
            "keyframes": [
                {"t": 0.0, "x": 0.0, "y": 0.0},
                {"t": round(float(duration), 6), "x": 0.0, "y": 0.0},
            ],
        }


def _slice_keyframes(
    keyframes: list[dict[str, Any]],
    *,
    seg_start: float,
    seg_end: float,
) -> list[dict[str, Any]]:
    """Project the smoothed crop keyframes onto a keep segment.

    Returns keyframes whose ``t`` is the *segment-relative* time; the absolute
    source-time can be reconstructed by adding ``seg_start`` back. Includes a
    synthesized boundary keyframe at ``t = 0`` (computed from the closest
    keyframe to the segment start) so the renderer always has a defined crop
    position at the very start of the segment.
    """
    if not keyframes:
        return []

    boundary_kf = _interpolated_keyframe_at(keyframes, seg_start)
    sliced: list[dict[str, Any]] = [{**boundary_kf, "t": 0.0, "source_t": round(seg_start, 6)}]

    for kf in keyframes:
        kf_time = float(kf.get("t") or 0.0)
        if kf_time <= seg_start or kf_time >= seg_end:
            continue
        sliced.append(
            {
                **kf,
                "t": round(kf_time - seg_start, 6),
                "source_t": round(kf_time, 6),
            }
        )

    end_kf = _interpolated_keyframe_at(keyframes, seg_end)
    sliced.append(
        {
            **end_kf,
            "t": round(seg_end - seg_start, 6),
            "source_t": round(seg_end, 6),
        }
    )
    return sliced


def _interpolated_keyframe_at(
    keyframes: list[dict[str, Any]],
    timestamp: float,
) -> dict[str, Any]:
    if not keyframes:
        return {"t": 0.0, "x": 0.0, "y": 0.0}

    first = keyframes[0]
    last = keyframes[-1]
    if timestamp <= float(first.get("t") or 0.0):
        return {**first, "t": float(first.get("t") or 0.0)}
    if timestamp >= float(last.get("t") or 0.0):
        return {**last, "t": float(last.get("t") or 0.0)}

    for index in range(len(keyframes) - 1):
        a = keyframes[index]
        b = keyframes[index + 1]
        a_t = float(a.get("t") or 0.0)
        b_t = float(b.get("t") or 0.0)
        if a_t <= timestamp <= b_t and b_t > a_t:
            ratio = (timestamp - a_t) / (b_t - a_t)
            return {
                "t": timestamp,
                "x": float(a.get("x") or 0.0) + ratio * (float(b.get("x") or 0.0) - float(a.get("x") or 0.0)),
                "y": float(a.get("y") or 0.0) + ratio * (float(b.get("y") or 0.0) - float(a.get("y") or 0.0)),
                "interpolated_from": [index, index + 1],
            }
    return {**last, "t": float(last.get("t") or 0.0)}
