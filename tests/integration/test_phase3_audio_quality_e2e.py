"""End-to-end smoke test for the Phase 3 audio quality chain.

Drives the new audio steps end-to-end on a synthetic 9-second clip:

* ``audio_extraction``  → ``extracted_audio.wav``
* ``audio_enhancement`` → ``enhanced_audio.wav`` (real ffmpeg filter chain)
* ``voice_activity_detection`` running the **Silero v5 ONNX** backend on
  ``enhanced_audio.wav`` (not the raw extract — proves enhanced audio is
  consumed when present)
* ``transcription`` (mocked WhisperModel — we are not testing whisper accuracy
  here, only that the pipeline shape is correct end-to-end and that detected
  filler words are propagated to the cut planner)
* ``dead_air_cut_planning`` with ``remove_filler_words = true`` so the planner
  removes the mock filler word AND the silent middle block.

The headline acceptance criteria for Phase 3 are:

1. Enhanced audio is preferred by VAD when present.
2. Silero VAD accepts the synthetic clip without raising and emits a
   timeline-covering segments list.
3. Filler-word cuts subtract from the silence-only keep segments and are
   reflected in ``cut_plan.metrics.removed_filler_seconds``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from orchestrator.object_store import FilesystemObjectStore
from services.audio_enhancement.service import AudioEnhancementService
from services.audio_extraction.service import AudioExtractionService
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.dead_air_cut_planning.service import DeadAirCutPlanningService
from services.transcription.service import TranscriptionService
from services.voice_activity_detection.service import VoiceActivityDetectionService


_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@dataclass
class _FakeWord:
    word: str
    start: float
    end: float
    probability: float | None = 0.9


@dataclass
class _FakeSegment:
    start: float
    end: float
    text: str
    words: list[_FakeWord]


@dataclass
class _FakeInfo:
    language: str = "th"


class _FakeWhisperModel:
    """Returns deterministic ASR output for the synthetic clip.

    The fake transcript marks one filler word in the FIRST speech chunk only;
    subsequent chunks return no words so we get exactly one filler globally.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def transcribe(self, audio, **_kwargs):
        self.call_count += 1
        if self.call_count == 1:
            words = [
                _FakeWord(word="hello", start=0.10, end=0.40, probability=0.92),
                _FakeWord(word="um", start=0.80, end=1.10, probability=0.65),
                _FakeWord(word="world", start=1.40, end=1.90, probability=0.91),
            ]
            segment = _FakeSegment(
                start=0.0, end=2.0, text="hello um world", words=words
            )
            return iter([segment]), _FakeInfo(language="en")
        return iter([]), _FakeInfo(language="en")


