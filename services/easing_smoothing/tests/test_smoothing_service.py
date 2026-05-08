from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.easing_smoothing.service import EasingSmoothingService


class EasingSmoothingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="easing_smoothing",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "reframe_plan_smooth": "jobs/job_test/artifacts/reframe_plan_smooth.json",
            },
        )
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "reframe_plan_raw": {"object_key": "jobs/job_test/artifacts/reframe_plan_raw.json"},
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/reframe_plan_raw.json",
            {
                "crop_width": 608,
                "crop_height": 1080,
                "source_resolution": {"width": 1920, "height": 1080},
                "target_resolution": {"width": 1080, "height": 1920},
                "keyframes": [
                    {"frame_index": 0, "t": 0.0, "x": 0.0, "y": 0.0, "confidence": 0.9},
                    {"frame_index": 1, "t": 0.2, "x": 100.0, "y": 0.0, "confidence": 0.9},
                    {"frame_index": 2, "t": 0.4, "x": 900.0, "y": 0.0, "confidence": 0.9},
                ],
            },
        )
        self.service = EasingSmoothingService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_smooths_large_movement_and_preserves_bounds(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["reframe_plan_smooth"])

        self.assertEqual(response.outputs["reframe_plan_smooth"], self.request.expected_outputs["reframe_plan_smooth"])
        self.assertEqual(payload["keyframes"][0]["x"], 0.0)
        self.assertGreater(payload["keyframes"][1]["x"], 0.0)
        self.assertLess(payload["keyframes"][1]["x"], 100.0)
        self.assertGreater(payload["keyframes"][2]["x"], 0.0)
        self.assertLess(payload["keyframes"][2]["x"], 900.0)
        self.assertTrue(payload["keyframes"][2]["smoothed"])
