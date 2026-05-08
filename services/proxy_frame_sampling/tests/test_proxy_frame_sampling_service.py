from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.proxy_frame_sampling.service import ProxyFrameSamplingService


class ProxyFrameSamplingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="proxy_frame_sampling",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "source_video": "jobs/job_test/input/source.mp4",
                "job_manifest": "jobs/job_test/manifests/job_manifest.json",
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "proxy": "jobs/job_test/artifacts/proxy.mp4",
                "sampled_frames": "jobs/job_test/artifacts/sampled_frames.json",
            },
        )
        self.store.upload_bytes(self.request.inputs["source_video"], b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.request.inputs["job_manifest"],
            {
                "job_id": "job_test",
                "service_config": {
                    "proxy_frame_sampling": {
                        "sample_fps": 5,
                        "proxy_height": 540,
                    }
                },
            },
        )
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "metadata": {
                        "object_key": "jobs/job_test/artifacts/metadata.json",
                    }
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/metadata.json",
            {
                "width": 1920,
                "height": 1080,
                "duration": 1.0,
            },
        )
        self.service = ProxyFrameSamplingService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("services.proxy_frame_sampling.service.build_proxy_video_bytes", return_value=b"proxy-bytes")
    def test_writes_proxy_and_sampled_frames_artifacts(self, mock_build_proxy) -> None:
        response = self.service.run(build_context(self.request, self.store))

        self.assertEqual(response.outputs["proxy"], self.request.expected_outputs["proxy"])
        self.assertEqual(
            self.store.download_bytes(self.request.expected_outputs["proxy"]),
            b"proxy-bytes",
        )
        sampled_frames = self.store.download_json(self.request.expected_outputs["sampled_frames"])
        self.assertEqual(sampled_frames["proxy_resolution"], {"width": 960, "height": 540})
        self.assertEqual(sampled_frames["frames"][0], {"index": 0, "t": 0.0})
        self.assertEqual(sampled_frames["frames"][-1], {"index": 5, "t": 1.0})
        mock_build_proxy.assert_called_once_with(b"video-bytes", proxy_height=540)
