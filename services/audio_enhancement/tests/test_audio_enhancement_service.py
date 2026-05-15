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
from services.audio_enhancement.service import _loudnorm_pass2_linear_token
from services.audio_enhancement.service import _parse_astats_overall_peak_db
from services.audio_enhancement.service import _parse_loudnorm_measured_inputs
from services.audio_enhancement.service import _parse_loudnorm_metrics
from services.audio_enhancement.service import _peak_window_gain_db
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
        out_lufs = response.metrics.get("output_lufs")
        self.assertIsNotNone(out_lufs)
        self.assertAlmostEqual(float(out_lufs), -16.0, delta=1.5)
        self.assertIs(response.metrics.get("loudnorm_pass2_applied"), True)
        pre = response.metrics.get("peak_sample_dbfs_pre_peak_force")
        post = response.metrics.get("peak_sample_dbfs")
        self.assertIsInstance(pre, (int, float))
        self.assertIsInstance(post, (int, float))
        self.assertAlmostEqual(float(pre), float(post), delta=0.5)

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

    def test_parse_astats_overall_peak_db_prefers_last_match(self) -> None:
        stderr = "noise\nPeak level dB: -3.0\nOverall\nPeak level dB: -6.020865\n"
        self.assertAlmostEqual(_parse_astats_overall_peak_db(stderr), -6.020865, places=5)

    def test_peak_window_gain_db_too_hot(self) -> None:
        self.assertAlmostEqual(
            _peak_window_gain_db(-6.0, low_dbfs=-18.0, high_dbfs=-14.0, max_boost_db=12.0),
            -8.0,
        )

    def test_peak_window_gain_db_too_quiet_capped(self) -> None:
        self.assertAlmostEqual(
            _peak_window_gain_db(-25.0, low_dbfs=-18.0, high_dbfs=-14.0, max_boost_db=12.0),
            9.0,
        )

    def test_peak_window_gain_db_too_quiet_uncapped(self) -> None:
        self.assertAlmostEqual(
            _peak_window_gain_db(-50.052, low_dbfs=-18.0, high_dbfs=-14.0, max_boost_db=0.0),
            34.052,
            places=3,
        )

    def test_parse_loudnorm_metrics_prefers_last_json_block(self) -> None:
        stderr = (
            '{"input_i" : "-30.00", "output_i" : "-30.00"}\n'
            '{\n\t"input_i" : "-24.15",\n\t"output_i" : "-22.98",\n}\n'
        )
        m = _parse_loudnorm_metrics(stderr)
        self.assertAlmostEqual(m["input_lufs"], -24.15, places=2)
        self.assertAlmostEqual(m["output_lufs"], -22.98, places=2)

    def test_parse_loudnorm_measured_inputs_requires_all_fields(self) -> None:
        stderr = '{"input_i" : "-24.15", "input_tp" : "-10.00"}\n'
        self.assertIsNone(_parse_loudnorm_measured_inputs(stderr))

    def test_parse_loudnorm_measured_inputs_last_block(self) -> None:
        stderr = (
            '{"input_i" : "-30.00", "input_tp" : "-12.00", "input_lra" : "1.00", '
            '"input_thresh" : "-40.00"}\n'
            '{\n\t"input_i" : "-24.15",\n\t"input_tp" : "-11.20",\n\t'
            '"input_lra" : "5.50",\n\t"input_thresh" : "-34.20"\n}\n'
        )
        t = _parse_loudnorm_measured_inputs(stderr)
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t[0], -24.15, places=2)
        self.assertAlmostEqual(t[1], -11.20, places=2)
        self.assertAlmostEqual(t[2], 5.50, places=2)
        self.assertAlmostEqual(t[3], -34.20, places=2)

    def test_parse_loudnorm_measured_inputs_bare_numbers(self) -> None:
        stderr = '{"input_i" : -24.15, "input_tp" : -11.2, "input_lra" : 5.5, "input_thresh" : -34.2}\n'
        t = _parse_loudnorm_measured_inputs(stderr)
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t[0], -24.15, places=2)
        self.assertAlmostEqual(t[2], 5.5, places=2)

    def test_loudnorm_pass2_lra_at_least_measured(self) -> None:
        cfg = {"target_lufs": -23.0, "true_peak_db": -1.5, "loudness_range": 7.0}
        measured = (-24.0, -10.0, 12.5, -34.0)
        tok = _loudnorm_pass2_linear_token(cfg, measured)
        self.assertIn("LRA=12.50", tok)
        self.assertNotIn("LRA=7.00", tok)

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
