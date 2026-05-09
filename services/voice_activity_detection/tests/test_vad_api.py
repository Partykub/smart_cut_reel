"""Integration tests for the Phase 2 VAD FastAPI app."""

from __future__ import annotations

import io
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from orchestrator.object_store import FilesystemObjectStore
from services.voice_activity_detection.api import create_app


def _make_short_pattern_wav() -> bytes:
    sample_rate = 16000
    pcm = bytearray()
    # 0.5s silence
    for _ in range(sample_rate // 2):
        pcm += struct.pack("<h", 0)
    # 0.5s 1 kHz sine at -10 dBFS
    amp = int(0.3 * 32767)
    for i in range(sample_rate // 2):
        pcm += struct.pack("<h", int(amp * math.sin(2 * math.pi * 1000 * i / sample_rate)))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(bytes(pcm))
    return buffer.getvalue()


class VoiceActivityDetectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.audio_key = "jobs/job_test/artifacts/extracted_audio.wav"
        self.vad_key = "jobs/job_test/artifacts/vad_segments.json"
        self.store.upload_bytes(self.audio_key, _make_short_pattern_wav(), content_type="audio/wav")

        self.previous_root = os.environ.get("SMART_CUT_OBJECT_STORE_ROOT")
        os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.temp_dir.name
        self.previous_warmup = os.environ.get("VAD_DISABLE_WARMUP")
        os.environ["VAD_DISABLE_WARMUP"] = "1"

        from fastapi.testclient import TestClient

        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        if self.previous_root is None:
            os.environ.pop("SMART_CUT_OBJECT_STORE_ROOT", None)
        else:
            os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.previous_root
        if self.previous_warmup is None:
            os.environ.pop("VAD_DISABLE_WARMUP", None)
        else:
            os.environ["VAD_DISABLE_WARMUP"] = self.previous_warmup
        self.temp_dir.cleanup()

    def test_run_endpoint_writes_vad_segments(self) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "voice_activity_detection",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {"extracted_audio": self.audio_key},
                "expected_outputs": {"vad_segments": self.vad_key},
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["outputs"], {"vad_segments": self.vad_key})

        payload = self.store.download_json(self.vad_key)
        types = [seg["type"] for seg in payload["segments"]]
        self.assertIn("speech", types)
        self.assertIn("silence", types)


if __name__ == "__main__":
    unittest.main()