def _generate_synthetic_clip(out_path: Path) -> None:
    """9-second 320x180 clip with sine-tone audio in 0–3s and 6–9s, silence 3–6s."""
    cmd = [
        _FFMPEG or "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=9:size=320x180:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=9:sample_rate=16000",
        "-filter_complex",
        "[1:a]volume=enable='between(t,3,6)':volume=0[aout]",
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


@unittest.skipUnless(_FFMPEG and _FFPROBE, "ffmpeg/ffprobe not installed")
class Phase3AudioQualityEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = FilesystemObjectStore(self.root)
        self.job_id = "job_phase3_e2e"
        self.prefix = f"jobs/{self.job_id}"

        src_path = self.root / "source.mp4"
        _generate_synthetic_clip(src_path)
        self.source_key = f"{self.prefix}/input/source.mp4"
        self.store.upload_bytes(
            self.source_key, src_path.read_bytes(), content_type="video/mp4"
        )

        self.metadata_key = f"{self.prefix}/artifacts/metadata.json"
        self.store.upload_json(
            self.metadata_key,
            {"duration": 9.0, "fps": 30.0, "width": 320, "height": 180},
        )

        self.artifact_manifest_key = f"{self.prefix}/manifests/artifact_manifest.json"
        self.job_manifest_key = f"{self.prefix}/manifests/job_manifest.json"
        self.store.upload_json(
            self.job_manifest_key,
            {
                "schema_version": "3.0.0",
                "job_id": self.job_id,
                "input": {"source_video": {"object_key": self.source_key}},
                "target_output": {
                    "aspect_ratio": "9:16",
                    "resolution": {"width": 108, "height": 192},
                    "format": "mp4",
                    "object_key": f"{self.prefix}/outputs/final_9x16.mp4",
                },
                "enabled_features": {
                    "remove_dead_air": True,
                    "enhance_audio": True,
                    "remove_filler_words": True,
                },
            },
        )
        self._refresh_artifact_manifest()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _refresh_artifact_manifest(self, **extra: dict) -> None:
        artifacts: dict = {
            "metadata": {
                "object_key": self.metadata_key,
                "produced_by": "media_metadata",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        }
        artifacts.update(extra)
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "schema_version": "3.0.0",
                "job_id": self.job_id,
                "updated_at": "2026-05-08T00:00:00Z",
                "artifacts": artifacts,
            },
        )

    def _ctx(self, request: RunRequest):
        return build_context(request, self.store)

    def test_pipeline_runs_silero_enhancement_transcription_and_filler_cut(self) -> None:
        # 1. Audio extraction
        extracted_key = f"{self.prefix}/artifacts/extracted_audio.wav"
        AudioExtractionService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="audio_extraction",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={"source_video": self.source_key},
                    expected_outputs={"extracted_audio": extracted_key},
                    config={"sample_rate": 16000, "channels": 1},
                )
            )
        )
        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": extracted_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            }
        )

        # 2. Audio enhancement (real ffmpeg filter chain)
        enhanced_key = f"{self.prefix}/artifacts/enhanced_audio.wav"
        AudioEnhancementService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="audio_enhancement",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={"artifact_manifest": self.artifact_manifest_key},
                    expected_outputs={"enhanced_audio": enhanced_key},
                    config={
                        "denoise_model": "std",
                        "target_lufs": -16.0,
                        "true_peak_db": -1.5,
                        "loudness_range": 11.0,
                        "highpass_frequency_hz": 80,
                    },
                )
            )
        )
        self.assertGreater(len(self.store.download_bytes(enhanced_key)), 1000)

        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": extracted_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            enhanced_audio={
                "object_key": enhanced_key,
                "produced_by": "audio_enhancement",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
        )

        # 3. Silero VAD on enhanced audio
        vad_key = f"{self.prefix}/artifacts/vad_segments.json"
        VoiceActivityDetectionService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="voice_activity_detection",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={"artifact_manifest": self.artifact_manifest_key},
                    expected_outputs={"vad_segments": vad_key},
                    config={
                        "model": "silero_v5",
                        "audio_source": "enhanced_audio_or_extracted",
                        "speech_threshold": 0.3,
                        "min_speech_duration_seconds": 0.2,
                        "min_silence_duration_seconds": 0.2,
                        "speech_pad_seconds": 0.05,
                    },
                )
            )
        )
        vad_payload = self.store.download_json(vad_key)
        self.assertEqual(vad_payload["model"], "silero_v5")
        self.assertEqual(vad_payload["audio_source_kind"], "enhanced_audio")
        self.assertGreater(len(vad_payload["segments"]), 0)
        self.assertAlmostEqual(
            vad_payload["segments"][-1]["end"],
            vad_payload["duration_seconds"],
            places=4,
        )

        # Patch the VAD to expose at least one speech segment for the planner to
        # work with — Silero on a pure 440 Hz sine often returns zero speech.
        if not any(seg["type"] == "speech" for seg in vad_payload["segments"]):
            vad_payload["segments"] = [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "type": "speech",
                    "confidence": 0.95,
                },
                {
                    "start": 3.0,
                    "end": 6.0,
                    "type": "silence",
                    "confidence": 0.95,
                },
                {
                    "start": 6.0,
                    "end": vad_payload["duration_seconds"],
                    "type": "speech",
                    "confidence": 0.95,
                },
            ]
            self.store.upload_json(vad_key, vad_payload)

        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": extracted_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            enhanced_audio={
                "object_key": enhanced_key,
                "produced_by": "audio_enhancement",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            vad_segments={
                "object_key": vad_key,
                "produced_by": "voice_activity_detection",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        )

        # 4. Transcription with mocked WhisperModel
        transcript_key = f"{self.prefix}/artifacts/transcript.json"
        with patch(
            "services.transcription.service._load_faster_whisper_model",
            return_value=_FakeWhisperModel(),
        ):
            TranscriptionService().run(
                self._ctx(
                    RunRequest(
                        job_id=self.job_id,
                        step_id="transcription",
                        minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                        inputs={"artifact_manifest": self.artifact_manifest_key},
                        expected_outputs={"transcript": transcript_key},
                        config={
                            "model": "small",
                            "language": "en",
                            "compute_type": "int8",
                            "filler_words_th": [],
                            "filler_words_en": ["um"],
                            "filler_min_silence_around_seconds": 0.05,
                        },
                    )
                )
            )
        transcript = self.store.download_json(transcript_key)
        filler_words = [
            word
            for segment in transcript["segments"]
            for word in segment["words"]
            if word.get("is_filler")
        ]
        self.assertEqual(len(filler_words), 1)
        self.assertEqual(filler_words[0]["word"].lower(), "um")

        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": extracted_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            enhanced_audio={
                "object_key": enhanced_key,
                "produced_by": "audio_enhancement",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            vad_segments={
                "object_key": vad_key,
                "produced_by": "voice_activity_detection",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
            transcript={
                "object_key": transcript_key,
                "produced_by": "transcription",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        )

        # 5. Dead-air planning with filler word cut
        cut_plan_key = f"{self.prefix}/artifacts/cut_plan.json"
        DeadAirCutPlanningService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="dead_air_cut_planning",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={
                        "artifact_manifest": self.artifact_manifest_key,
                        "job_manifest": self.job_manifest_key,
                    },
                    expected_outputs={"cut_plan": cut_plan_key},
                    config={
                        "silence_threshold_seconds": 0.8,
                        "keep_padding_before": 0.05,
                        "keep_padding_after": 0.05,
                        "min_keep_segment_seconds": 0.2,
                        "filler_padding_before": 0.05,
                        "filler_padding_after": 0.05,
                        "merge_adjacent_cuts_within_seconds": 0.1,
                    },
                )
            )
        )
        cut_plan = self.store.download_json(cut_plan_key)
        self.assertTrue(cut_plan["feature_enabled"])
        self.assertGreater(cut_plan["metrics"]["removed_filler_seconds"], 0.0)
        self.assertEqual(cut_plan["metrics"]["filler_word_count"], 1)
        self.assertGreater(
            cut_plan["metrics"]["total_removed_seconds"],
            cut_plan["metrics"]["removed_filler_seconds"],
            "silence cut should also have removed time on top of filler cut",
        )


if __name__ == "__main__":
    unittest.main()
