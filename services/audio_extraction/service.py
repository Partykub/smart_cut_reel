"""Phase 2 audio extraction service.

Reads ``source.mp4`` from the object store, decodes the master audio track to
mono PCM 16-bit WAV at the configured sample rate (default 16 kHz), and writes
``artifacts/extracted_audio.wav`` for downstream voice activity detection.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


_VALID_SAMPLE_RATES = frozenset({8000, 16000, 22050, 44100, 48000})
_VALID_CHANNEL_COUNTS = frozenset({1, 2})


def _has_audio_stream(probe: dict[str, Any]) -> bool:
    streams = probe.get("streams") or []
    if not isinstance(streams, list):
        return False
    return any(isinstance(stream, dict) and stream.get("codec_type") == "audio" for stream in streams)


class AudioExtractionService:
    service_id = "audio_extraction"

    def run(self, context: ServiceContext) -> RunResponse:
        source_key = context.input_key("source_video")
        source_bytes = context.read_bytes(source_key)

        probe_document = probe_video_bytes(source_bytes)
        if not _has_audio_stream(probe_document):
            raise ValueError(
                "source video has no audio stream — Phase 2 dead air cutting requires an audio track"
            )

        config = self._config(context)
        sample_rate = int(config["sample_rate"])
        channels = int(config["channels"])

        wav_bytes = _extract_audio_to_wav(
            source_bytes,
            sample_rate=sample_rate,
            channels=channels,
        )

        output_key = context.expected_output_key("extracted_audio")
        context.write_bytes(output_key, wav_bytes, content_type="audio/wav")
        return RunResponse(
            service_id=self.service_id,
            outputs={"extracted_audio": output_key},
        )

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "sample_rate": 16000,
            "channels": 1,
        }
        defaults.update(context.request.config)

        sample_rate = int(defaults["sample_rate"])
        if sample_rate not in _VALID_SAMPLE_RATES:
            allowed = ", ".join(str(rate) for rate in sorted(_VALID_SAMPLE_RATES))
            raise ValueError(f"Invalid sample_rate '{sample_rate}'. Allowed: {allowed}")

        channels = int(defaults["channels"])
        if channels not in _VALID_CHANNEL_COUNTS:
            allowed = ", ".join(str(count) for count in sorted(_VALID_CHANNEL_COUNTS))
            raise ValueError(f"Invalid channels '{channels}'. Allowed: {allowed}")

        defaults["sample_rate"] = sample_rate
        defaults["channels"] = channels
        return defaults


def _extract_audio_to_wav(source_bytes: bytes, *, sample_rate: int, channels: int) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "input.mp4"
        dst = Path(tmp_dir) / "output.wav"
        src.write_bytes(source_bytes)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(dst),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg audio extraction failed"
            raise ValueError(detail)

        return dst.read_bytes()
