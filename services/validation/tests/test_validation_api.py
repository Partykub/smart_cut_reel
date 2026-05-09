from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.validation.api import create_app


class ValidationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.source_key = "jobs/job_test/input/source.mp4"
        self.job_manifest_key = "jobs/job_test/manifests/job_manifest.json"
        self.store.upload_bytes(self.source_key, b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.job_manifest_key,
            {
                "job_id": "job_test",
                "input": {"source_video": {"object_key": self.source_key}},
                "target_output": {
                    "aspect_ratio": "9:16",
                    "resolution": {"width": 1080, "height": 1920},
                },
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

    @patch("services.validation.service.probe_video_bytes")
    def test_run_endpoint_returns_success_payload(self, mock_probe) -> None:
        mock_probe.return_value = {
            "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            "format": {"duration": "4.2"},
        }

        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "validation",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "source_video": self.source_key,
                    "job_manifest": self.job_manifest_key,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "service_id": "validation",
            "status": "success",
            "outputs": {},
            "warnings": [],
            "metrics": {},
        })
