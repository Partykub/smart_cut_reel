from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.track_interpolation.api import create_app


class TrackInterpolationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.raw_tracks_key = "jobs/job_test/artifacts/body_tracks_raw.json"
        self.output_key = "jobs/job_test/artifacts/body_tracks_interpolated.json"
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "body_tracks_raw": {"object_key": self.raw_tracks_key},
                }
            },
        )
        self.store.upload_json(
            self.raw_tracks_key,
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

    def test_run_endpoint_writes_interpolated_output(self) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "track_interpolation",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "artifact_manifest": self.artifact_manifest_key,
                },
                "expected_outputs": {
                    "body_tracks_interpolated": self.output_key,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outputs"], {"body_tracks_interpolated": self.output_key})
        payload = self.store.download_json(self.output_key)
        self.assertEqual(payload["tracks"][1]["center"], {"x": 400.0, "y": 520.0})
