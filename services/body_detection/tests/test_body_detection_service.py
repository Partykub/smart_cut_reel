from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.body_detection.service import DetectionCandidate
from services.body_detection.service import BodyDetectionService
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

    @patch.object(BodyDetectionService, "_detect_proxy_frames")
    def test_writes_detected_and_fallback_tracks(self, mock_detect_proxy_frames) -> None:
        mock_detect_proxy_frames.return_value = {
            0: DetectionCandidate(x=100.0, y=120.0, w=400.0, h=800.0, confidence=0.93),
            2: DetectionCandidate(x=200.0, y=140.0, w=420.0, h=780.0, confidence=0.88),
        }

        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["body_tracks_raw"])

        self.assertEqual(response.outputs["body_tracks_raw"], self.request.expected_outputs["body_tracks_raw"])
        self.assertEqual(payload["coordinate_space"], "source")
        self.assertEqual(payload["detector_backend"], "hog_person_detector")
        self.assertEqual(payload["proxy_resolution"], {"width": 960, "height": 540})
        self.assertEqual(len(payload["tracks"]), 3)
        self.assertEqual(payload["tracks"][0]["frame_index"], 0)
        self.assertEqual(payload["tracks"][0]["center"], {"x": 300.0, "y": 520.0})
        self.assertFalse(payload["tracks"][0]["missing"])
        self.assertTrue(payload["tracks"][1]["missing"])
        self.assertEqual(payload["tracks"][1]["center"], {"x": 960.0, "y": 540.0})
        self.assertEqual(payload["detection_summary"], {"detected_frames": 2, "missing_frames": 1})
        self.assertEqual(response.warnings[0].code, "BODY_DETECTION_MISSING_FRAMES")