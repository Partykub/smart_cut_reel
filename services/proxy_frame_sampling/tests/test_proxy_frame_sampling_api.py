from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.proxy_frame_sampling.api import create_app


class ProxyFrameSamplingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.source_key = "jobs/job_test/input/source.mp4"
        self.job_manifest_key = "jobs/job_test/manifests/job_manifest.json"
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.proxy_key = "jobs/job_test/artifacts/proxy.mp4"
        self.sampled_frames_key = "jobs/job_test/artifacts/sampled_frames.json"
        self.metadata_key = "jobs/job_test/artifacts/metadata.json"
        self.store.upload_bytes(self.source_key, b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.job_manifest_key,
            {
                "job_id": "job_test",
                "service_config": {
                    "proxy_frame_sampling": {
                        "sample_every_n_source_frames": 3,
                        "proxy_height": 540,
                    }
                },
            },
        )
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "metadata": {"object_key": self.metadata_key},
                }
            },
        )
        self.store.upload_json(self.metadata_key, {"width": 1920, "height": 1080, "fps": 30.0, "duration": 1.0})

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

    @patch("services.proxy_frame_sampling.service.build_proxy_video_bytes", return_value=b"proxy-bytes")
    def test_run_endpoint_writes_proxy_outputs(self, mock_build_proxy) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "proxy_frame_sampling",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "source_video": self.source_key,
                    "job_manifest": self.job_manifest_key,
                    "artifact_manifest": self.artifact_manifest_key,
                },
                "expected_outputs": {
                    "proxy": self.proxy_key,
                    "sampled_frames": self.sampled_frames_key,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["outputs"],
            {"proxy": self.proxy_key, "sampled_frames": self.sampled_frames_key},
        )
        self.assertEqual(self.store.download_bytes(self.proxy_key), b"proxy-bytes")
        sampled_frames = self.store.download_json(self.sampled_frames_key)
        self.assertEqual(sampled_frames["frame_interval_seconds"], 0.1)
        mock_build_proxy.assert_called_once_with(b"video-bytes", proxy_height=540)