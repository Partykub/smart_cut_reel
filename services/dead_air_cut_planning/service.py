"""Phase 2 / Phase 3 dead air cut planning service.

Reads ``vad_segments.json`` and the source duration from ``metadata.json`` and
emits ``cut_plan.json`` — a list of ``keep_segments`` describing which time
ranges of the source video should be retained.

Phase 2 cuts long silences (> ``silence_threshold_seconds``).

Phase 3 additionally cuts filler-word occurrences (e.g. "เอ่อ", "um") sourced
from ``transcript.json``. The transcript artifact is optional: when missing or
when ``enabled_features.remove_filler_words`` is false, the planner behaves
identically to Phase 2.

When ``enabled_features.remove_dead_air`` is ``false`` (or missing) the service
still runs and emits an identity plan covering the whole clip, so the renderer
can fall back to the Phase 1 single-segment behavior without conditional
pipeline branches.
"""

from __future__ import annotations

from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


CUT_PLAN_SCHEMA_VERSION = "3.0.0"


class DeadAirCutPlanningService:
    service_id = "dead_air_cut_planning"

    def run(self, context: ServiceContext) -> RunResponse:
        artifact_manifest = self._artifact_manifest(context)
        metadata_key = self._artifact_key(artifact_manifest, "metadata")
        if not isinstance(metadata_key, str) or not context.exists(metadata_key):
            raise ValueError("artifact_manifest is missing metadata for dead_air_cut_planning")
        metadata = context.read_json(metadata_key)
        source_duration = float(metadata.get("duration") or 0.0)
        if source_duration <= 0:
            raise ValueError("metadata must include positive duration")

        job_manifest = context.read_json(context.input_key("job_manifest"))
        feature_enabled = bool(
            job_manifest.get("enabled_features", {}).get("remove_dead_air", False)
        )

        config = self._config(context)

        warnings: list[ServiceWarning] = []
        if not feature_enabled:
            keep_segments = [{"source_start": 0.0, "source_end": round(source_duration, 6)}]
            payload = self._payload(
                context=context,
                feature_enabled=False,
                config=config,
                source_duration=source_duration,
                keep_segments=keep_segments,
                warnings_in_plan=[],
            )
            output_key = context.expected_output_key("cut_plan")
            context.write_json(output_key, payload)
            return RunResponse(
                service_id=self.service_id,
                outputs={"cut_plan": output_key},
                warnings=warnings,
            )

        vad_key = self._artifact_key(artifact_manifest, "vad_segments")
        if not isinstance(vad_key, str) or not context.exists(vad_key):
            raise ValueError("artifact_manifest is missing vad_segments for dead_air_cut_planning")
        vad_payload = context.read_json(vad_key)
        vad_segments = vad_payload.get("segments") or []
        if not isinstance(vad_segments, list) or not vad_segments:
            raise ValueError("vad_segments artifact must contain a non-empty segments list")

        keep_segments, plan_warnings = _build_keep_segments(
            vad_segments=vad_segments,
            source_duration=source_duration,
            silence_threshold=float(config["silence_threshold_seconds"]),
            keep_padding_before=float(config["keep_padding_before"]),
            keep_padding_after=float(config["keep_padding_after"]),
            min_keep_segment_seconds=float(config["min_keep_segment_seconds"]),
        )
        kept_after_silence = sum(
            seg["source_end"] - seg["source_start"] for seg in keep_segments
        )

        filler_intervals: list[tuple[float, float]] = []
        if bool(
            job_manifest.get("enabled_features", {}).get("remove_filler_words", False)
        ):
            transcript_payload = self._read_transcript(context, artifact_manifest)
            if transcript_payload is not None:
                filler_intervals = _filler_intervals_from_transcript(
                    transcript_payload,
                    padding_before=float(config["filler_padding_before"]),
                    padding_after=float(config["filler_padding_after"]),
                    source_duration=source_duration,
                )
            else:
                warnings.append(
                    ServiceWarning(
                        code="FILLER_CUT_TRANSCRIPT_MISSING",
                        message=(
                            "remove_filler_words is enabled but transcript artifact is missing. "
                            "Filler word cut skipped for this job."
                        ),
                        step=self.service_id,
                    )
                )

        if filler_intervals:
            keep_segments = _subtract_intervals_from_keep_segments(
                keep_segments=keep_segments,
                cut_intervals=_merge_close_intervals(
                    filler_intervals,
                    merge_within=float(config["merge_adjacent_cuts_within_seconds"]),
                ),
            )

        keep_segments = _drop_short_keep_segments(
            keep_segments=keep_segments,
            min_keep_segment_seconds=float(config["min_keep_segment_seconds"]),
            plan_warnings=plan_warnings,
            warning_code="DEAD_AIR_DROPPED_SHORT_AFTER_FILLER_CUT",
        )

        kept_after_filler = sum(
            seg["source_end"] - seg["source_start"] for seg in keep_segments
        )
        removed_filler_seconds = max(0.0, kept_after_silence - kept_after_filler)
        filler_word_count = len(filler_intervals)

        if not keep_segments:
            warnings.append(
                ServiceWarning(
                    code="CUT_PLAN_EMPTY_FALLBACK_IDENTITY",
                    message=(
                        "Dead air planning produced zero keep segments. "
                        "Falling back to identity (entire clip kept)."
                    ),
                    step=self.service_id,
                )
            )
            keep_segments = [{"source_start": 0.0, "source_end": round(source_duration, 6)}]

        payload = self._payload(
            context=context,
            feature_enabled=True,
            config=config,
            source_duration=source_duration,
            keep_segments=keep_segments,
            warnings_in_plan=plan_warnings,
            removed_filler_seconds=removed_filler_seconds,
            filler_word_count=filler_word_count,
        )
        output_key = context.expected_output_key("cut_plan")
        context.write_json(output_key, payload)
        return RunResponse(
            service_id=self.service_id,
            outputs={"cut_plan": output_key},
            warnings=warnings,
        )

    def _payload(
        self,
        *,
        context: ServiceContext,
        feature_enabled: bool,
        config: dict[str, Any],
        source_duration: float,
        keep_segments: list[dict[str, float]],
        warnings_in_plan: list[dict[str, Any]],
        removed_filler_seconds: float = 0.0,
        filler_word_count: int = 0,
    ) -> dict[str, Any]:
        kept_total = sum(seg["source_end"] - seg["source_start"] for seg in keep_segments)
        removed_total = max(0.0, source_duration - kept_total)
        removed_silence_seconds = max(0.0, removed_total - removed_filler_seconds)
        cut_count = max(0, len(keep_segments) - 1)
        compression_ratio = (kept_total / source_duration) if source_duration > 0 else 1.0

        return {
            "schema_version": CUT_PLAN_SCHEMA_VERSION,
            "job_id": context.job_id,
            "feature_enabled": feature_enabled,
            "source_duration_seconds": round(source_duration, 6),
            "config_used": {
                "silence_threshold_seconds": float(config["silence_threshold_seconds"]),
                "keep_padding_before": float(config["keep_padding_before"]),
                "keep_padding_after": float(config["keep_padding_after"]),
                "min_keep_segment_seconds": float(config["min_keep_segment_seconds"]),
                "filler_padding_before": float(config["filler_padding_before"]),
                "filler_padding_after": float(config["filler_padding_after"]),
                "merge_adjacent_cuts_within_seconds": float(
                    config["merge_adjacent_cuts_within_seconds"]
                ),
            },
            "keep_segments": [
                {
                    "source_start": round(float(seg["source_start"]), 6),
                    "source_end": round(float(seg["source_end"]), 6),
                }
                for seg in keep_segments
            ],
            "metrics": {
                "total_kept_seconds": round(kept_total, 6),
                "total_removed_seconds": round(removed_total, 6),
                "removed_silence_seconds": round(removed_silence_seconds, 6),
                "removed_filler_seconds": round(removed_filler_seconds, 6),
                "filler_word_count": filler_word_count,
                "cut_count": cut_count,
                "compression_ratio": round(compression_ratio, 6),
            },
            "plan_warnings": warnings_in_plan,
        }

    def _read_transcript(
        self,
        context: ServiceContext,
        artifact_manifest: dict[str, Any],
    ) -> dict[str, Any] | None:
        transcript_key = self._artifact_key(artifact_manifest, "transcript")
        if isinstance(transcript_key, str) and context.exists(transcript_key):
            return context.read_json(transcript_key)
        try:
            inline_key = context.input_key("transcript")
        except ValueError:
            return None
        if context.exists(inline_key):
            return context.read_json(inline_key)
        return None

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for dead_air_cut_planning")
        return context.read_json(artifact_manifest_key)

    def _artifact_key(self, artifact_manifest: dict[str, Any], artifact_name: str) -> Any:
        entry = artifact_manifest.get("artifacts", {}).get(artifact_name) or {}
        if isinstance(entry, dict):
            return entry.get("object_key")
        return None

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "silence_threshold_seconds": 0.8,
            "keep_padding_before": 0.15,
            "keep_padding_after": 0.2,
            "min_keep_segment_seconds": 0.5,
            "filler_padding_before": 0.05,
            "filler_padding_after": 0.05,
            "merge_adjacent_cuts_within_seconds": 0.1,
        }
        defaults.update(context.request.config)

        for key in (
            "silence_threshold_seconds",
            "keep_padding_before",
            "keep_padding_after",
            "min_keep_segment_seconds",
            "filler_padding_before",
            "filler_padding_after",
            "merge_adjacent_cuts_within_seconds",
        ):
            if float(defaults[key]) < 0.0:
                raise ValueError(f"{key} must be greater than or equal to zero")

        return defaults


