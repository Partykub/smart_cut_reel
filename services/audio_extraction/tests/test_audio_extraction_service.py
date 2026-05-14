"""Unit tests for the Phase 2 audio extraction service."""

from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.audio_extraction.service import AudioExtractionService
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context


def _make_wav_bytes(*, sample_rate: int = 16000, channels: int = 1, duration_seconds: float = 1.0) -> bytes:
    n_frames = int(sample_rate * duration_seconds)
    pcm = b"".join(struct.pack("<h", 0) for _ in range(n_frames * channels))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "output.wav"
        with wave.open(str(tmp_path), "wb") as wav_out:
            wav_out.setnchannels(channels)
            wav_out.setsampwidth(2)
            wav_out.setframerate(sample_rate)
            wav_out.writeframes(pcm)
        return tmp_path.read_bytes()


class AudioExtractionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="audio_extraction",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "source_video": "jobs/job_test/input/source.mp4",
                "job_manifest": "jobs/job_test/manifests/job_manifest.json",
            },
            expected_outputs={
                "extracted_audio": "jobs/job_test/artifacts/extracted_audio.wav",
            },
        )
        self.store.upload_bytes(
            self.request.inputs["source_video"], b"video-bytes", content_type="video/mp4"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("services.audio_extraction.service._extract_audio_to_wav")
    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_writes_wav_artifact_with_default_config(self, mock_probe, mock_extract) -> None:
        mock_probe.return_value = {"streams": [{"codec_type": "audio"}]}
        mock_extract.return_value = _make_wav_bytes()

        service = AudioExtractionService()
        response = service.run(build_context(self.request, self.store))

        self.assertEqual(response.outputs["extracted_audio"], self.request.expected_outputs["extracted_audio"])
        mock_extract.assert_called_once_with(b"video-bytes", sample_rate=16000, channels=1)
        wav_bytes = self.store.download_bytes(self.request.expected_outputs["extracted_audio"])
        self.assertEqual(wav_bytes[:4], b"RIFF")

    @patch("services.audio_extraction.service._extract_audio_to_wav")
    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_uses_overridden_sample_rate_and_channels(self, mock_probe, mock_extract) -> None:
        mock_probe.return_value = {"streams": [{"codec_type": "audio"}]}
        mock_extract.return_value = _make_wav_bytes(sample_rate=48000, channels=2, duration_seconds=0.1)

        request = RunRequest(
            job_id=self.request.job_id,
            step_id=self.request.step_id,
            minio=self.request.minio,
            inputs=self.request.inputs,
            expected_outputs=self.request.expected_outputs,
            config={"sample_rate": 48000, "channels": 2},
        )
        service = AudioExtractionService()
        service.run(build_context(request, self.store))

        mock_extract.assert_called_once_with(b"video-bytes", sample_rate=48000, channels=2)

    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_fails_when_source_has_no_audio_stream(self, mock_probe) -> None:
        mock_probe.return_value = {"streams": [{"codec_type": "video"}]}

        service = AudioExtractionService()
        with self.assertRaises(ValueError) as ctx:
            service.run(build_context(self.request, self.store))
        self.assertIn("no audio stream", str(ctx.exception))

    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_rejects_invalid_sample_rate(self, mock_probe) -> None:
        mock_probe.return_value = {"streams": [{"codec_type": "audio"}]}

        request = RunRequest(
            job_id=self.request.job_id,
            step_id=self.request.step_id,
            minio=self.request.minio,
            inputs=self.request.inputs,
            expected_outputs=self.request.expected_outputs,
            config={"sample_rate": 12345},
        )
        service = AudioExtractionService()
        with self.assertRaises(ValueError) as ctx:
            service.run(build_context(request, self.store))
        self.assertIn("Invalid sample_rate", str(ctx.exception))

    @patch("services.audio_extraction.service.probe_video_bytes")
    def test_rejects_invalid_channel_count(self, mock_probe) -> None:
        mock_probe.return_value = {"streams": [{"codec_type": "audio"}]}

        request = RunRequest(
            job_id=self.request.job_id,
            step_id=self.request.step_id,
            minio=self.request.minio,
            inputs=self.request.inputs,
            expected_outputs=self.request.expected_outputs,
            config={"channels": 5},
        )
        service = AudioExtractionService()
        with self.assertRaises(ValueError) as ctx:
            service.run(build_context(request, self.store))
        self.assertIn("Invalid channels", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
