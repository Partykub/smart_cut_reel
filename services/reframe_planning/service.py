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
            face_hint_strength=float(config["face_hint_strength"]),
            face_hint_max_ratio=float(config["face_hint_max_ratio"]),
            face_hint_dead_zone_px=float(config["face_hint_dead_zone_px"]),
            face_hint_smoothing_strength=float(config["face_hint_smoothing_strength"]),
            stable_zone_trigger_ratio=float(config["stable_zone_trigger_ratio"]),
            stable_zone_release_ratio=float(config["stable_zone_release_ratio"]),
            stable_zone_offset_ratio=float(config["stable_zone_offset_ratio"]),
            stable_hold_seconds=float(config["stable_hold_seconds"]),
        )

        payload = {
            "job_id": context.job_id,
            "framing_mode": config["framing_mode"],
            "clamp_to_source": bool(config["clamp_to_source"]),
            "crop_width": crop_width,
            "crop_height": crop_height,
            "source_resolution": {"width": source_width, "height": source_height},
            "target_resolution": metadata.get("target_resolution"),
            "face_hint_strength": float(config["face_hint_strength"]),
            "face_hint_max_ratio": float(config["face_hint_max_ratio"]),
            "face_hint_dead_zone_px": float(config["face_hint_dead_zone_px"]),
            "face_hint_smoothing_strength": float(config["face_hint_smoothing_strength"]),
            "stable_zone_trigger_ratio": float(config["stable_zone_trigger_ratio"]),
            "stable_zone_release_ratio": float(config["stable_zone_release_ratio"]),
            "stable_zone_offset_ratio": float(config["stable_zone_offset_ratio"]),
            "stable_hold_seconds": float(config["stable_hold_seconds"]),
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
            "face_hint_strength": 0.18,
            "face_hint_max_ratio": 0.1,
            "face_hint_dead_zone_px": 48.0,
            "face_hint_smoothing_strength": 0.9,
            "stable_zone_trigger_ratio": 0.12,
            "stable_zone_release_ratio": 0.05,
            "stable_zone_offset_ratio": 0.35,
            "stable_hold_seconds": 0.75,
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
    face_hint_strength: float,
    face_hint_max_ratio: float,
    face_hint_dead_zone_px: float,
    face_hint_smoothing_strength: float,
    stable_zone_trigger_ratio: float,
    stable_zone_release_ratio: float,
    stable_zone_offset_ratio: float,
    stable_hold_seconds: float,
) -> list[dict[str, Any]]:
    del framing_mode
    del face_hint_strength
    del face_hint_max_ratio
    del face_hint_smoothing_strength
    del stable_zone_trigger_ratio
    del stable_zone_release_ratio
    del stable_zone_offset_ratio
    del stable_hold_seconds

    keyframes: list[dict[str, Any]] = []
    max_x = max(0, source_width - crop_width)
    max_y = max(0, source_height - crop_height)
    last_anchor_center_x: float | None = None

    for track in tracks:
        raw_center_x = _face_anchor_center_x(track)
        if last_anchor_center_x is None:
            center_x = raw_center_x
        elif abs(raw_center_x - last_anchor_center_x) <= max(0.0, face_hint_dead_zone_px):
            center_x = last_anchor_center_x
        else:
            center_x = raw_center_x
        last_anchor_center_x = center_x
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
                "anchor_center_x": round(raw_center_x, 2),
                "face_offset_x": 0.0,
                "face_offset_smoothed_x": 0.0,
                "stable_zone": "face_anchor",
                "confidence": round(float(track.get("confidence") or 0.0), 4),
                "source": track.get("source", "unknown"),
                "interpolated": bool(track.get("interpolated")),
            }
        )

    return keyframes


def _face_anchor_center_x(track: dict[str, Any]) -> float:
    center = track.get("center") or {}
    return float(center.get("x") or 0.0)