def _build_keep_segments(
    *,
    vad_segments: list[dict[str, Any]],
    source_duration: float,
    silence_threshold: float,
    keep_padding_before: float,
    keep_padding_after: float,
    min_keep_segment_seconds: float,
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    """Convert a VAD segment list into a sorted, padded ``keep_segments`` list.

    Algorithm:
    1. Mark every silence segment whose duration ``>= silence_threshold`` as a
       ``cut_silence``; shorter silences are left intact and absorbed into
       neighboring keep windows.
    2. Project all non-cut spans onto the source timeline as initial keep
       windows.
    3. Pad each keep window outward by ``keep_padding_before`` /
       ``keep_padding_after`` seconds (clamped to ``[0, source_duration]``).
    4. Merge any keep windows that now overlap.
    5. Drop keep windows shorter than ``min_keep_segment_seconds`` (and emit a
       plan-level warning summarizing how much time was discarded).
    """
    plan_warnings: list[dict[str, Any]] = []
    sorted_segments = sorted(vad_segments, key=lambda seg: float(seg.get("start") or 0.0))

    cut_intervals: list[tuple[float, float]] = []
    for segment in sorted_segments:
        seg_type = str(segment.get("type") or "")
        seg_start = max(0.0, float(segment.get("start") or 0.0))
        seg_end = min(source_duration, float(segment.get("end") or 0.0))
        if seg_end <= seg_start:
            continue
        if seg_type != "silence":
            continue
        if (seg_end - seg_start) >= silence_threshold:
            cut_intervals.append((seg_start, seg_end))

    keep_windows: list[tuple[float, float]] = []
    cursor = 0.0
    for cut_start, cut_end in cut_intervals:
        if cut_start > cursor:
            keep_windows.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < source_duration:
        keep_windows.append((cursor, source_duration))

    padded: list[tuple[float, float]] = []
    for start, end in keep_windows:
        padded_start = max(0.0, start - keep_padding_before)
        padded_end = min(source_duration, end + keep_padding_after)
        if padded_end > padded_start:
            padded.append((padded_start, padded_end))

    merged: list[tuple[float, float]] = []
    for start, end in sorted(padded, key=lambda window: window[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    pruned: list[tuple[float, float]] = []
    discarded_total = 0.0
    discarded_count = 0
    for start, end in merged:
        duration = end - start
        if duration < min_keep_segment_seconds:
            discarded_total += duration
            discarded_count += 1
            continue
        pruned.append((start, end))

    if discarded_count > 0:
        plan_warnings.append(
            {
                "code": "DEAD_AIR_DROPPED_SHORT_KEEP_SEGMENTS",
                "discarded_count": discarded_count,
                "discarded_seconds": round(discarded_total, 6),
                "min_keep_segment_seconds": min_keep_segment_seconds,
            }
        )

    keep_segments: list[dict[str, float]] = [
        {"source_start": start, "source_end": end} for start, end in pruned
    ]
    return keep_segments, plan_warnings


def _filler_intervals_from_transcript(
    transcript_payload: dict[str, Any],
    *,
    padding_before: float,
    padding_after: float,
    source_duration: float,
) -> list[tuple[float, float]]:
    segments = transcript_payload.get("segments")
    if not isinstance(segments, list):
        return []
    intervals: list[tuple[float, float]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for word in segment.get("words", []) or []:
            if not isinstance(word, dict):
                continue
            if word.get("is_filler") is not True:
                continue
            try:
                start = float(word["start"]) - padding_before
                end = float(word["end"]) + padding_after
            except (KeyError, TypeError, ValueError):
                continue
            start = max(0.0, start)
            end = min(source_duration, end)
            if end > start:
                intervals.append((start, end))
    return intervals


def _merge_close_intervals(
    intervals: list[tuple[float, float]],
    *,
    merge_within: float,
) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda interval: interval[0])
    merged: list[list[float]] = []
    for start, end in sorted_intervals:
        if merged and start - merged[-1][1] <= merge_within:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _subtract_intervals_from_keep_segments(
    *,
    keep_segments: list[dict[str, float]],
    cut_intervals: list[tuple[float, float]],
) -> list[dict[str, float]]:
    """Subtract a sorted, merged list of ``cut_intervals`` from each
    ``keep_segment``. A segment that contains a cut may be split into two
    smaller segments. The result is a sorted list with no overlaps.
    """
    if not cut_intervals:
        return keep_segments

    result: list[dict[str, float]] = []
    for segment in keep_segments:
        keep_start = float(segment["source_start"])
        keep_end = float(segment["source_end"])
        sub_intervals: list[tuple[float, float]] = [(keep_start, keep_end)]
        for cut_start, cut_end in cut_intervals:
            new_subs: list[tuple[float, float]] = []
            for window_start, window_end in sub_intervals:
                if cut_end <= window_start or cut_start >= window_end:
                    new_subs.append((window_start, window_end))
                    continue
                if cut_start > window_start:
                    new_subs.append((window_start, cut_start))
                if cut_end < window_end:
                    new_subs.append((cut_end, window_end))
            sub_intervals = new_subs
            if not sub_intervals:
                break
        for window_start, window_end in sub_intervals:
            if window_end > window_start:
                result.append({"source_start": window_start, "source_end": window_end})
    return result


def _drop_short_keep_segments(
    *,
    keep_segments: list[dict[str, float]],
    min_keep_segment_seconds: float,
    plan_warnings: list[dict[str, Any]],
    warning_code: str,
) -> list[dict[str, float]]:
    if min_keep_segment_seconds <= 0:
        return keep_segments
    pruned: list[dict[str, float]] = []
    discarded_total = 0.0
    discarded_count = 0
    for segment in keep_segments:
        duration = float(segment["source_end"]) - float(segment["source_start"])
        if duration < min_keep_segment_seconds:
            discarded_total += duration
            discarded_count += 1
            continue
        pruned.append(segment)
    if discarded_count > 0:
        plan_warnings.append(
            {
                "code": warning_code,
                "discarded_count": discarded_count,
                "discarded_seconds": round(discarded_total, 6),
                "min_keep_segment_seconds": min_keep_segment_seconds,
            }
        )
    return pruned
