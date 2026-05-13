"""Phase 2 / Phase 3 voice activity detection service.

Reads ``extracted_audio.wav`` (PCM 16-bit, mono or stereo) — or the
``enhanced_audio.wav`` produced by the Phase 3 audio enhancement step when
present — and segments the timeline into ``speech`` / ``silence`` ranges.

Only **Silero VAD v5 (ONNX)** is supported:

* ``silero_v5`` (canonical) — Silero VAD via the official ``silero-vad`` package
  (bundled ONNX weights + ``onnxruntime``). Model is loaded lazily in-process
  and cached.
* ``silero_v4`` — backward-compat alias for older manifests; dispatches to the
  same v5 inference path and records ``silero_v4`` in the artifact ``model``
  field when requested.

Downstream services (``dead_air_cut_planning``, frontend) only rely on the
``segments`` shape, not the model id.
"""

from __future__ import annotations

import io
import struct
import threading
import wave
from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


VAD_SCHEMA_VERSION = "3.0.0"

_SUPPORTED_MODELS = frozenset({"silero_v4", "silero_v5"})

_VALID_AUDIO_SOURCES = frozenset(
    {"extracted_audio", "enhanced_audio", "enhanced_audio_or_extracted"}
)

_SILERO_TARGET_SAMPLE_RATES = (16000, 8000)

_silero_lock = threading.Lock()
_silero_cache: dict[str, Any] = {}


