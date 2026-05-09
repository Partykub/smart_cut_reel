"""Phase 1 easing and smoothing service implementation."""

from __future__ import annotations

from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.easing_smoothing.easing import EasingName
from services.easing_smoothing.easing import interpolate


class EasingSmoothingService:
    service_id = "easing_smoothing"

    def run(self, context: ServiceContext) -> RunResponse:
        artifact_manifest = self._artifact_manifest(context)
        reframe_plan_key = artifact_manifest.get("artifacts", {}).get("reframe_plan_raw", {}).get("object_key")
        if not isinstance(reframe_plan_key, str) or not context.exists(reframe_plan_key):
            raise ValueError("artifact_manifest is missing reframe_plan_raw for easing_smoothing")

        raw_plan = context.read_json(reframe_plan_key)
        keyframes = raw_plan.get("keyframes", [])
        if not isinstance(keyframes, list) or not keyframes:
            raise ValueError("reframe_plan_raw artifact must contain a non-empty keyframes list")

        config = self._config(context)
        smoothed_keyframes = smooth_keyframes(
            keyframes=keyframes,
            crop_width=int(raw_plan.get("crop_width") or 0),
            source_width=int((raw_plan.get("source_resolution") or {}).get("width") or 0),
            smoothing_strength=float(config["smoothing_strength"]),
            max_velocity_px_per_second=float(config["max_velocity_px_per_second"]),
            max_acceleration_px_per_second2=float(config["max_acceleration_px_per_second2"]),
            dead_zone_px=float(config["dead_zone_px"]),
            easing=str(config["easing"]),
        )

        payload = {
            "job_id": context.job_id,
            "crop_width": raw_plan.get("crop_width"),
            "crop_height": raw_plan.get("crop_height"),
            "source_resolution": raw_plan.get("source_resolution"),
            "target_resolution": raw_plan.get("target_resolution"),
            "smoothing_method": config["smoothing_method"],
            "smoothing_strength": float(config["smoothing_strength"]),
            "max_velocity_px_per_second": float(config["max_velocity_px_per_second"]),
            "max_acceleration_px_per_second2": float(config["max_acceleration_px_per_second2"]),
            "dead_zone_px": float(config["dead_zone_px"]),
            "easing": config["easing"],
            "keyframes": smoothed_keyframes,
        }

        output_key = context.expected_output_key("reframe_plan_smooth")
        context.write_json(output_key, payload)
        return RunResponse(service_id=self.service_id, outputs={"reframe_plan_smooth": output_key})

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for easing_smoothing")
        return context.read_json(artifact_manifest_key)

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults = {
            "smoothing_method": "exponential",
            "smoothing_strength": 0.82,
            "max_velocity_px_per_second": 700.0,
            "max_acceleration_px_per_second2": 1600.0,
            "easing": "easeInOutCubic",
            "dead_zone_px": 80.0,
        }
        defaults.update(context.request.config)
        return defaults


def smooth_keyframes(
    *,
    keyframes: list[dict[str, Any]],
    crop_width: int,
    source_width: int,
    smoothing_strength: float,
    max_velocity_px_per_second: float,
    max_acceleration_px_per_second2: float,
    dead_zone_px: float,
    easing: str,
) -> list[dict[str, Any]]:
    if crop_width <= 0 or source_width <= 0:
        raise ValueError("crop_width and source_width must be greater than zero")
    if easing not in {"linear", "easeOutCubic", "easeInOutCubic", "easeInOutSine"}:
        raise ValueError(f"Unknown easing '{easing}'")

    max_x = max(0.0, float(source_width - crop_width))
    alpha = max(0.0, min(1.0, 1.0 - float(smoothing_strength)))
    eased_alpha = interpolate(0.0, 1.0, alpha, easing=easing) if alpha > 0 else 0.0
    effective_dead_zone_px = min(max(0.0, dead_zone_px), crop_width * 0.2)

    smoothed: list[dict[str, Any]] = []
    last_x: float | None = None
    last_velocity = 0.0
    for frame in keyframes:
        frame_copy = dict(frame)
        target_x = float(frame.get("x") or 0.0)
        target_y = float(frame.get("y") or 0.0)
        timestamp = float(frame.get("t") or 0.0)
        current_index = len(smoothed)

        if last_x is None:
            smoothed_x = target_x
        else:
            delta = target_x - last_x
            if _should_snap_to_target(
                keyframes=keyframes,
                index=current_index,
                last_x=last_x,
                target_x=target_x,
                crop_width=crop_width,
                effective_dead_zone_px=effective_dead_zone_px,
            ):
                smoothed_x = target_x
                last_velocity = 0.0
            elif abs(delta) <= effective_dead_zone_px:
                smoothed_x = last_x
            else:
                proposed_x = last_x + (delta * eased_alpha)
                dt = max(1e-6, timestamp - float(smoothed[-1].get("t") or 0.0))
                desired_velocity = (proposed_x - last_x) / dt
                velocity_limit = _clamp(desired_velocity, -max_velocity_px_per_second, max_velocity_px_per_second)
                acceleration = (velocity_limit - last_velocity) / dt
                if acceleration > max_acceleration_px_per_second2:
                    velocity_limit = last_velocity + (max_acceleration_px_per_second2 * dt)
                elif acceleration < -max_acceleration_px_per_second2:
                    velocity_limit = last_velocity - (max_acceleration_px_per_second2 * dt)
                smoothed_x = last_x + (velocity_limit * dt)
                last_velocity = velocity_limit

        smoothed_x = min(max(0.0, smoothed_x), max_x)
        frame_copy["raw_x"] = round(target_x, 2)
        frame_copy["x"] = round(smoothed_x, 2)
        frame_copy["y"] = round(target_y, 2)
        frame_copy["smoothed"] = True
        smoothed.append(frame_copy)
        last_x = smoothed_x

    return smoothed


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _should_snap_to_target(
    *,
    keyframes: list[dict[str, Any]],
    index: int,
    last_x: float,
    target_x: float,
    crop_width: int,
    effective_dead_zone_px: float,
) -> bool:
    jump_size = abs(target_x - last_x)
    if jump_size < max(effective_dead_zone_px * 2.0, crop_width * 0.45):
        return False

    if index + 1 >= len(keyframes):
        return False

    next_target_x = float(keyframes[index + 1].get("x") or 0.0)
    confirmation_window = max(effective_dead_zone_px, crop_width * 0.15)
    return abs(next_target_x - target_x) <= confirmation_window
