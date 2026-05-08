"""Phase 1 reframe planning service implementation."""

from __future__ import annotations

from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


class ReframePlanningService:
    service_id = "reframe_planning"

    def run(self, context: ServiceContext) -> RunResponse:
        artifact_manifest = self._artifact_manifest(context)
        metadata_key = artifact_manifest.get("artifacts", {}).get("metadata", {}).get("object_key")
        tracks_key = artifact_manifest.get("artifacts", {}).get("body_tracks_interpolated", {}).get("object_key")
        if not isinstance(metadata_key, str) or not context.exists(metadata_key):
            raise ValueError("artifact_manifest is missing metadata for reframe planning")
        if not isinstance(tracks_key, str) or not context.exists(tracks_key):
            raise ValueError("artifact_manifest is missing body_tracks_interpolated for reframe planning")

        metadata = context.read_json(metadata_key)
        track_payload = context.read_json(tracks_key)
        tracks = track_payload.get("tracks", [])
        if not isinstance(tracks, list) or not tracks:
            raise ValueError("body_tracks_interpolated artifact must contain a non-empty tracks list")

        config = self._config(context)
        crop = metadata.get("target_crop") or {}
        crop_width = int(crop.get("width") or 0)
        crop_height = int(crop.get("height") or 0)
        source_width = int(metadata.get("width") or 0)
        source_height = int(metadata.get("height") or 0)
        if crop_width <= 0 or crop_height <= 0 or source_width <= 0 or source_height <= 0:
            raise ValueError("metadata is missing crop or source dimensions for reframe planning")

        keyframes = build_reframe_keyframes(
            tracks=tracks,
            crop_width=crop_width,
            crop_height=crop_height,
            source_width=source_width,
            source_height=source_height,
            framing_mode=str(config["framing_mode"]),
            clamp_to_source=bool(config["clamp_to_source"]),
        )

        payload = {
            "job_id": context.job_id,
            "framing_mode": config["framing_mode"],
            "clamp_to_source": bool(config["clamp_to_source"]),
            "crop_width": crop_width,
            "crop_height": crop_height,
            "source_resolution": {"width": source_width, "height": source_height},
            "target_resolution": metadata.get("target_resolution"),
            "keyframes": keyframes,
        }

        output_key = context.expected_output_key("reframe_plan_raw")
        context.write_json(output_key, payload)
        return RunResponse(service_id=self.service_id, outputs={"reframe_plan_raw": output_key})

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for reframe planning")
        return context.read_json(artifact_manifest_key)

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults = {
            "framing_mode": "center_subject",
            "clamp_to_source": True,
        }
        defaults.update(context.request.config)
        return defaults


def build_reframe_keyframes(
    *,
    tracks: list[dict[str, Any]],
    crop_width: int,
    crop_height: int,
    source_width: int,
    source_height: int,
    framing_mode: str,
    clamp_to_source: bool,
) -> list[dict[str, Any]]:
    del framing_mode
    keyframes: list[dict[str, Any]] = []
    max_x = max(0, source_width - crop_width)
    max_y = max(0, source_height - crop_height)

    for track in tracks:
        center = track.get("center") or {}
        center_x = float(center.get("x") or 0.0)
        target_x = center_x - (crop_width / 2.0)
        if clamp_to_source:
            target_x = min(max(0.0, target_x), float(max_x))
        target_y = 0.0
        if clamp_to_source:
            target_y = min(max(0.0, target_y), float(max_y))

        keyframes.append(
            {
                "frame_index": int(track.get("frame_index") or 0),
                "t": round(float(track.get("t") or 0.0), 6),
                "x": round(target_x, 2),
                "y": round(target_y, 2),
                "center_x": round(center_x, 2),
                "confidence": round(float(track.get("confidence") or 0.0), 4),
                "source": track.get("source", "unknown"),
                "interpolated": bool(track.get("interpolated")),
            }
        )

    return keyframes
