from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.body_detection.api import create_app
from services.body_detection.service import BodyDetectionService
from services.body_detection.service import DetectionCandidate
from services.body_detection.service import DetectionRunResult


class BodyDetectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.source_key = "jobs/job_test/input/source.mp4"
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.metadata_key = "jobs/job_test/artifacts/metadata.json"
        self.output_key = "jobs/job_test/artifacts/body_tracks_raw.json"
        self.store.upload_bytes(self.source_key, b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "metadata": {"object_key": self.metadata_key},
                    "proxy": {"object_key": "jobs/job_test/artifacts/proxy.mp4"},
                    "sampled_frames": {"object_key": "jobs/job_test/artifacts/sampled_frames.json"},
                }
            },
        )
        self.store.upload_json(self.metadata_key, {"width": 1920, "height": 1080})
        self.store.upload_bytes("jobs/job_test/artifacts/proxy.mp4", b"proxy-bytes", content_type="video/mp4")
        self.store.upload_json(
            "jobs/job_test/artifacts/sampled_frames.json",
            {
                "proxy_resolution": {"width": 960, "height": 540},
                "frames": [
                    {"index": 0, "t": 0.0},
                    {"index": 1, "t": 0.2},
                ],
            },
        )

        import os

        self.previous_root = os.environ.get("SMART_CUT_OBJECT_STORE_ROOT")
        os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.temp_dir.name

        from fastapi.testclient import TestClient

        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        import os

        if self.previous_root is None:
            os.environ.pop("SMART_CUT_OBJECT_STORE_ROOT", None)
        else:
            os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.previous_root
        self.temp_dir.cleanup()

    @patch.object(BodyDetectionService, "_detect_proxy_frames")
    def test_run_endpoint_returns_fallback_warning_and_writes_output(self, mock_detect_proxy_frames) -> None:
        mock_detect_proxy_frames.return_value = DetectionRunResult(
            detections_by_frame={
                0: DetectionCandidate(x=100.0, y=120.0, w=400.0, h=800.0, confidence=0.91),
            },
            detector_backend="yolo_ultralytics_cpu",
            track_source="yolo_person_detector",
            warnings=[],
        )

        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "body_detection",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "source_video": self.source_key,
                    "artifact_manifest": self.artifact_manifest_key,
                },
                "expected_outputs": {
                    "body_tracks_raw": self.output_key,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"], {"body_tracks_raw": self.output_key})
        self.assertEqual(payload["warnings"][0]["code"], "BODY_DETECTION_MISSING_FRAMES")
        output = self.store.download_json(self.output_key)
        self.assertEqual(len(output["tracks"]), 2)
        self.assertEqual(output["detector_backend"], "yolo_ultralytics_cpu")
        self.assertEqual(output["tracks"][0]["center"], {"x": 300.0, "y": 520.0})
        self.assertEqual(output["tracks"][0]["source"], "yolo_person_detector")
        self.assertFalse(output["tracks"][0]["missing"])
        self.assertTrue(output["tracks"][1]["missing"])