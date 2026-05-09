"""Phase 1 track interpolation service implementation."""

from __future__ import annotations

from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


class TrackInterpolationService:
    service_id = "track_interpolation"

    def run(self, context: ServiceContext) -> RunResponse:
        artifact_manifest = self._artifact_manifest(context)
        raw_tracks_key = artifact_manifest.get("artifacts", {}).get("body_tracks_raw", {}).get("object_key")
        if not isinstance(raw_tracks_key, str) or not context.exists(raw_tracks_key):
            raise ValueError("artifact_manifest is missing body_tracks_raw for track interpolation")

        raw_payload = context.read_json(raw_tracks_key)
        raw_tracks = raw_payload.get("tracks", [])
        if not isinstance(raw_tracks, list) or not raw_tracks:
            raise ValueError("body_tracks_raw artifact must contain a non-empty tracks list")

        config = self._config(context)
        interpolated_tracks, stats = interpolate_tracks(
            raw_tracks=raw_tracks,
            max_gap_fill_seconds=float(config["max_gap_fill_seconds"]),
            max_center_jump_per_second=float(config["max_center_jump_per_second"]),
            missing_strategy=str(config["missing_strategy"]),
            source_center=_source_center(raw_payload),
        )

        output_payload = {
            "job_id": context.job_id,
            "coordinate_space": raw_payload.get("coordinate_space", "source"),
            "source_resolution": raw_payload.get("source_resolution"),
            "proxy_resolution": raw_payload.get("proxy_resolution"),
            "missing_strategy": config["missing_strategy"],
            "interpolation_stats": stats,
            "tracks": interpolated_tracks,
        }

        output_key = context.expected_output_key("body_tracks_interpolated")
        context.write_json(output_key, output_payload)

        warnings: list[ServiceWarning] = []
        if stats["filled_missing_count"] > 0:
            warnings.append(
                ServiceWarning(
                    code="TRACK_INTERPOLATION_FILLED_GAPS",
                    message=f"Track interpolation filled {stats['filled_missing_count']} missing frames.",
                    step=self.service_id,
                )
            )
        if stats["outlier_adjustments"] > 0:
            warnings.append(
                ServiceWarning(
                    code="TRACK_INTERPOLATION_OUTLIERS_ADJUSTED",
                    message=f"Track interpolation adjusted {stats['outlier_adjustments']} outlier frames.",
                    step=self.service_id,
                )
            )

        return RunResponse(
            service_id=self.service_id,
            outputs={"body_tracks_interpolated": output_key},
            warnings=warnings,
        )

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for track interpolation")
        return context.read_json(artifact_manifest_key)

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults = {
            "max_gap_fill_seconds": 1.0,
            "max_center_jump_per_second": 600.0,
            "missing_strategy": "hold_then_center",
        }
        defaults.update(context.request.config)
        return defaults


