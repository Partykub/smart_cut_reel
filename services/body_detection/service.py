"""Phase 1 body detection implementation with detector fallback."""

from __future__ import annotations

from dataclasses import dataclass
import tempfile
from typing import Any

from services.common.media import find_video_stream
from services.common.media import normalized_dimensions
from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


@dataclass(slots=True)
class DetectionCandidate:
    x: float
    y: float
    w: float
    h: float
    confidence: float


class BodyDetectionService:
    service_id = "body_detection"

    def run(self, context: ServiceContext) -> RunResponse:
        source_width, source_height = self._source_dimensions(context)
        sampled_frames = self._sampled_frames_payload(context)
        proxy_object_key = self._proxy_object_key(context)
        proxy_width, proxy_height = self._proxy_dimensions(context, sampled_frames)
        config = self._config(context)

        frames = sampled_frames.get("frames", [])
        if not isinstance(frames, list) or not frames:
            raise ValueError("sampled_frames artifact must contain a non-empty frames list")

        detections_by_frame = self._detect_proxy_frames(
            proxy_bytes=context.read_bytes(proxy_object_key),
            frames=frames,
            proxy_width=proxy_width,
            proxy_height=proxy_height,
            source_width=source_width,
            source_height=source_height,
            min_confidence=float(config["min_confidence"]),
            subject_selection_strategy=str(config["subject_selection_strategy"]),
        )

        center_x = source_width / 2.0
        center_y = source_height / 2.0
        bbox_width = round(source_width * 0.32, 2)
        bbox_height = round(source_height * 0.8, 2)

        tracks: list[dict[str, Any]] = []
        missing_count = 0
        detected_count = 0
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            frame_index = int(frame.get("index") or 0)
            timestamp = float(frame.get("t") or 0.0)
            detection = detections_by_frame.get(frame_index)
            if detection is None:
                missing_count += 1
                tracks.append(
                    {
                        "frame_index": frame_index,
                        "t": round(timestamp, 6),
                        "bbox": {
                            "x": round(center_x - (bbox_width / 2.0), 2),
                            "y": round(center_y - (bbox_height / 2.0), 2),
                            "w": bbox_width,
                            "h": bbox_height,
                        },
                        "center": {"x": round(center_x, 2), "y": round(center_y, 2)},
                        "confidence": 0.0,
                        "missing": True,
                        "source": "fallback_center_track",
                    }
                )
                continue

            detected_count += 1
            tracks.append(
                {
                    "frame_index": frame_index,
                    "t": round(timestamp, 6),
                    "bbox": {
                        "x": round(detection.x, 2),
                        "y": round(detection.y, 2),
                        "w": round(detection.w, 2),
                        "h": round(detection.h, 2),
                    },
                    "center": {
                        "x": round(detection.x + (detection.w / 2.0), 2),
                        "y": round(detection.y + (detection.h / 2.0), 2),
                    },
                    "confidence": round(detection.confidence, 4),
                    "missing": False,
                    "source": "hog_person_detector",
                }
            )

        payload = {
            "job_id": context.job_id,
            "coordinate_space": "source",
            "detector_backend": "hog_person_detector",
            "source_resolution": {"width": source_width, "height": source_height},
            "proxy_resolution": {"width": proxy_width, "height": proxy_height},
            "detection_summary": {
                "detected_frames": detected_count,
                "missing_frames": missing_count,
            },
            "tracks": tracks,
        }

        output_key = context.expected_output_key("body_tracks_raw")
        context.write_json(output_key, payload)

        warnings: list[ServiceWarning] = []
        if missing_count > 0:
            warnings.append(
                ServiceWarning(
                    code="BODY_DETECTION_MISSING_FRAMES",
                    message=f"Body detection missed {missing_count} sampled frames and fell back to centered tracks.",
                    step=self.service_id,
                )
            )

        return RunResponse(
            service_id=self.service_id,
            outputs={"body_tracks_raw": output_key},
            warnings=warnings,
        )

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults = {
            "subject_selection_strategy": "nearest_previous_crop_center",
            "min_confidence": 0.5,
        }
        defaults.update(context.request.config)
        return defaults

    def _detect_proxy_frames(
        self,
        *,
        proxy_bytes: bytes,
        frames: list[dict[str, Any]],
        proxy_width: int,
        proxy_height: int,
        source_width: int,
        source_height: int,
        min_confidence: float,
        subject_selection_strategy: str,
    ) -> dict[int, DetectionCandidate]:
        try:
            import cv2
        except ImportError:
            return {}

        with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
            handle.write(proxy_bytes)
            handle.flush()
            capture = cv2.VideoCapture(handle.name)
            if not capture.isOpened():
                return {}

            try:
                detector = self._create_hog_detector(cv2)
                results: dict[int, DetectionCandidate] = {}
                previous_center: tuple[float, float] | None = None
                scale_x = source_width / proxy_width
                scale_y = source_height / proxy_height
                for frame in frames:
                    if not isinstance(frame, dict):
                        continue
                    frame_index = int(frame.get("index") or 0)
                    timestamp_ms = float(frame.get("t") or 0.0) * 1000.0
                    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
                    ok, image = capture.read()
                    if not ok or image is None:
                        continue
                    candidates = self._detect_people_in_frame(
                        detector,
                        image,
                        min_confidence=min_confidence,
                    )
                    chosen = self._select_candidate(
                        candidates,
                        strategy=subject_selection_strategy,
                        previous_center=previous_center,
                    )
                    if chosen is None:
                        continue
                    previous_center = (chosen.x + (chosen.w / 2.0), chosen.y + (chosen.h / 2.0))
                    results[frame_index] = DetectionCandidate(
                        x=chosen.x * scale_x,
                        y=chosen.y * scale_y,
                        w=chosen.w * scale_x,
                        h=chosen.h * scale_y,
                        confidence=chosen.confidence,
                    )
                return results
            finally:
                capture.release()

    def _create_hog_detector(self, cv2: Any) -> Any:
        detector = cv2.HOGDescriptor()
        detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return detector

    def _detect_people_in_frame(
        self,
        detector: Any,
        image: Any,
        *,
        min_confidence: float,
    ) -> list[DetectionCandidate]:
        rects, weights = detector.detectMultiScale(
            image,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        candidates: list[DetectionCandidate] = []
        for (x, y, w, h), weight in zip(rects, weights):
            confidence = float(weight)
            if confidence < min_confidence:
                continue
            candidates.append(
                DetectionCandidate(
                    x=float(x),
                    y=float(y),
                    w=float(w),
                    h=float(h),
                    confidence=confidence,
                )
            )
        return candidates

    def _select_candidate(
        self,
        candidates: list[DetectionCandidate],
        *,
        strategy: str,
        previous_center: tuple[float, float] | None,
    ) -> DetectionCandidate | None:
        if not candidates:
            return None
        if strategy == "largest_box":
            return max(candidates, key=lambda candidate: candidate.w * candidate.h)
        if strategy == "highest_confidence" or previous_center is None:
            return max(candidates, key=lambda candidate: candidate.confidence)

        previous_x, previous_y = previous_center
        return min(
            candidates,
            key=lambda candidate: (
                (candidate.x + (candidate.w / 2.0) - previous_x) ** 2
                + (candidate.y + (candidate.h / 2.0) - previous_y) ** 2,
                -candidate.confidence,
            ),
        )

    def _sampled_frames_payload(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest = self._artifact_manifest(context)
        sampled_frames_object_key = artifact_manifest.get("artifacts", {}).get("sampled_frames", {}).get("object_key")
        if not isinstance(sampled_frames_object_key, str) or not context.exists(sampled_frames_object_key):
            raise ValueError("artifact_manifest is missing sampled_frames for body detection")
        return context.read_json(sampled_frames_object_key)

    def _proxy_object_key(self, context: ServiceContext) -> str:
        artifact_manifest = self._artifact_manifest(context)
        proxy_object_key = artifact_manifest.get("artifacts", {}).get("proxy", {}).get("object_key")
        if not isinstance(proxy_object_key, str) or not context.exists(proxy_object_key):
            raise ValueError("artifact_manifest is missing proxy for body detection")
        return proxy_object_key

    def _proxy_dimensions(self, context: ServiceContext, sampled_frames: dict[str, Any]) -> tuple[int, int]:
        proxy_object_key = self._proxy_object_key(context)

        proxy_resolution = sampled_frames.get("proxy_resolution")
        if isinstance(proxy_resolution, dict):
            width = int(proxy_resolution.get("width") or 0)
            height = int(proxy_resolution.get("height") or 0)
            if width > 0 and height > 0:
                return width, height

        probe_document = probe_video_bytes(context.read_bytes(proxy_object_key))
        stream = find_video_stream(probe_document)
        width, height, _rotation = normalized_dimensions(stream)
        return width, height

    def _source_dimensions(self, context: ServiceContext) -> tuple[int, int]:
        artifact_manifest = self._artifact_manifest(context)
        metadata_object_key = artifact_manifest.get("artifacts", {}).get("metadata", {}).get("object_key")
        if isinstance(metadata_object_key, str) and context.exists(metadata_object_key):
            metadata = context.read_json(metadata_object_key)
            width = int(metadata.get("width") or 0)
            height = int(metadata.get("height") or 0)
            if width > 0 and height > 0:
                return width, height

        probe_document = probe_video_bytes(context.read_bytes(context.input_key("source_video")))
        stream = find_video_stream(probe_document)
        width, height, _rotation = normalized_dimensions(stream)
        return width, height

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            raise ValueError("request is missing artifact_manifest for body detection")
        return context.read_json(artifact_manifest_key)
