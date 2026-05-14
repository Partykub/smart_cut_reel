"""Phase 1 body detection implementation with detector fallback."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
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


@dataclass(slots=True)
class DetectionRunResult:
    detections_by_frame: dict[int, DetectionCandidate]
    detector_backend: str
    track_source: str
    warnings: list[ServiceWarning]
    face_detector_backend: str | None = None
    sources_by_frame: dict[int, str] | None = None
    debug_boxes_by_frame: dict[int, dict[str, DetectionCandidate]] | None = None


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

        detection_result = self._detect_proxy_frames(
            proxy_bytes=context.read_bytes(proxy_object_key),
            frames=frames,
            proxy_width=proxy_width,
            proxy_height=proxy_height,
            source_width=source_width,
            source_height=source_height,
            config=config,
            heartbeat_fn=context.heartbeat,
        )
        detections_by_frame = detection_result.detections_by_frame
        sources_by_frame = detection_result.sources_by_frame or {}
        debug_boxes_by_frame = detection_result.debug_boxes_by_frame or {}

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
            debug_boxes = debug_boxes_by_frame.get(frame_index, {})
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
                        "body_bbox": None,
                        "face_bbox": None,
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
                    "source": sources_by_frame.get(frame_index, detection_result.track_source),
                    "body_bbox": self._serialize_optional_bbox(debug_boxes.get("body")),
                    "face_bbox": self._serialize_optional_bbox(debug_boxes.get("face")),
                }
            )

        payload = {
            "job_id": context.job_id,
            "coordinate_space": "source",
            "detector_backend": detection_result.detector_backend,
            "face_detector_backend": detection_result.face_detector_backend,
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

        warnings: list[ServiceWarning] = list(detection_result.warnings)
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
            "face_detector_backend": "retinaface",
            "subject_selection_strategy": "nearest_previous_crop_center",
            "min_confidence": 0.9,
            "face_min_confidence": 0.6,
            "face_recognition_model": "hog",
            "model_path": os.getenv("BODY_DETECTION_YOLO_MODEL", "yolov8m.pt"),
            "device_preference": os.getenv("BODY_DETECTION_DEVICE_PREFERENCE", "gpu_first"),
            "image_size": 640,
            "person_class_id": 0,
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
        config: dict[str, Any],
        heartbeat_fn: Any = None,
    ) -> DetectionRunResult:
        try:
            import cv2
        except ImportError as exc:
            raise ValueError("opencv-python-headless is required for body detection") from exc

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ValueError("ultralytics is required for YOLO body detection") from exc

        model_path = str(config["model_path"])
        subject_selection_strategy = str(config["subject_selection_strategy"])
        min_confidence = float(config["min_confidence"])
        face_detector_backend = str(config["face_detector_backend"])
        face_min_confidence = float(config["face_min_confidence"])
        face_recognition_model = str(config["face_recognition_model"])
        image_size = int(config["image_size"])
        person_class_id = int(config["person_class_id"])

        yolo_model = YOLO(model_path)
        preferred_device = self._preferred_device(str(config["device_preference"]))
        active_device = preferred_device
        active_backend = self._backend_name(active_device)
        warnings: list[ServiceWarning] = []
        warning_codes: set[str] = set()

        with tempfile.TemporaryDirectory() as tmp_dir:
            proxy_path = Path(tmp_dir) / "proxy.mp4"
            proxy_path.write_bytes(proxy_bytes)
            capture = cv2.VideoCapture(str(proxy_path))
            if not capture.isOpened():
                return DetectionRunResult(
                    detections_by_frame={},
                    detector_backend=active_backend,
                    track_source="yolo_person_detector",
                    warnings=warnings,
                    face_detector_backend=face_detector_backend,
                    debug_boxes_by_frame={},
                )

            try:
                try:
                    detections_by_frame, sources_by_frame, debug_boxes_by_frame = self._run_detection_pass(
                        cv2=cv2,
                        capture=capture,
                        yolo_model=yolo_model,
                        frames=frames,
                        proxy_width=proxy_width,
                        proxy_height=proxy_height,
                        source_width=source_width,
                        source_height=source_height,
                        min_confidence=min_confidence,
                        face_detector_backend=face_detector_backend,
                        face_min_confidence=face_min_confidence,
                        face_recognition_model=face_recognition_model,
                        subject_selection_strategy=subject_selection_strategy,
                        image_size=image_size,
                        person_class_id=person_class_id,
                        device=active_device,
                        heartbeat_fn=heartbeat_fn,
                        warnings=warnings,
                        warning_codes=warning_codes,
                    )
                except Exception as exc:
                    if active_device != "cpu":
                        active_device = "cpu"
                        active_backend = self._backend_name(active_device)
                        warnings.append(
                            ServiceWarning(
                                code="BODY_DETECTION_GPU_FALLBACK_CPU",
                                message=f"YOLO GPU inference failed and body detection retried on CPU: {exc}",
                                step=self.service_id,
                            )
                        )
                        detections_by_frame, sources_by_frame, debug_boxes_by_frame = self._run_detection_pass(
                            cv2=cv2,
                            capture=capture,
                            yolo_model=yolo_model,
                            frames=frames,
                            proxy_width=proxy_width,
                            proxy_height=proxy_height,
                            source_width=source_width,
                            source_height=source_height,
                            min_confidence=min_confidence,
                            face_detector_backend=face_detector_backend,
                            face_min_confidence=face_min_confidence,
                            face_recognition_model=face_recognition_model,
                            subject_selection_strategy=subject_selection_strategy,
                            image_size=image_size,
                            person_class_id=person_class_id,
                            device=active_device,
                            heartbeat_fn=heartbeat_fn,
                            warnings=warnings,
                            warning_codes=warning_codes,
                        )
                    else:
                        raise ValueError(f"YOLO body detection failed on CPU: {exc}") from exc

                return DetectionRunResult(
                    detections_by_frame=detections_by_frame,
                    detector_backend=active_backend,
                    track_source="yolo_person_detector",
                    warnings=warnings,
                    face_detector_backend=face_detector_backend,
                    sources_by_frame=sources_by_frame,
                    debug_boxes_by_frame=debug_boxes_by_frame,
                )
            finally:
                capture.release()

    def _preferred_device(self, device_preference: str) -> str:
        if device_preference == "cpu":
            return "cpu"

        try:
            import torch
        except ImportError:
            return "cpu"

        if torch.cuda.is_available():
            return "cuda:0"
        return "cpu"

    def _backend_name(self, device: str) -> str:
        if device.startswith("cuda"):
            return "yolo_ultralytics_cuda"
        return "yolo_ultralytics_cpu"

    def _run_detection_pass(
        self,
        *,
        cv2: Any,
        capture: Any,
        yolo_model: Any,
        frames: list[dict[str, Any]],
        proxy_width: int,
        proxy_height: int,
        source_width: int,
        source_height: int,
        min_confidence: float,
        face_detector_backend: str,
        face_min_confidence: float,
        face_recognition_model: str,
        subject_selection_strategy: str,
        image_size: int,
        person_class_id: int,
        device: str,
        warnings: list[ServiceWarning],
        warning_codes: set[str],
        heartbeat_fn: Any = None,
    ) -> tuple[dict[int, DetectionCandidate], dict[int, str], dict[int, dict[str, DetectionCandidate]]]:
        results: dict[int, DetectionCandidate] = {}
        sources_by_frame: dict[int, str] = {}
        debug_boxes_by_frame: dict[int, dict[str, DetectionCandidate]] = {}
        previous_center: tuple[float, float] | None = None
        scale_x = source_width / proxy_width
        scale_y = source_height / proxy_height
        _heartbeat_interval = 10
        total_seconds = float(frames[-1].get("t") or 0.0) if frames else 0.0
        for frame_number, frame in enumerate(frames):
            if heartbeat_fn is not None and frame_number % _heartbeat_interval == 0:
                current_t = float(frame.get("t") or 0.0)
                heartbeat_fn(
                    {
                        "current_seconds": round(current_t, 1),
                        "total_seconds": round(total_seconds, 1),
                        "percent": round(
                            current_t / total_seconds * 100, 1
                        ) if total_seconds > 0 else 0.0,
                    }
                )
            if not isinstance(frame, dict):
                continue
            frame_index = int(frame.get("index") or 0)
            timestamp_ms = float(frame.get("t") or 0.0) * 1000.0
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
            ok, image = capture.read()
            if not ok or image is None:
                continue
            candidates = self._detect_people_in_frame(
                yolo_model,
                image,
                min_confidence=min_confidence,
                image_size=image_size,
                person_class_id=person_class_id,
                device=device,
            )
            chosen = self._select_candidate(
                candidates,
                strategy=subject_selection_strategy,
                previous_center=previous_center,
            )
            if chosen is None:
                continue
            previous_center = (chosen.x + (chosen.w / 2.0), chosen.y + (chosen.h / 2.0))
            selected_candidate = chosen
            selected_source = "yolo_body_fallback"
            debug_boxes_by_frame[frame_index] = {
                "body": self._scale_detection_candidate(chosen, scale_x=scale_x, scale_y=scale_y)
            }
            face_candidate = self._detect_face_in_body_candidate(
                image=image,
                body_candidate=chosen,
                face_detector_backend=face_detector_backend,
                face_min_confidence=face_min_confidence,
                face_recognition_model=face_recognition_model,
                warnings=warnings,
                warning_codes=warning_codes,
            )
            if face_candidate is not None:
                selected_candidate = face_candidate
                selected_source = self._track_source_for_face_backend(face_detector_backend)
                debug_boxes_by_frame[frame_index]["face"] = self._scale_detection_candidate(
                    face_candidate,
                    scale_x=scale_x,
                    scale_y=scale_y,
                )
            results[frame_index] = DetectionCandidate(
                x=selected_candidate.x * scale_x,
                y=selected_candidate.y * scale_y,
                w=selected_candidate.w * scale_x,
                h=selected_candidate.h * scale_y,
                confidence=selected_candidate.confidence,
            )
            sources_by_frame[frame_index] = selected_source
        return results, sources_by_frame, debug_boxes_by_frame

    def _scale_detection_candidate(
        self,
        detection: DetectionCandidate,
        *,
        scale_x: float,
        scale_y: float,
    ) -> DetectionCandidate:
        return DetectionCandidate(
            x=detection.x * scale_x,
            y=detection.y * scale_y,
            w=detection.w * scale_x,
            h=detection.h * scale_y,
            confidence=detection.confidence,
        )

    def _serialize_optional_bbox(self, detection: DetectionCandidate | None) -> dict[str, float] | None:
        if detection is None:
            return None
        return {
            "x": round(detection.x, 2),
            "y": round(detection.y, 2),
            "w": round(detection.w, 2),
            "h": round(detection.h, 2),
        }

    def _detect_face_in_body_candidate(
        self,
        *,
        image: Any,
        body_candidate: DetectionCandidate,
        face_detector_backend: str,
        face_min_confidence: float,
        face_recognition_model: str,
        warnings: list[ServiceWarning],
        warning_codes: set[str],
    ) -> DetectionCandidate | None:
        x1 = max(0, int(body_candidate.x))
        y1 = max(0, int(body_candidate.y))
        x2 = max(x1 + 1, int(body_candidate.x + body_candidate.w))
        y2 = max(y1 + 1, int(body_candidate.y + body_candidate.h))
        body_crop = image[y1:y2, x1:x2]
        if body_crop is None or getattr(body_crop, "size", 0) == 0:
            return None

        try:
            if face_detector_backend == "face_recognition":
                face_candidate = self._detect_with_face_recognition(
                    body_crop=body_crop,
                    face_recognition_model=face_recognition_model,
                )
            else:
                face_candidate = self._detect_with_retinaface(
                    body_crop=body_crop,
                    face_min_confidence=face_min_confidence,
                )
        except ImportError as exc:
            self._append_warning_once(
                warnings=warnings,
                warning_codes=warning_codes,
                code="BODY_DETECTION_FACE_BACKEND_UNAVAILABLE",
                message=f"Face detector backend '{face_detector_backend}' is unavailable; falling back to body boxes: {exc}",
            )
            return None
        except Exception as exc:
            self._append_warning_once(
                warnings=warnings,
                warning_codes=warning_codes,
                code="BODY_DETECTION_FACE_BACKEND_FAILED",
                message=f"Face detector backend '{face_detector_backend}' failed; falling back to body boxes: {exc}",
            )
            return None

        if face_candidate is None:
            return None

        return DetectionCandidate(
            x=x1 + face_candidate.x,
            y=y1 + face_candidate.y,
            w=face_candidate.w,
            h=face_candidate.h,
            confidence=face_candidate.confidence,
        )

    def _detect_with_retinaface(
        self,
        *,
        body_crop: Any,
        face_min_confidence: float,
    ) -> DetectionCandidate | None:
        try:
            from retinaface import RetinaFace
        except ImportError as exc:
            raise ImportError("retinaface package is not installed") from exc

        try:
            detections = RetinaFace.detect_faces(body_crop, threshold=face_min_confidence)
        except TypeError:
            detections = RetinaFace.detect_faces(body_crop)

        if not isinstance(detections, dict):
            return None

        candidates: list[DetectionCandidate] = []
        for item in detections.values():
            if not isinstance(item, dict):
                continue
            facial_area = item.get("facial_area")
            if not isinstance(facial_area, (list, tuple)) or len(facial_area) != 4:
                continue
            confidence = float(item.get("score") or item.get("confidence") or 0.0)
            if confidence < face_min_confidence:
                continue
            left, top, right, bottom = [float(value) for value in facial_area]
            candidates.append(
                DetectionCandidate(
                    x=left,
                    y=top,
                    w=max(0.0, right - left),
                    h=max(0.0, bottom - top),
                    confidence=confidence,
                )
            )

        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate.confidence)

    def _detect_with_face_recognition(
        self,
        *,
        body_crop: Any,
        face_recognition_model: str,
    ) -> DetectionCandidate | None:
        try:
            import face_recognition
        except ImportError as exc:
            raise ImportError("face_recognition package is not installed") from exc

        rgb_crop = body_crop[:, :, ::-1]
        locations = face_recognition.face_locations(rgb_crop, model=face_recognition_model)
        candidates: list[DetectionCandidate] = []
        for top, right, bottom, left in locations:
            candidates.append(
                DetectionCandidate(
                    x=float(left),
                    y=float(top),
                    w=max(0.0, float(right - left)),
                    h=max(0.0, float(bottom - top)),
                    confidence=1.0,
                )
            )
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate.w * candidate.h)

    def _append_warning_once(
        self,
        *,
        warnings: list[ServiceWarning],
        warning_codes: set[str],
        code: str,
        message: str,
    ) -> None:
        if code in warning_codes:
            return
        warnings.append(ServiceWarning(code=code, message=message, step=self.service_id))
        warning_codes.add(code)

    def _track_source_for_face_backend(self, face_detector_backend: str) -> str:
        if face_detector_backend == "face_recognition":
            return "face_recognition_detector"
        return "retinaface_detector"

    def _detect_people_in_frame(
        self,
        yolo_model: Any,
        image: Any,
        *,
        min_confidence: float,
        image_size: int,
        person_class_id: int,
        device: str,
    ) -> list[DetectionCandidate]:
        results = yolo_model.predict(
            source=image,
            classes=[person_class_id],
            conf=min_confidence,
            imgsz=image_size,
            device=device,
            verbose=False,
        )
        candidates: list[DetectionCandidate] = []
        boxes = getattr(results[0], "boxes", None) if results else None
        if boxes is None:
            return candidates
        xyxy_values = boxes.xyxy.tolist() if hasattr(boxes.xyxy, "tolist") else list(boxes.xyxy)
        confidence_values = boxes.conf.tolist() if hasattr(boxes.conf, "tolist") else list(boxes.conf)
        for xyxy, confidence in zip(xyxy_values, confidence_values):
            x1, y1, x2, y2 = [float(value) for value in xyxy]
            candidates.append(
                DetectionCandidate(
                    x=x1,
                    y=y1,
                    w=max(0.0, x2 - x1),
                    h=max(0.0, y2 - y1),
                    confidence=float(confidence),
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