def interpolate_tracks(
    *,
    raw_tracks: list[dict[str, Any]],
    max_gap_fill_seconds: float,
    max_center_jump_per_second: float,
    missing_strategy: str,
    source_center: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    tracks = [dict(track) for track in raw_tracks]
    filled_missing_count = 0
    outlier_adjustments = 0

    index = 0
    while index < len(tracks):
        if not bool(tracks[index].get("missing")):
            index += 1
            continue

        gap_start = index
        while index < len(tracks) and bool(tracks[index].get("missing")):
            index += 1
        gap_end = index - 1

        previous_index = _previous_valid_index(tracks, gap_start - 1)
        next_index = _next_valid_index(tracks, gap_end + 1)
        if previous_index is None or next_index is None:
            _apply_missing_strategy(
                tracks=tracks,
                start=gap_start,
                end=gap_end,
                previous_index=previous_index,
                source_center=source_center,
                missing_strategy=missing_strategy,
            )
            continue

        previous_track = tracks[previous_index]
        next_track = tracks[next_index]
        gap_duration = float(next_track.get("t", 0.0)) - float(previous_track.get("t", 0.0))
        if gap_duration <= max_gap_fill_seconds:
            for fill_index in range(gap_start, gap_end + 1):
                ratio = (
                    (float(tracks[fill_index].get("t", 0.0)) - float(previous_track.get("t", 0.0)))
                    / gap_duration
                    if gap_duration > 0
                    else 0.0
                )
                tracks[fill_index] = _interpolate_track(previous_track, next_track, tracks[fill_index], ratio)
                filled_missing_count += 1
        else:
            _apply_missing_strategy(
                tracks=tracks,
                start=gap_start,
                end=gap_end,
                previous_index=previous_index,
                source_center=source_center,
                missing_strategy=missing_strategy,
            )

    last_valid_index: int | None = None
    for index, track in enumerate(tracks):
        if bool(track.get("missing")):
            continue
        if last_valid_index is None:
            last_valid_index = index
            continue
        previous_track = tracks[last_valid_index]
        dt = float(track.get("t", 0.0)) - float(previous_track.get("t", 0.0))
        if dt <= 0:
            last_valid_index = index
            continue
        distance = _center_distance(previous_track, track)
        speed = distance / dt
        if speed > max_center_jump_per_second:
            if _is_confirmed_transition(
                tracks=tracks,
                current_index=index,
                current_track=track,
                max_center_jump_per_second=max_center_jump_per_second,
            ):
                last_valid_index = index
                continue
            tracks[index] = _clone_track(previous_track, track)
            tracks[index]["source"] = "outlier_adjusted"
            tracks[index]["interpolated"] = True
            outlier_adjustments += 1
        last_valid_index = index

    return tracks, {
        "filled_missing_count": filled_missing_count,
        "outlier_adjustments": outlier_adjustments,
    }


def _source_center(raw_payload: dict[str, Any]) -> dict[str, float]:
    resolution = raw_payload.get("source_resolution") or {}
    width = float(resolution.get("width") or 0.0)
    height = float(resolution.get("height") or 0.0)
    if width <= 0 or height <= 0:
        width = 1920.0
        height = 1080.0
    return {"x": width / 2.0, "y": height / 2.0}


def _previous_valid_index(tracks: list[dict[str, Any]], start: int) -> int | None:
    for index in range(start, -1, -1):
        if not bool(tracks[index].get("missing")):
            return index
    return None


def _next_valid_index(tracks: list[dict[str, Any]], start: int) -> int | None:
    for index in range(start, len(tracks)):
        if not bool(tracks[index].get("missing")):
            return index
    return None


def _is_confirmed_transition(
    *,
    tracks: list[dict[str, Any]],
    current_index: int,
    current_track: dict[str, Any],
    max_center_jump_per_second: float,
) -> bool:
    next_index = _next_valid_index(tracks, current_index + 1)
    if next_index is None:
        return False

    next_track = tracks[next_index]
    dt = float(next_track.get("t", 0.0)) - float(current_track.get("t", 0.0))
    if dt <= 0:
        return False

    distance = _center_distance(current_track, next_track)
    speed = distance / dt
    return speed <= max_center_jump_per_second


def _interpolate_track(
    previous_track: dict[str, Any],
    next_track: dict[str, Any],
    current_track: dict[str, Any],
    ratio: float,
) -> dict[str, Any]:
    clamped_ratio = max(0.0, min(1.0, ratio))
    interpolated = dict(current_track)
    interpolated["center"] = {
        "x": round(_lerp(previous_track["center"]["x"], next_track["center"]["x"], clamped_ratio), 2),
        "y": round(_lerp(previous_track["center"]["y"], next_track["center"]["y"], clamped_ratio), 2),
    }
    interpolated["bbox"] = {
        key: round(_lerp(previous_track["bbox"][key], next_track["bbox"][key], clamped_ratio), 2)
        for key in ("x", "y", "w", "h")
    }
    interpolated["confidence"] = round(
        _lerp(float(previous_track.get("confidence", 0.0)), float(next_track.get("confidence", 0.0)), clamped_ratio),
        4,
    )
    interpolated["missing"] = False
    interpolated["interpolated"] = True
    interpolated["source"] = "linear_interpolation"
    return interpolated


def _apply_missing_strategy(
    *,
    tracks: list[dict[str, Any]],
    start: int,
    end: int,
    previous_index: int | None,
    source_center: dict[str, float],
    missing_strategy: str,
) -> None:
    hold_track = tracks[previous_index] if previous_index is not None else None
    for index in range(start, end + 1):
        if missing_strategy == "hold_then_center" and hold_track is not None:
            tracks[index] = _clone_track(hold_track, tracks[index])
            tracks[index]["source"] = "hold_previous"
        else:
            tracks[index] = _center_fallback_track(tracks[index], source_center)
            tracks[index]["source"] = "center_fallback"
        tracks[index]["missing"] = False
        tracks[index]["interpolated"] = True


def _clone_track(source_track: dict[str, Any], target_track: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(target_track)
    cloned["center"] = dict(source_track["center"])
    cloned["bbox"] = dict(source_track["bbox"])
    cloned["confidence"] = source_track.get("confidence", 0.0)
    return cloned


def _center_fallback_track(track: dict[str, Any], source_center: dict[str, float]) -> dict[str, Any]:
    fallback = dict(track)
    bbox = fallback.get("bbox") or {}
    width = float(bbox.get("w") or 0.0)
    height = float(bbox.get("h") or 0.0)
    fallback["center"] = {"x": round(source_center["x"], 2), "y": round(source_center["y"], 2)}
    fallback["bbox"] = {
        "x": round(source_center["x"] - (width / 2.0), 2),
        "y": round(source_center["y"] - (height / 2.0), 2),
        "w": width,
        "h": height,
    }
    fallback["confidence"] = 0.0
    return fallback


def _center_distance(previous_track: dict[str, Any], current_track: dict[str, Any]) -> float:
    prev_center = previous_track.get("center") or {}
    curr_center = current_track.get("center") or {}
    dx = float(curr_center.get("x") or 0.0) - float(prev_center.get("x") or 0.0)
    dy = float(curr_center.get("y") or 0.0) - float(prev_center.get("y") or 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _lerp(start: float, end: float, ratio: float) -> float:
    return start + ((end - start) * ratio)
