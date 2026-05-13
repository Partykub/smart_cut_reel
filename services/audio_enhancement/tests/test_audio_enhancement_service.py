"""Unit tests for the Phase 3 audio enhancement service."""

from __future__ import annotations

import io
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.audio_enhancement.service import AudioEnhancementService
from services.audio_enhancement.service import _FfmpegFilterError
from services.audio_enhancement.service import _build_filter_chain
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context


def _make_wav(*, sample_rate: int = 16000, channels: int = 1, duration: float = 0.5) -> bytes:
    n_frames = int(round(sample_rate * duration))
    pcm = bytearray()
    amp = int(0.1 * 32767)
    phase = 0.0
    freq = 440.0
    for _ in range(n_frames):
        value = int(amp * math.sin(phase))
        for _ in range(channels):
            pcm += struct.pack("<h", value)
        phase += 2.0 * math.pi * freq / sample_rate

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(channels)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(bytes(pcm))
    return buffer.getvalue()


class AudioEnhancementServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.extracted_key = "jobs/job_test/artifacts/extracted_audio.wav"
        self.enhanced_key = "jobs/job_test/artifacts/enhanced_audio.wav"
        self.store.upload_bytes(self.extracted_key, _make_wav(), content_type="audio/wav")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_request(self, *, config: dict | None = None) -> RunRequest:
        return RunRequest(
            job_id="job_test",
            step_id="audio_enhancement",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={"extracted_audio": self.extracted_key},
            expected_outputs={"enhanced_audio": self.enhanced_key},
            config=config or {},
        )

    def test_runs_real_ffmpeg_chain_and_writes_wav(self) -> None:
        service = AudioEnhancementService()
        response = service.run(build_context(self._build_request(), self.store))

        self.assertEqual(response.outputs["enhanced_audio"], self.enhanced_key)
        self.assertEqual(response.warnings, [])

        wav_bytes = self.store.download_bytes(self.enhanced_key)
        self.assertEqual(wav_bytes[:4], b"RIFF")
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_in:
            self.assertEqual(wav_in.getframerate(), 16000)
            self.assertEqual(wav_in.getnchannels(), 1)
            self.assertEqual(wav_in.getsampwidth(), 2)
            duration = wav_in.getnframes() / float(wav_in.getframerate())
        self.assertAlmostEqual(duration, 0.5, delta=0.05)
        self.assertEqual(response.metrics["denoise_model"], "std")
        self.assertEqual(response.metrics["target_lufs"], -16.0)

    def test_passes_through_audio_when_ffmpeg_fails(self) -> None:
        service = AudioEnhancementService()
        with patch(
            "services.audio_enhancement.service._run_ffmpeg_chain",
            side_effect=_FfmpegFilterError("simulated failure"),
        ):
            response = service.run(build_context(self._build_request(), self.store))

        self.assertEqual(response.outputs["enhanced_audio"], self.enhanced_key)
        self.assertEqual(len(response.warnings), 1)
        self.assertEqual(response.warnings[0].code, "AUDIO_ENHANCEMENT_FALLBACK")
        self.assertEqual(
            self.store.download_bytes(self.enhanced_key),
            self.store.download_bytes(self.extracted_key),
        )

    def test_bypass_copies_without_ffmpeg_when_all_processing_off(self) -> None:
        service = AudioEnhancementService()
        with patch("services.audio_enhancement.service._run_ffmpeg_chain") as mock_ffmpeg:
            response = service.run(
                build_context(
                    self._build_request(
                        config={
                            "highpass_frequency_hz": 0,
                            "denoise_model": "off",
                            "loudness_normalization_enabled": False,
                        }
                    ),
                    self.store,
                )
            )
        mock_ffmpeg.assert_not_called()
        self.assertEqual(
            self.store.download_bytes(self.enhanced_key),
            self.store.download_bytes(self.extracted_key),
        )
        self.assertEqual(response.metrics["loudness_normalization_enabled"], False)
        self.assertIsNone(response.metrics["input_lufs"])

    def test_build_filter_chain_skips_loudnorm_when_disabled(self) -> None:
        cfg = {
            "highpass_frequency_hz": 80.0,
            "denoise_model": "off",
            "loudness_normalization_enabled": False,
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
        }
        chain = _build_filter_chain(cfg)
        self.assertIn("highpass", chain)
        self.assertNotIn("loudnorm", chain)

    def test_rejects_invalid_denoise_model(self) -> None:
        service = AudioEnhancementService()
        with self.assertRaises(ValueError):
            service.run(
                build_context(
                    self._build_request(config={"denoise_model": "neural-magic"}),
                    self.store,
                )
            )

    def test_supports_artifact_manifest_to_locate_extracted_audio(self) -> None:
        manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.store.upload_json(
            manifest_key,
            {
                "schema_version": "3.0.0",
                "job_id": "job_test",
                "updated_at": "2026-05-08T10:00:00Z",
                "artifacts": {
                    "extracted_audio": {
                        "object_key": self.extracted_key,
                        "produced_by": "audio_extraction",
                        "created_at": "2026-05-08T10:00:00Z",
                        "content_type": "audio/wav",
                    }
                },
            },
        )

        request = RunRequest(
            job_id="job_test",
            step_id="audio_enhancement",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={"artifact_manifest": manifest_key},
            expected_outputs={"enhanced_audio": self.enhanced_key},
        )
        service = AudioEnhancementService()
        response = service.run(build_context(request, self.store))
        self.assertEqual(response.outputs["enhanced_audio"], self.enhanced_key)


if __name__ == "__main__":
    unittest.main()
