"""Audio cut quality check service.

Validates that the rendered output stays in sync with the cut plan and checks
for basic A/V duration drift. Emits a JSON report plus warnings when thresholds
are exceeded.

Muxing final audio from ``enhanced_audio.wav`` (vs the source MP4 track) does
not change QC semantics: cuts still use source timeline seconds and the final
container is probed the same way.
"""

from __future__ import annotations

from typing import Any

from services.common.media import parse_fraction
from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


AUDIO_QC_SCHEMA_VERSION = "1.0.0"


class AudioCutQcService:
    service_id = "audio_cut_qc"

    def run(self, context: ServiceContext) -> RunResponse:
        config = self._config(context)
        artifact_manifest = self._artifact_manifest(context)

        final_key = self._artifact_key(artifact_manifest, "final_9x16")
        if not isinstance(final_key, str) or not context.exists(final_key):
            raise ValueError("artifact_manifest is missing final_9x16 for audio_cut_qc")

        final_bytes = context.read_bytes(final_key)
        probe = probe_video_bytes(final_bytes)

        warnings: list[ServiceWarning] = []
        format_duration = parse_fraction(
            (probe.get("format") or {}).get("duration")
            if isinstance(probe.get("format"), dict)
            else None
        )

        video_duration = _duration_for_stream(probe, "video") or format_duration
        audio_duration, audio_stream_present = _audio_duration(probe, format_duration)

        av_drift_ms: float | None = None
        if audio_stream_present and video_duration > 0:
            av_drift_ms = (audio_duration - video_duration) * 1000.0
            if abs(av_drift_ms) > float(config["max_av_drift_ms"]):
                warnings.append(
                    ServiceWarning(
                        code="AUDIO_QC_AV_DRIFT",
                        message=(
                            "Audio/video duration drift exceeds threshold: "
                            f"{av_drift_ms:.2f} ms (max {config['max_av_drift_ms']} ms)."
                        ),
                        step=self.service_id,
                    )
                )
        if not audio_stream_present:
            warnings.append(
                ServiceWarning(
                    code="AUDIO_QC_NO_AUDIO_STREAM",
                    message="Rendered output has no detectable audio stream.",
                    step=self.service_id,
                )
            )

        cut_plan_key = self._artifact_key(artifact_manifest, "cut_plan")
        keep_segments: list[dict[str, Any]] = []
        keep_total_seconds: float | None = None
        keep_drift_ms: float | None = None
        invalid_counts = {"invalid": 0, "overlap": 0, "out_of_bounds": 0}
        source_duration = 0.0

        if isinstance(cut_plan_key, str) and context.exists(cut_plan_key):
            cut_plan = context.read_json(cut_plan_key)
            keep_segments = cut_plan.get("keep_segments") or []
            if isinstance(keep_segments, list):
                keep_total_seconds = _sum_keep_segments(keep_segments)
                source_duration = float(cut_plan.get("source_duration_seconds") or 0.0)
                invalid_counts = _validate_keep_segments(
                    keep_segments,
                    source_duration=source_duration,
                    tolerance_seconds=float(config["segment_bounds_tolerance_seconds"]),
                )
            else:
                keep_segments = []
                keep_total_seconds = None

            if keep_total_seconds is not None and video_duration > 0:
                keep_drift_ms = (video_duration - keep_total_seconds) * 1000.0
                if abs(keep_drift_ms) > float(config["max_keep_drift_ms"]):
                    warnings.append(
                        ServiceWarning(
                            code="AUDIO_QC_KEEP_DRIFT",
                            message=(
                                "Rendered duration differs from cut_plan keep total by "
                                f"{keep_drift_ms:.2f} ms (max {config['max_keep_drift_ms']} ms)."
                            ),
                            step=self.service_id,
                        )
                    )
        else:
            warnings.append(
                ServiceWarning(
                    code="AUDIO_QC_CUT_PLAN_MISSING",
                    message="cut_plan artifact missing; skipping keep-segment checks.",
                    step=self.service_id,
                )
            )

        if invalid_counts["invalid"] > 0:
            warnings.append(
                ServiceWarning(
                    code="AUDIO_QC_KEEP_SEGMENT_INVALID",
                    message=f"{invalid_counts['invalid']} keep_segments have non-positive duration.",
                    step=self.service_id,
                )
            )
        if invalid_counts["overlap"] > 0:
            warnings.append(
                ServiceWarning(
                    code="AUDIO_QC_KEEP_SEGMENT_OVERLAP",
                    message=f"{invalid_counts['overlap']} keep_segments overlap previous ranges.",
                    step=self.service_id,
                )
            )
        if invalid_counts["out_of_bounds"] > 0:
            warnings.append(
                ServiceWarning(
                    code="AUDIO_QC_KEEP_SEGMENT_OUT_OF_BOUNDS",
                    message=(
                        f"{invalid_counts['out_of_bounds']} keep_segments exceed source duration "
                        f"({source_duration:.3f}s)."
                    ),
                    step=self.service_id,
                )
            )

        metrics = {
            "output_video_seconds": _round_or_none(video_duration),
            "output_audio_seconds": _round_or_none(audio_duration if audio_stream_present else None),
            "av_drift_ms": _round_or_none(av_drift_ms, digits=3),
            "expected_keep_seconds": _round_or_none(keep_total_seconds),
            "keep_drift_ms": _round_or_none(keep_drift_ms, digits=3),
            "keep_segment_count": len(keep_segments),
            "invalid_keep_segments": invalid_counts,
            "audio_stream_present": audio_stream_present,
        }

        report = {
            "schema_version": AUDIO_QC_SCHEMA_VERSION,
            "job_id": context.job_id,
            "final_output": {"object_key": final_key},
            "config_used": {
                "max_av_drift_ms": float(config["max_av_drift_ms"]),
                "max_keep_drift_ms": float(config["max_keep_drift_ms"]),
                "segment_bounds_tolerance_seconds": float(
                    config["segment_bounds_tolerance_seconds"]
                ),
            },
            "metrics": metrics,
        }

        output_key = context.expected_output_key("audio_qc_report")
        context.write_json(output_key, report)

        return RunResponse(
            service_id=self.service_id,
            outputs={"audio_qc_report": output_key},
            warnings=warnings,
            metrics=metrics,
        )

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.input_key("artifact_manifest")
        if not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for audio_cut_qc")
        return context.read_json(artifact_manifest_key)

    def _artifact_key(self, artifact_manifest: dict[str, Any], name: str) -> Any:
        entry = artifact_manifest.get("artifacts", {}).get(name) if artifact_manifest else None
        if isinstance(entry, dict):
            return entry.get("object_key")
        return None

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "max_av_drift_ms": 40.0,
            "max_keep_drift_ms": 80.0,
            "segment_bounds_tolerance_seconds": 0.02,
        }
        defaults.update(context.request.config)
        return defaults


