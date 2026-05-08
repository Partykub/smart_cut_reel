from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.reframe_planning.api import create_app


class ReframePlanningApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.output_key = "jobs/job_test/artifacts/reframe_plan_raw.json"
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "metadata": {"object_key": "jobs/job_test/artifacts/metadata.json"},
                    "body_tracks_interpolated": {"object_key": "jobs/job_test/artifacts/body_tracks_interpolated.json"},
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/metadata.json",
            {
                "width": 1920,
                "height": 1080,
                "target_crop": {"width": 608, "height": 1080},
                "target_resolution": {"width": 1080, "height": 1920},
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_interpolated.json",
            {
                "tracks": [
                    {
                        "frame_index": 0,
                        "t": 0.0,
                        "center": {"x": 300.0, "y": 520.0},
                        "confidence": 0.9,
                        "source": "detected",
                    }
                ]
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

    def test_run_endpoint_writes_reframe_plan(self) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "reframe_planning",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "artifact_manifest": self.artifact_manifest_key,
                },
                "expected_outputs": {
                    "reframe_plan_raw": self.output_key,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outputs"], {"reframe_plan_raw": self.output_key})
        payload = self.store.download_json(self.output_key)
        self.assertEqual(payload["keyframes"][0]["x"], 0.0)
