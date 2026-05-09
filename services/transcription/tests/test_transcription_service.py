"""Unit tests for the Phase 3 transcription service.

The faster-whisper model is mocked so the suite stays fast and works without
network access. A separate integration test (run on demand) can exercise the
real model.
"""

from __future__ import annotations

import io
import math
import struct
import tempfile
import unittest
import wave
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.transcription.service import TranscriptionService


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float | None = 0.9


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str
    words: list[FakeWord]


@dataclass
class FakeInfo:
    language: str = "th"


class FakeWhisperModel:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"length": len(audio), "kwargs": kwargs})
        # Emit two fake words: one filler ("เอ่อ"), one real ("สวัสดี")
        words = [
            FakeWord(word="เอ่อ", start=0.10, end=0.35, probability=0.85),
            FakeWord(word="สวัสดี", start=0.50, end=0.95, probability=0.92),
        ]
        segment = FakeSegment(start=0.0, end=1.0, text="เอ่อ สวัสดี", words=words)
        return iter([segment]), FakeInfo(language="th")


def _make_wav(*, duration: float = 1.0, sample_rate: int = 16000) -> bytes:
    n = int(round(duration * sample_rate))
    pcm = bytearray()
    amp = int(0.05 * 32767)
    phase = 0.0
    for _ in range(n):
        value = int(amp * math.sin(phase))
        pcm += struct.pack("<h", value)
        phase += 2.0 * math.pi * 440.0 / sample_rate
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(bytes(pcm))
    return buffer.getvalue()


class TranscriptionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.audio_key = "jobs/job_test/artifacts/enhanced_audio.wav"
        self.vad_key = "jobs/job_test/artifacts/vad_segments.json"
        self.transcript_key = "jobs/job_test/artifacts/transcript.json"
        self.store.upload_bytes(self.audio_key, _make_wav(), content_type="audio/wav")
        self.store.upload_json(
            self.vad_key,
            {
                "schema_version": "3.0.0",
                "job_id": "job_test",
                "model": "silero_v5",
                "audio_object_key": self.audio_key,
                "sample_rate": 16000,
                "channels": 1,
                "duration_seconds": 1.0,
                "segments": [
                    {"start": 0.0, "end": 1.0, "type": "speech", "confidence": 0.95},
                ],
                "metrics": {},
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_request(self, *, config: dict | None = None) -> RunRequest:
        return RunRequest(
            job_id="job_test",
            step_id="transcription",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "enhanced_audio": self.audio_key,
                "vad_segments": self.vad_key,
            },
            expected_outputs={"transcript": self.transcript_key},
            config=config or {},
        )

    @patch("services.transcription.service._load_faster_whisper_model")
    def test_writes_transcript_with_word_timestamps_and_filler_flag(
        self, mock_loader: MagicMock
    ) -> None:
        fake_model = FakeWhisperModel()
        mock_loader.return_value = fake_model

        service = TranscriptionService()
        response = service.run(build_context(self._build_request(), self.store))

        payload = self.store.download_json(self.transcript_key)
        self.assertEqual(response.outputs["transcript"], self.transcript_key)
        self.assertEqual(payload["schema_version"], "3.0.0")
        self.assertEqual(payload["language"], "th")
        self.assertEqual(payload["model"], "small")
        self.assertEqual(len(payload["segments"]), 1)

        words = payload["segments"][0]["words"]
        self.assertEqual([w["word"] for w in words], ["เอ่อ", "สวัสดี"])
        self.assertTrue(words[0].get("is_filler"))
        self.assertNotIn("is_filler", words[1])
        self.assertEqual(payload["metrics"]["filler_word_count"], 1)
        self.assertEqual(payload["metrics"]["total_words"], 2)

    @patch("services.transcription.service._load_faster_whisper_model")
    def test_emits_empty_transcript_when_model_load_fails(
        self, mock_loader: MagicMock
    ) -> None:
        mock_loader.side_effect = RuntimeError("model unavailable in test environment")

        service = TranscriptionService()
        response = service.run(build_context(self._build_request(), self.store))

        payload = self.store.download_json(self.transcript_key)
        self.assertEqual(payload["segments"], [])
        self.assertEqual(payload["metrics"]["total_words"], 0)
        self.assertEqual(len(response.warnings), 1)
        self.assertEqual(response.warnings[0].code, "TRANSCRIPTION_FAILED")

    def test_rejects_invalid_model_choice(self) -> None:
        service = TranscriptionService()
        with self.assertRaises(ValueError):
            service.run(
                build_context(
                    self._build_request(config={"model": "huge"}),
                    self.store,
                )
            )

    def test_skips_transcription_when_remove_filler_words_disabled(self) -> None:
        """When the user has not enabled filler-word cutting, the service must
        short-circuit and write an empty transcript instead of paying the
        faster-whisper cost. The downstream cut planner already treats a
        missing/empty transcript as a no-op for filler intervals.
        """
        manifest_key = "jobs/job_test/manifests/job_manifest.json"
        self.store.upload_json(
            manifest_key,
            {
                "schema_version": "3.0.0",
                "job_id": "job_test",
                "enabled_features": {
                    "remove_dead_air": True,
                    "enhance_audio": True,
                    "remove_filler_words": False,
                },
            },
        )

        request = RunRequest(
            job_id="job_test",
            step_id="transcription",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "enhanced_audio": self.audio_key,
                "vad_segments": self.vad_key,
                "job_manifest": manifest_key,
            },
            expected_outputs={"transcript": self.transcript_key},
        )

        with patch(
            "services.transcription.service._load_faster_whisper_model"
        ) as mock_loader:
            response = TranscriptionService().run(build_context(request, self.store))
            mock_loader.assert_not_called()

        payload = self.store.download_json(self.transcript_key)
        self.assertEqual(payload["segments"], [])
        self.assertEqual(payload["language"], "skipped")
        self.assertEqual(payload["metrics"]["total_words"], 0)
        self.assertEqual(
            payload["metrics"].get("skipped_reason"),
            "remove_filler_words feature disabled",
        )
        self.assertTrue(response.metrics.get("skipped"))

    @patch("services.transcription.service._load_faster_whisper_model")
    def test_uses_extracted_audio_when_enhanced_audio_missing(
        self, mock_loader: MagicMock
    ) -> None:
        fake_model = FakeWhisperModel()
        mock_loader.return_value = fake_model
        extracted_key = "jobs/job_test/artifacts/extracted_audio.wav"
        self.store.upload_bytes(extracted_key, _make_wav(), content_type="audio/wav")

        request = RunRequest(
            job_id="job_test",
            step_id="transcription",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "extracted_audio": extracted_key,
                "vad_segments": self.vad_key,
            },
            expected_outputs={"transcript": self.transcript_key},
        )
        service = TranscriptionService()
        response = service.run(build_context(request, self.store))
        payload = self.store.download_json(self.transcript_key)
        self.assertEqual(response.outputs["transcript"], self.transcript_key)
        self.assertEqual(payload["audio_object_key"], extracted_key)


if __name__ == "__main__":
    unittest.main()
