"""Integration tests for the Phase 2 audio extraction FastAPI app."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.audio_extraction.api import create_app


class AudioExtractionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.source_key = "jobs/job_test/input/source.mp4"
        self.audio_key = "jobs/job_test/artifacts/extracted_audio.wav"
        self.store.upload_bytes(self.source_key, b"video-bytes", content_type="video/mp4")

        self.previous_root = os.environ.get("SMART_CUT_OBJECT_STORE_ROOT")
        os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.temp_dir.name

        from fastapi.testclient import TestClient

        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        if self.previous_root is None:
            os.environ.pop("SMART_CUT_OBJECT_STORE_ROOT", None)
        else:
            os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.previous_root
        self.temp_dir.cleanup()

    @patch("services.audio_extraction.service._extract_audio_to_wav")
    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_run_endpoint_writes_wav_artifact(self, mock_probe, mock_extract) -> None:
        mock_probe.return_value = {"streams": [{"codec_type": "audio"}]}
        mock_extract.return_value = b"RIFF\x00\x00\x00\x00WAVEfmt "

        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "audio_extraction",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {"source_video": self.source_key},
                "expected_outputs": {"extracted_audio": self.audio_key},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outputs"], {"extracted_audio": self.audio_key})
        self.assertTrue(self.store.exists(self.audio_key))

    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_run_endpoint_returns_400_when_no_audio_stream(self, mock_probe) -> None:
        mock_probe.return_value = {"streams": []}

        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "audio_extraction",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {"source_video": self.source_key},
                "expected_outputs": {"extracted_audio": self.audio_key},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no audio stream", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
