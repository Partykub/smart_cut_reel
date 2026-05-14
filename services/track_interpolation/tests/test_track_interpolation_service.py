from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.track_interpolation.service import TrackInterpolationService


class TrackInterpolationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="track_interpolation",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "body_tracks_interpolated": "jobs/job_test/artifacts/body_tracks_interpolated.json",
            },
        )
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "body_tracks_raw": {
                        "object_key": "jobs/job_test/artifacts/body_tracks_raw.json",
                    }
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_raw.json",
            {
                "coordinate_space": "source",
                "source_resolution": {"width": 1920, "height": 1080},
                "tracks": [
                    {
                        "frame_index": 0,
                        "t": 0.0,
                        "bbox": {"x": 100.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "center": {"x": 300.0, "y": 520.0},
                        "confidence": 0.9,
                        "missing": False,
                    },
                    {
                        "frame_index": 1,
                        "t": 0.2,
                        "bbox": {"x": 0.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "center": {"x": 0.0, "y": 520.0},
                        "confidence": 0.0,
                        "missing": True,
                    },
                    {
                        "frame_index": 2,
                        "t": 0.4,
                        "bbox": {"x": 300.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "center": {"x": 500.0, "y": 520.0},
                        "confidence": 0.85,
                        "missing": False,
                    },
                ],
            },
        )
        self.service = TrackInterpolationService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fills_short_missing_gap_with_linear_interpolation(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_interpolated"])

        self.assertEqual(response.outputs["body_tracks_interpolated"], self.request.expected_outputs["body_tracks_interpolated"])
        self.assertEqual(payload["tracks"][1]["center"], {"x": 400.0, "y": 520.0})
        self.assertFalse(payload["tracks"][1]["missing"])
        self.assertTrue(payload["tracks"][1]["interpolated"])
        self.assertEqual(payload["tracks"][1]["source"], "linear_interpolation")
        self.assertEqual(response.warnings[0].code, "TRACK_INTERPOLATION_FILLED_GAPS")

    def test_adjusts_outlier_jump_over_speed_limit(self) -> None:
        self.request.config = {"max_center_jump_per_second": 50.0}

        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_interpolated"])

        self.assertEqual(payload["tracks"][1]["center"], {"x": 300.0, "y": 520.0})
        self.assertEqual(payload["tracks"][2]["center"], {"x": 300.0, "y": 520.0})
        warning_codes = [warning.code for warning in response.warnings]
        self.assertIn("TRACK_INTERPOLATION_OUTLIERS_ADJUSTED", warning_codes)

    def test_keeps_sustained_jump_when_next_frame_confirms_transition(self) -> None:
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_raw.json",
            {
                "coordinate_space": "source",
                "source_resolution": {"width": 640, "height": 360},
                "tracks": [
                    {
                        "frame_index": 0,
                        "t": 0.0,
                        "bbox": {"x": 80.0, "y": 60.0, "w": 120.0, "h": 200.0},
                        "center": {"x": 140.0, "y": 160.0},
                        "confidence": 0.95,
                        "missing": False,
                        "source": "yolo_person_detector",
                    },
                    {
                        "frame_index": 1,
                        "t": 0.2,
                        "bbox": {"x": 330.0, "y": 60.0, "w": 120.0, "h": 200.0},
                        "center": {"x": 390.0, "y": 160.0},
                        "confidence": 0.94,
                        "missing": False,
                        "source": "yolo_person_detector",
                    },
                    {
                        "frame_index": 2,
                        "t": 0.4,
                        "bbox": {"x": 340.0, "y": 60.0, "w": 120.0, "h": 200.0},
                        "center": {"x": 400.0, "y": 160.0},
                        "confidence": 0.94,
                        "missing": False,
                        "source": "yolo_person_detector",
                    },
                ],
            },
        )
        self.request.config = {"max_center_jump_per_second": 600.0}

        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_interpolated"])

        self.assertEqual(payload["tracks"][1]["center"], {"x": 390.0, "y": 160.0})
        self.assertEqual(payload["tracks"][1].get("source"), "yolo_person_detector")
        warning_codes = [warning.code for warning in response.warnings]
        self.assertNotIn("TRACK_INTERPOLATION_OUTLIERS_ADJUSTED", warning_codes)

    def test_interpolates_body_and_face_debug_boxes_when_present(self) -> None:
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_raw.json",
            {
                "coordinate_space": "source",
                "source_resolution": {"width": 1920, "height": 1080},
                "face_detector_backend": "retinaface",
                "tracks": [
                    {
                        "frame_index": 0,
                        "t": 0.0,
                        "bbox": {"x": 100.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "body_bbox": {"x": 100.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "face_bbox": {"x": 220.0, "y": 200.0, "w": 120.0, "h": 120.0},
                        "center": {"x": 300.0, "y": 520.0},
                        "confidence": 0.9,
                        "missing": False,
                    },
                    {
                        "frame_index": 1,
                        "t": 0.2,
                        "bbox": {"x": 0.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "body_bbox": None,
                        "face_bbox": None,
                        "center": {"x": 0.0, "y": 520.0},
                        "confidence": 0.0,
                        "missing": True,
                    },
                    {
                        "frame_index": 2,
                        "t": 0.4,
                        "bbox": {"x": 300.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "body_bbox": {"x": 300.0, "y": 120.0, "w": 400.0, "h": 800.0},
                        "face_bbox": {"x": 360.0, "y": 200.0, "w": 120.0, "h": 120.0},
                        "center": {"x": 500.0, "y": 520.0},
                        "confidence": 0.85,
                        "missing": False,
                    },
                ],
            },
        )

        self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_interpolated"])

        self.assertEqual(payload["face_detector_backend"], "retinaface")
        self.assertEqual(payload["tracks"][1]["body_bbox"], {"x": 200.0, "y": 120.0, "w": 400.0, "h": 800.0})
        self.assertEqual(payload["tracks"][1]["face_bbox"], {"x": 290.0, "y": 200.0, "w": 120.0, "h": 120.0})
