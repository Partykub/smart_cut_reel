from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.easing_smoothing.api import create_app


class EasingSmoothingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.output_key = "jobs/job_test/artifacts/reframe_plan_smooth.json"
        self.store.upload_json(
            self.artifact_manifest_key,
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

    def test_run_endpoint_writes_smoothed_plan(self) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "easing_smoothing",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "artifact_manifest": self.artifact_manifest_key,
                },
                "expected_outputs": {
                    "reframe_plan_smooth": self.output_key,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outputs"], {"reframe_plan_smooth": self.output_key})
        payload = self.store.download_json(self.output_key)
        self.assertEqual(payload["keyframes"][0]["x"], 0.0)