class VoiceActivityDetectionService:
    service_id = "voice_activity_detection"

    def run(self, context: ServiceContext) -> RunResponse:
        config = self._config(context)
        backend = config["model"]
        if backend not in _SUPPORTED_MODELS:
            raise ValueError(
                f"Invalid voice_activity_detection model '{backend}'. "
                f"Supported: {', '.join(sorted(_SUPPORTED_MODELS))}"
            )

        audio_source_pref = config["audio_source"]
        if audio_source_pref not in _VALID_AUDIO_SOURCES:
            raise ValueError(
                f"Invalid voice_activity_detection.audio_source '{audio_source_pref}'. "
                f"Supported: {', '.join(sorted(_VALID_AUDIO_SOURCES))}"
            )

        audio_key, resolved_audio_kind = self._resolve_audio_key(
            context, audio_source_pref
        )
        audio_bytes = context.read_bytes(audio_key)

        warnings: list[ServiceWarning] = []
        sample_rate, channels, _, duration_seconds = _read_wav(audio_bytes)
        if duration_seconds <= 0:
            raise ValueError("audio source has zero duration")

        segments, backend_extras = self._run_silero_backend(
            audio_bytes=audio_bytes,
            duration_seconds=duration_seconds,
            config=config,
        )

        speech_total = sum(seg["end"] - seg["start"] for seg in segments if seg["type"] == "speech")
        silence_total = sum(seg["end"] - seg["start"] for seg in segments if seg["type"] == "silence")

        if speech_total == 0:
            warnings.append(
                ServiceWarning(
                    code="VAD_NO_SPEECH_DETECTED",
                    message="No speech detected in the audio. Downstream cut planning will treat the clip as silent.",
                    step=self.service_id,
                )
            )
        elif silence_total == 0:
            warnings.append(
                ServiceWarning(
                    code="VAD_NO_SILENCE_DETECTED",
                    message="No silence detected. Dead air cut planning will produce an identity plan.",
                    step=self.service_id,
                )
            )

        payload: dict[str, Any] = {
            "schema_version": VAD_SCHEMA_VERSION,
            "job_id": context.job_id,
            "model": backend,
            "audio_source_kind": resolved_audio_kind,
            "audio_object_key": audio_key,
            "sample_rate": sample_rate,
            "channels": channels,
            "duration_seconds": round(duration_seconds, 6),
            "segments": segments,
            "metrics": {
                "total_speech_seconds": round(speech_total, 6),
                "total_silence_seconds": round(silence_total, 6),
                "speech_segment_count": sum(1 for seg in segments if seg["type"] == "speech"),
                "silence_segment_count": sum(1 for seg in segments if seg["type"] == "silence"),
            },
        }
        payload.update(backend_extras)

        output_key = context.expected_output_key("vad_segments")
        context.write_json(output_key, payload)
        return RunResponse(
            service_id=self.service_id,
            outputs={"vad_segments": output_key},
            warnings=warnings,
        )

    def _resolve_audio_key(
        self, context: ServiceContext, audio_source_pref: str
    ) -> tuple[str, str]:
        manifest_artifacts = self._artifact_manifest_entries(context)
        candidates: list[str] = []
        if audio_source_pref == "enhanced_audio":
            candidates = ["enhanced_audio"]
        elif audio_source_pref == "extracted_audio":
            candidates = ["extracted_audio"]
        else:
            candidates = ["enhanced_audio", "extracted_audio"]

        for artifact_key in candidates:
            entry = manifest_artifacts.get(artifact_key) or {}
            object_key = entry.get("object_key") if isinstance(entry, dict) else None
            if isinstance(object_key, str) and context.exists(object_key):
                return object_key, artifact_key

        for artifact_key in candidates:
            try:
                resolved = context.input_key(artifact_key)
            except ValueError:
                continue
            if context.exists(resolved):
                return resolved, artifact_key

        raise ValueError(
            "voice_activity_detection could not locate audio input. Expected one of "
            f"{', '.join(candidates)} in inputs or artifact manifest."
        )

    def _artifact_manifest_entries(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            return {}
        manifest = context.read_json(artifact_manifest_key)
        artifacts = manifest.get("artifacts", {}) if isinstance(manifest, dict) else {}
        return artifacts if isinstance(artifacts, dict) else {}

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "model": "silero_v5",
            "audio_source": "enhanced_audio_or_extracted",
            "speech_threshold": 0.5,
            "min_speech_duration_seconds": 0.25,
            "min_silence_duration_seconds": 0.2,
            "speech_pad_seconds": 0.05,
        }
        return {**defaults, **context.request.config}

    def _run_silero_backend(
        self,
        *,
        audio_bytes: bytes,
        duration_seconds: float,
        config: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        speech_threshold = float(config["speech_threshold"])
        if not 0.0 <= speech_threshold <= 1.0:
            raise ValueError("speech_threshold must be in [0, 1]")
        min_speech = float(config["min_speech_duration_seconds"])
        min_silence = float(config["min_silence_duration_seconds"])
        speech_pad = float(config["speech_pad_seconds"])

        waveform, target_sample_rate = _load_waveform_for_silero(audio_bytes)
        speech_chunks = _silero_speech_timestamps(
            waveform=waveform,
            sample_rate=target_sample_rate,
            speech_threshold=speech_threshold,
            min_speech_duration_seconds=min_speech,
            min_silence_duration_seconds=min_silence,
            speech_pad_seconds=speech_pad,
        )
        segments = _segments_from_silero_chunks(
            speech_chunks=speech_chunks,
            duration_seconds=duration_seconds,
        )
        extras = {
            "speech_threshold": speech_threshold,
            "min_speech_duration_seconds": min_speech,
            "min_silence_duration_seconds": min_silence,
            "speech_pad_seconds": speech_pad,
            "silero_sample_rate": target_sample_rate,
        }
        return segments, extras


def _read_wav(audio_bytes: bytes) -> tuple[int, int, list[int], float]:
    """Decode a PCM 16-bit WAV into per-sample integers.

    Returns ``(sample_rate, channels, samples, duration_seconds)``. ``samples``
    is interleaved if the stream is stereo (mono mean used when loading for Silero).
    """
    with io.BytesIO(audio_bytes) as buffer:
        with wave.open(buffer, "rb") as wav_in:
            sample_rate = wav_in.getframerate()
            channels = wav_in.getnchannels()
            sample_width = wav_in.getsampwidth()
            n_frames = wav_in.getnframes()
            raw = wav_in.readframes(n_frames)

    if sample_width != 2:
        raise ValueError(
            f"voice_activity_detection requires 16-bit PCM WAV; got sample_width={sample_width} bytes"
        )

    total_samples = n_frames * channels
    samples: list[int] = list(struct.unpack(f"<{total_samples}h", raw)) if total_samples else []
    duration_seconds = (n_frames / float(sample_rate)) if sample_rate > 0 else 0.0
    return sample_rate, channels, samples, duration_seconds


def _load_silero_model() -> Any:
    """Load (and cache) the bundled Silero VAD ONNX model.

    The ``silero-vad`` package ships the ONNX weights and the ``onnxruntime``
    backend; we load it once per process under a lock so concurrent /run
    requests do not race on first use.
    """
    cached = _silero_cache.get("model")
    if cached is not None:
        return cached
    with _silero_lock:
        cached = _silero_cache.get("model")
        if cached is not None:
            return cached
        from silero_vad import load_silero_vad

        model = load_silero_vad(onnx=True)
        _silero_cache["model"] = model
        return model


def warmup_silero_model() -> tuple[bool, str | None]:
    """Trigger one-shot Silero VAD model load on service startup.

    Returns ``(ok, error_message)`` so a failed warmup degrades gracefully
    (the first successful ``/run`` will load the model if warmup failed).
    """
    try:
        _load_silero_model()
    except Exception as exc:  # noqa: BLE001 - warmup must never crash startup
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def _load_waveform_for_silero(audio_bytes: bytes) -> tuple["Any", int]:
    """Decode WAV → mono float32 ``torch.Tensor`` accepted by Silero.

    Silero VAD v5 expects 16 kHz or 8 kHz mono float32 audio in [-1, 1]. We
    resample to 16 kHz when the source rate is unsupported.
    """
    import numpy as np
    import torch

    sample_rate, channels, samples, _ = _read_wav(audio_bytes)
    if not samples:
        raise ValueError("audio source has no samples for Silero VAD")

    array = np.asarray(samples, dtype=np.int16)
    if channels > 1:
        array = array.reshape(-1, channels).mean(axis=1)
    waveform = array.astype(np.float32) / 32768.0
    waveform = np.clip(waveform, -1.0, 1.0)

    if sample_rate not in _SILERO_TARGET_SAMPLE_RATES:
        target = 16000
        if waveform.size == 0:
            return torch.from_numpy(waveform), target
        new_length = max(1, int(round(waveform.size * (target / float(sample_rate)))))
        original_indices = np.linspace(0, waveform.size - 1, num=waveform.size)
        target_indices = np.linspace(0, waveform.size - 1, num=new_length)
        waveform = np.interp(target_indices, original_indices, waveform).astype(np.float32)
        sample_rate = target

    return torch.from_numpy(waveform), sample_rate


def _silero_speech_timestamps(
    *,
    waveform: Any,
    sample_rate: int,
    speech_threshold: float,
    min_speech_duration_seconds: float,
    min_silence_duration_seconds: float,
    speech_pad_seconds: float,
) -> list[dict[str, float]]:
    from silero_vad import get_speech_timestamps

    model = _load_silero_model()
    raw = get_speech_timestamps(
        waveform,
        model,
        sampling_rate=sample_rate,
        threshold=speech_threshold,
        min_speech_duration_ms=int(round(min_speech_duration_seconds * 1000)),
        min_silence_duration_ms=int(round(min_silence_duration_seconds * 1000)),
        speech_pad_ms=int(round(speech_pad_seconds * 1000)),
        return_seconds=True,
    )
    chunks: list[dict[str, float]] = []
    for entry in raw:
        if isinstance(entry, dict) and "start" in entry and "end" in entry:
            start = float(entry["start"])
            end = float(entry["end"])
            if end > start:
                chunks.append({"start": start, "end": end})
    return chunks


def _segments_from_silero_chunks(
    *,
    speech_chunks: list[dict[str, float]],
    duration_seconds: float,
) -> list[dict[str, Any]]:
    """Convert Silero ``[{start, end}]`` speech list to alternating segments
    that cover the full clip (so dead-air planning has a complete timeline).
    """
    if not speech_chunks:
        return [
            {
                "start": 0.0,
                "end": round(duration_seconds, 6),
                "type": "silence",
                "confidence": 1.0,
            }
        ]

    chunks = sorted(
        ({"start": max(0.0, float(c["start"])), "end": min(duration_seconds, float(c["end"]))} for c in speech_chunks),
        key=lambda c: c["start"],
    )

    segments: list[dict[str, Any]] = []
    cursor = 0.0
    for chunk in chunks:
        start = chunk["start"]
        end = chunk["end"]
        if end <= cursor:
            continue
        if start > cursor:
            segments.append(
                {
                    "start": round(cursor, 6),
                    "end": round(start, 6),
                    "type": "silence",
                    "confidence": 0.95,
                }
            )
        segments.append(
            {
                "start": round(max(start, cursor), 6),
                "end": round(end, 6),
                "type": "speech",
                "confidence": 0.95,
            }
        )
        cursor = end

    if cursor < duration_seconds:
        segments.append(
            {
                "start": round(cursor, 6),
                "end": round(duration_seconds, 6),
                "type": "silence",
                "confidence": 0.95,
            }
        )

    if segments:
        segments[-1]["end"] = round(duration_seconds, 6)

    return segments
