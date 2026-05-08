from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.validation.service import ValidationService


class ValidationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="validation",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "source_video": "jobs/job_test/input/source.mp4",
                "job_manifest": "jobs/job_test/manifests/job_manifest.json",
            },
        )
        self.store.upload_bytes(self.request.inputs["source_video"], b"video-bytes", content_type="video/mp4")
        self.store.upload_json(
            self.request.inputs["job_manifest"],
            {
                "job_id": "job_test",
                "input": {"source_video": {"object_key": self.request.inputs["source_video"]}},
                "target_output": {
                    "aspect_ratio": "9:16",
                    "resolution": {"width": 1080, "height": 1920},
                },
            },
        )
        self.service = ValidationService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("services.validation.service.probe_video_bytes")
    def test_validation_passes_for_supported_source(self, mock_probe) -> None:
        mock_probe.return_value = {
            "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            "format": {"duration": "12.5"},
        }

        response = self.service.run(build_context(self.request, self.store))

        self.assertEqual(response.status, "success")
        self.assertEqual(response.outputs, {})
        self.assertEqual(response.warnings, [])

    @patch("services.validation.service.probe_video_bytes")
    def test_validation_rejects_non_widescreen_source(self, mock_probe) -> None:
        mock_probe.return_value = {
            "streams": [{"codec_type": "video", "width": 1000, "height": 1000}],
            "format": {"duration": "12.5"},
        }

        with self.assertRaisesRegex(ValueError, "16:9"):
            self.service.run(build_context(self.request, self.store))
