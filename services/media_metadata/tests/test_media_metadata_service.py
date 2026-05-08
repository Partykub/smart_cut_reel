from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.media_metadata.service import MediaMetadataService


class MediaMetadataServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="media_metadata",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "source_video": "jobs/job_test/input/source.mp4",
                "job_manifest": "jobs/job_test/manifests/job_manifest.json",
            },
            expected_outputs={
                "metadata": "jobs/job_test/artifacts/metadata.json",
            },
        )
        self.store.upload_bytes(self.request.inputs["source_video"], b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.request.inputs["job_manifest"],
            {
                "job_id": "job_test",
                "target_output": {
                    "aspect_ratio": "9:16",
                    "resolution": {"width": 1080, "height": 1920},
                },
            },
        )
        self.service = MediaMetadataService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("services.media_metadata.service.probe_video_bytes")
    def test_writes_metadata_artifact(self, mock_probe) -> None:
        mock_probe.return_value = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                    "avg_frame_rate": "30000/1001",
                }
            ],
            "format": {"duration": "120.4"},
        }

        response = self.service.run(build_context(self.request, self.store))
        metadata = self.store.download_json(self.request.expected_outputs["metadata"])

        self.assertEqual(response.outputs["metadata"], self.request.expected_outputs["metadata"])
        self.assertEqual(metadata["width"], 1920)
        self.assertEqual(metadata["height"], 1080)
        self.assertAlmostEqual(metadata["fps"], 29.97003, places=5)
        self.assertEqual(metadata["target_crop"], {"width": 608, "height": 1080})