def _duration_for_stream(probe: dict[str, Any], codec_type: str) -> float:
    streams = probe.get("streams") or []
    if not isinstance(streams, list):
        return 0.0
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        if stream.get("codec_type") != codec_type:
            continue
        duration = parse_fraction(stream.get("duration"))
        if duration > 0:
            return duration
    return 0.0


def _audio_duration(probe: dict[str, Any], fallback_duration: float) -> tuple[float, bool]:
    streams = probe.get("streams") or []
    if not isinstance(streams, list):
        return 0.0, False
    audio_stream_present = any(
        isinstance(stream, dict) and stream.get("codec_type") == "audio"
        for stream in streams
    )
    if not audio_stream_present:
        return 0.0, False
    duration = _duration_for_stream(probe, "audio")
    if duration <= 0 and fallback_duration > 0:
        duration = fallback_duration
    return duration, True


def _sum_keep_segments(keep_segments: list[dict[str, Any]]) -> float:
    total = 0.0
    for seg in keep_segments:
        if not isinstance(seg, dict):
            continue
        start = float(seg.get("source_start") or 0.0)
        end = float(seg.get("source_end") or 0.0)
        if end > start:
            total += (end - start)
    return round(total, 6)


def _validate_keep_segments(
    keep_segments: list[dict[str, Any]],
    *,
    source_duration: float,
    tolerance_seconds: float,
) -> dict[str, int]:
    counts = {"invalid": 0, "overlap": 0, "out_of_bounds": 0}
    prev_end: float | None = None
    for seg in keep_segments:
        if not isinstance(seg, dict):
            continue
        start = float(seg.get("source_start") or 0.0)
        end = float(seg.get("source_end") or 0.0)
        if end <= start:
            counts["invalid"] += 1
        if source_duration > 0:
            if start < -tolerance_seconds or end > (source_duration + tolerance_seconds):
                counts["out_of_bounds"] += 1
        if prev_end is not None and start < (prev_end - tolerance_seconds):
            counts["overlap"] += 1
        if end > (prev_end or 0.0):
            prev_end = end
    return counts


def _round_or_none(value: float | None, *, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
