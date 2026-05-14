from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from orchestrator.object_store import FilesystemObjectStore
from services.body_detection.service import DetectionCandidate
from services.body_detection.service import DetectionRunResult
from services.body_detection.service import BodyDetectionService
from services.common.runtime import ServiceWarning
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context


class BodyDetectionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="body_detection",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "source_video": "jobs/job_test/input/source.mp4",
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "body_tracks_raw": "jobs/job_test/artifacts/body_tracks_raw.json",
            },
        )
        self.store.upload_bytes(self.request.inputs["source_video"], b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "metadata": {
                        "object_key": "jobs/job_test/artifacts/metadata.json",
                    },
                    "proxy": {
                        "object_key": "jobs/job_test/artifacts/proxy.mp4",
                    },
                    "sampled_frames": {
                        "object_key": "jobs/job_test/artifacts/sampled_frames.json",
                    }
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/metadata.json",
            {
                "width": 1920,
                "height": 1080,
            },
        )
        self.store.upload_bytes("jobs/job_test/artifacts/proxy.mp4", b"proxy-bytes", content_type="video/mp4")
        self.store.upload_json(
            "jobs/job_test/artifacts/sampled_frames.json",
            {
                "proxy_resolution": {"width": 960, "height": 540},
                "frames": [
                    {"index": 0, "t": 0.0},
                    {"index": 1, "t": 0.2},
                    {"index": 2, "t": 0.4},
                ],
            },
        )
        self.service = BodyDetectionService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_config_defaults_to_high_confidence_threshold(self) -> None:
        config = self.service._config(build_context(self.request, self.store))

        self.assertEqual(config["min_confidence"], 0.9)
        self.assertEqual(config["face_detector_backend"], "retinaface")
        self.assertEqual(config["face_min_confidence"], 0.6)

    @patch.object(BodyDetectionService, "_detect_proxy_frames")
    def test_writes_detected_and_fallback_tracks(self, mock_detect_proxy_frames) -> None:
        mock_detect_proxy_frames.return_value = DetectionRunResult(
            detections_by_frame={
                0: DetectionCandidate(x=100.0, y=120.0, w=400.0, h=800.0, confidence=0.93),
                2: DetectionCandidate(x=200.0, y=140.0, w=420.0, h=780.0, confidence=0.88),
            },
            detector_backend="yolo_ultralytics_cpu",
            track_source="yolo_person_detector",
            face_detector_backend="retinaface",
            warnings=[
                ServiceWarning(
                    code="BODY_DETECTION_GPU_FALLBACK_CPU",
                    message="YOLO GPU inference failed and body detection retried on CPU.",
                    step="body_detection",
                )
            ],
        )

        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_raw"])

        self.assertEqual(response.outputs["body_tracks_raw"], self.request.expected_outputs["body_tracks_raw"])
        self.assertEqual(payload["coordinate_space"], "source")
        self.assertEqual(payload["detector_backend"], "yolo_ultralytics_cpu")
        self.assertEqual(payload["face_detector_backend"], "retinaface")
        self.assertEqual(payload["proxy_resolution"], {"width": 960, "height": 540})
        self.assertEqual(len(payload["tracks"]), 3)
        self.assertEqual(payload["tracks"][0]["frame_index"], 0)
        self.assertEqual(payload["tracks"][0]["center"], {"x": 300.0, "y": 520.0})
        self.assertEqual(payload["tracks"][0]["source"], "yolo_person_detector")
        self.assertIsNone(payload["tracks"][0]["body_bbox"])
        self.assertIsNone(payload["tracks"][0]["face_bbox"])
        self.assertFalse(payload["tracks"][0]["missing"])
        self.assertTrue(payload["tracks"][1]["missing"])
        self.assertEqual(payload["tracks"][1]["center"], {"x": 960.0, "y": 540.0})
        self.assertIsNone(payload["tracks"][1]["body_bbox"])
        self.assertIsNone(payload["tracks"][1]["face_bbox"])
        self.assertEqual(payload["detection_summary"], {"detected_frames": 2, "missing_frames": 1})
        self.assertEqual(response.warnings[0].code, "BODY_DETECTION_GPU_FALLBACK_CPU")
        self.assertEqual(response.warnings[1].code, "BODY_DETECTION_MISSING_FRAMES")

    @patch.object(BodyDetectionService, "_detect_proxy_frames")
    def test_prefers_per_frame_sources_when_face_detection_mixes_with_body_fallback(self, mock_detect_proxy_frames) -> None:
        mock_detect_proxy_frames.return_value = DetectionRunResult(
            detections_by_frame={
                0: DetectionCandidate(x=100.0, y=120.0, w=160.0, h=160.0, confidence=0.97),
                1: DetectionCandidate(x=240.0, y=110.0, w=420.0, h=780.0, confidence=0.82),
            },
            detector_backend="yolo_ultralytics_cpu",
            track_source="yolo_person_detector",
            face_detector_backend="face_recognition",
            sources_by_frame={
                0: "face_recognition_detector",
                1: "yolo_body_fallback",
            },
            debug_boxes_by_frame={
                0: {
                    "body": DetectionCandidate(x=80.0, y=60.0, w=420.0, h=780.0, confidence=0.91),
                    "face": DetectionCandidate(x=100.0, y=120.0, w=160.0, h=160.0, confidence=0.97),
                },
                1: {
                    "body": DetectionCandidate(x=240.0, y=110.0, w=420.0, h=780.0, confidence=0.82),
                },
            },
            warnings=[],
        )

        self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_raw"])

        self.assertEqual(payload["tracks"][0]["source"], "face_recognition_detector")
        self.assertEqual(payload["tracks"][1]["source"], "yolo_body_fallback")
        self.assertEqual(payload["tracks"][0]["face_bbox"], {"x": 100.0, "y": 120.0, "w": 160.0, "h": 160.0})
        self.assertEqual(payload["tracks"][0]["body_bbox"], {"x": 80.0, "y": 60.0, "w": 420.0, "h": 780.0})
        self.assertIsNone(payload["tracks"][1]["face_bbox"])
        self.assertEqual(payload["tracks"][1]["body_bbox"], {"x": 240.0, "y": 110.0, "w": 420.0, "h": 780.0})

    @patch.object(BodyDetectionService, "_detect_face_in_body_candidate")
    @patch.object(BodyDetectionService, "_detect_people_in_frame")
    def test_run_detection_pass_scales_debug_boxes_to_source_space(
        self,
        mock_detect_people_in_frame,
        mock_detect_face_in_body_candidate,
    ) -> None:
        mock_detect_people_in_frame.return_value = [
            DetectionCandidate(x=100.0, y=50.0, w=200.0, h=300.0, confidence=0.95)
        ]
        mock_detect_face_in_body_candidate.return_value = DetectionCandidate(
            x=120.0,
            y=80.0,
            w=60.0,
            h=70.0,
            confidence=0.99,
        )

        class FakeCapture:
            def get(self, prop: int) -> float:
                if prop == fake_cv2.CAP_PROP_FPS:
                    return 60.0
                return 0.0

            def set(self, *_args) -> bool:
                return True

            def read(self) -> tuple[bool, object]:
                return True, object()

        fake_cv2 = Mock()
        fake_cv2.CAP_PROP_POS_MSEC = 0
        fake_cv2.CAP_PROP_POS_FRAMES = 1
        fake_cv2.CAP_PROP_FPS = 2

        detections_by_frame, sources_by_frame, debug_boxes_by_frame = self.service._run_detection_pass(
            cv2=fake_cv2,
            capture=FakeCapture(),
            yolo_model=Mock(),
            frames=[{"index": 0, "t": 0.0}],
            sample_fps=60.0,
            proxy_width=960,
            proxy_height=540,
            source_width=1920,
            source_height=1080,
            min_confidence=0.9,
            face_detector_backend="retinaface",
            face_min_confidence=0.6,
            face_recognition_model="hog",
            subject_selection_strategy="highest_confidence",
            image_size=640,
            person_class_id=0,
            device="cpu",
            warnings=[],
            warning_codes=set(),
        )

        self.assertEqual(sources_by_frame[0], "retinaface_detector")
        self.assertEqual(
            detections_by_frame[0],
            DetectionCandidate(x=240.0, y=160.0, w=120.0, h=140.0, confidence=0.99),
        )
        self.assertEqual(
            debug_boxes_by_frame[0]["body"],
            DetectionCandidate(x=200.0, y=100.0, w=400.0, h=600.0, confidence=0.95),
        )
        self.assertEqual(
            debug_boxes_by_frame[0]["face"],
            DetectionCandidate(x=240.0, y=160.0, w=120.0, h=140.0, confidence=0.99),
        )

    @patch.object(BodyDetectionService, "_detect_face_in_body_candidate")
    @patch.object(BodyDetectionService, "_detect_people_in_frame")
    def test_run_detection_pass_seeks_by_frame_when_proxy_fps_available(
        self,
        mock_detect_people_in_frame,
        mock_detect_face_in_body_candidate,
    ) -> None:
        mock_detect_people_in_frame.return_value = [
            DetectionCandidate(x=100.0, y=50.0, w=200.0, h=300.0, confidence=0.95)
        ]
        mock_detect_face_in_body_candidate.return_value = None

        class FakeCapture:
            def __init__(self) -> None:
                self.set_calls: list[tuple[int, float]] = []

            def get(self, prop: int) -> float:
                if prop == fake_cv2.CAP_PROP_FPS:
                    return 59.992998
                return 0.0

            def set(self, prop: int, value: float) -> bool:
                self.set_calls.append((prop, value))
                return True

            def read(self) -> tuple[bool, object]:
                return True, object()

        fake_cv2 = Mock()
        fake_cv2.CAP_PROP_POS_MSEC = 0
        fake_cv2.CAP_PROP_POS_FRAMES = 1
        fake_cv2.CAP_PROP_FPS = 2
        capture = FakeCapture()

        self.service._run_detection_pass(
            cv2=fake_cv2,
            capture=capture,
            yolo_model=Mock(),
            frames=[{"index": 788, "t": 13.134866}],
            sample_fps=59.992998,
            proxy_width=960,
            proxy_height=540,
            source_width=1920,
            source_height=1080,
            min_confidence=0.9,
            face_detector_backend="retinaface",
            face_min_confidence=0.6,
            face_recognition_model="hog",
            subject_selection_strategy="highest_confidence",
            image_size=640,
            person_class_id=0,
            device="cpu",
            warnings=[],
            warning_codes=set(),
        )

        self.assertEqual(capture.set_calls[0], (fake_cv2.CAP_PROP_POS_FRAMES, 788))

    @patch.object(BodyDetectionService, "_detect_face_in_body_candidate")
    @patch.object(BodyDetectionService, "_detect_people_in_frame")
    def test_run_detection_pass_falls_back_to_timestamp_seek_when_proxy_fps_unavailable(
        self,
        mock_detect_people_in_frame,
        mock_detect_face_in_body_candidate,
    ) -> None:
        mock_detect_people_in_frame.return_value = [
            DetectionCandidate(x=100.0, y=50.0, w=200.0, h=300.0, confidence=0.95)
        ]
        mock_detect_face_in_body_candidate.return_value = None

        class FakeCapture:
            def __init__(self) -> None:
                self.set_calls: list[tuple[int, float]] = []

            def get(self, _prop: int) -> float:
                return 0.0

            def set(self, prop: int, value: float) -> bool:
                self.set_calls.append((prop, value))
                return True

            def read(self) -> tuple[bool, object]:
                return True, object()

        fake_cv2 = Mock()
        fake_cv2.CAP_PROP_POS_MSEC = 0
        fake_cv2.CAP_PROP_POS_FRAMES = 1
        fake_cv2.CAP_PROP_FPS = 2
        capture = FakeCapture()

        self.service._run_detection_pass(
            cv2=fake_cv2,
            capture=capture,
            yolo_model=Mock(),
            frames=[{"index": 788, "t": 13.134866}],
            sample_fps=0.0,
            proxy_width=960,
            proxy_height=540,
            source_width=1920,
            source_height=1080,
            min_confidence=0.9,
            face_detector_backend="retinaface",
            face_min_confidence=0.6,
            face_recognition_model="hog",
            subject_selection_strategy="highest_confidence",
            image_size=640,
            person_class_id=0,
            device="cpu",
            warnings=[],
            warning_codes=set(),
        )

        self.assertEqual(capture.set_calls[0], (fake_cv2.CAP_PROP_POS_MSEC, 13134.866))