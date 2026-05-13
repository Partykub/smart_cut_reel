"""Unit tests for the Phase 2 voice activity detection service."""

from __future__ import annotations

import io
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.voice_activity_detection.service import VoiceActivityDetectionService


def _make_pattern_wav(
    *,
    sample_rate: int = 16000,
    sections: list[tuple[float, str]],
) -> bytes:
    """Build a deterministic WAV with alternating loud/silent sections.

    Each section is ``(duration_seconds, kind)`` where ``kind`` is ``"speech"``
    (1 kHz sine at -10 dBFS) or ``"silence"`` (pure zeros).
    """
    pcm = bytearray()
    amp = int(0.3 * 32767)  # ~-10 dBFS sine
    phase = 0.0
    freq = 1000.0
    for duration, kind in sections:
        n_samples = int(round(sample_rate * duration))
        if kind == "speech":
            for i in range(n_samples):
                value = int(amp * math.sin(phase))
                pcm += struct.pack("<h", value)
                phase += 2.0 * math.pi * freq / sample_rate
        else:
            for _ in range(n_samples):
                pcm += struct.pack("<h", 0)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(bytes(pcm))
    return buffer.getvalue()


class VoiceActivityDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.audio_key = "jobs/job_test/artifacts/extracted_audio.wav"
        self.vad_key = "jobs/job_test/artifacts/vad_segments.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_request(self, *, config: dict | None = None) -> RunRequest:
        return RunRequest(
            job_id="job_test",
            step_id="voice_activity_detection",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "extracted_audio": self.audio_key,
            },
            expected_outputs={
                "vad_segments": self.vad_key,
            },
            config=config or {},
        )

    def test_default_config_runs_silero_v5(self) -> None:
        """Default ``model`` is ``silero_v5``; synthetic sine/silence may not
        mirror the old energy RMS pattern, so we assert a valid full-timeline
        envelope instead of exact alternation.
        """
        wav_bytes = _make_pattern_wav(
            sections=[
                (1.0, "silence"),
                (1.5, "speech"),
                (1.5, "silence"),
                (1.0, "speech"),
            ],
        )
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")

        service = VoiceActivityDetectionService()
        response = service.run(build_context(self._build_request(), self.store))
        payload = self.store.download_json(self.vad_key)

        self.assertEqual(response.outputs["vad_segments"], self.vad_key)
        self.assertEqual(payload["schema_version"], "3.0.0")
        self.assertEqual(payload["model"], "silero_v5")
        self.assertAlmostEqual(payload["duration_seconds"], 5.0, delta=0.05)

        self.assertGreaterEqual(len(payload["segments"]), 1)
        for seg in payload["segments"]:
            self.assertIn(seg["type"], {"speech", "silence"})

        speech_total = payload["metrics"]["total_speech_seconds"]
        silence_total = payload["metrics"]["total_silence_seconds"]
        self.assertAlmostEqual(speech_total + silence_total, payload["duration_seconds"], delta=0.05)

        first = payload["segments"][0]
        last = payload["segments"][-1]
        self.assertAlmostEqual(first["start"], 0.0, places=4)
        self.assertAlmostEqual(last["end"], payload["duration_seconds"], places=4)

    def test_all_silent_clip_emits_warning_and_single_silence_segment(self) -> None:
        wav_bytes = _make_pattern_wav(sections=[(2.0, "silence")])
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")

        service = VoiceActivityDetectionService()
        response = service.run(build_context(self._build_request(), self.store))
        payload = self.store.download_json(self.vad_key)

        self.assertEqual(len(payload["segments"]), 1)
        self.assertEqual(payload["segments"][0]["type"], "silence")
        warning_codes = [w.code for w in response.warnings]
        self.assertIn("VAD_NO_SPEECH_DETECTED", warning_codes)

    def test_all_speech_clip_emits_warning_and_single_speech_segment(self) -> None:
        wav_bytes = _make_pattern_wav(sections=[(2.0, "speech")])
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")

        service = VoiceActivityDetectionService()
        response = service.run(build_context(self._build_request(), self.store))
        payload = self.store.download_json(self.vad_key)

        self.assertEqual(len(payload["segments"]), 1)
        self.assertEqual(payload["segments"][0]["type"], "speech")
        warning_codes = [w.code for w in response.warnings]
        self.assertIn("VAD_NO_SILENCE_DETECTED", warning_codes)

    def test_uses_artifact_manifest_to_locate_audio(self) -> None:
        wav_bytes = _make_pattern_wav(sections=[(1.0, "silence"), (1.0, "speech")])
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")
        self.store.upload_json(
            "jobs/job_test/manifests/artifact_manifest.json",
            {
                "artifacts": {
                    "extracted_audio": {"object_key": self.audio_key},
                }
            },
        )
        request = RunRequest(
            job_id="job_test",
            step_id="voice_activity_detection",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "vad_segments": self.vad_key,
            },
        )
        service = VoiceActivityDetectionService()
        service.run(build_context(request, self.store))

        payload = self.store.download_json(self.vad_key)
        self.assertGreaterEqual(len(payload["segments"]), 2)

    def test_unsupported_model_returns_validation_error(self) -> None:
        wav_bytes = _make_pattern_wav(sections=[(1.0, "speech")])
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")

        service = VoiceActivityDetectionService()
        with self.assertRaises(ValueError):
            service.run(
                build_context(
                    self._build_request(config={"model": "energy"}),
                    self.store,
                )
            )

    def test_silero_v5_backend_emits_full_timeline_schema(self) -> None:
        """Smoke test: Silero ONNX model loads, runs on a synthetic clip, and
        emits a ``segments`` array that covers the full duration with valid
        types and a ``silero_v5`` model tag.

        Note: synthetic sine tones are unlikely to trigger Silero's
        speech-trained classifier, so we only assert that the inference
        pipeline ran end-to-end and produced a covering timeline. Real-speech
        accuracy is exercised by the Phase 3 e2e fixtures.
        """
        wav_bytes = _make_pattern_wav(
            sections=[
                (0.6, "silence"),
                (1.5, "speech"),
                (1.5, "silence"),
                (1.0, "speech"),
                (0.4, "silence"),
            ],
        )
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")

        service = VoiceActivityDetectionService()
        response = service.run(
            build_context(
                self._build_request(
                    config={
                        "model": "silero_v5",
                        "speech_threshold": 0.3,
                        "min_speech_duration_seconds": 0.2,
                        "min_silence_duration_seconds": 0.2,
                        "speech_pad_seconds": 0.05,
                    },
                ),
                self.store,
            )
        )
        payload = self.store.download_json(self.vad_key)

        self.assertEqual(response.outputs["vad_segments"], self.vad_key)
        self.assertEqual(payload["model"], "silero_v5")
        self.assertEqual(payload["schema_version"], "3.0.0")
        self.assertAlmostEqual(payload["duration_seconds"], 5.0, delta=0.1)
        self.assertGreaterEqual(len(payload["segments"]), 1)
        for seg in payload["segments"]:
            self.assertIn(seg["type"], {"speech", "silence"})

        first = payload["segments"][0]
        last = payload["segments"][-1]
        self.assertAlmostEqual(first["start"], 0.0, places=4)
        self.assertAlmostEqual(last["end"], payload["duration_seconds"], places=4)

    def test_silero_v4_alias_dispatches_to_same_backend(self) -> None:
        """``silero_v4`` is preserved as a backward-compat alias for Phase 3.0
        manifests; it must dispatch to the same v5 inference path and surface
        ``silero_v4`` in the artifact so existing jobs keep validating.
        """
        wav_bytes = _make_pattern_wav(sections=[(2.0, "silence")])
        self.store.upload_bytes(self.audio_key, wav_bytes, content_type="audio/wav")

        VoiceActivityDetectionService().run(
            build_context(
                self._build_request(config={"model": "silero_v4"}),
                self.store,
            )
        )
        payload = self.store.download_json(self.vad_key)
        self.assertEqual(payload["model"], "silero_v4")


if __name__ == "__main__":
    unittest.main()
