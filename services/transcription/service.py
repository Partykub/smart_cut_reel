"""Phase 3 transcription service.

Uses ``faster-whisper`` (CTranslate2 backend) to produce word-level timestamps
for each speech segment detected by VAD. The output ``transcript.json``
artifact powers two downstream features:

* dead-air cut planning can match the configured filler-word dictionary against
  the transcript and cut those occurrences (Phase 3.L), and
* the debug frontend can display the transcript next to the timeline.

Design notes:

* The service prefers ``enhanced_audio.wav`` (denoised + loudness-normalised)
  when available and falls back to ``extracted_audio.wav``.
* ASR is restricted to the ``speech`` regions detected by VAD so we do not run
  the whisper decoder over silent segments.
* The faster-whisper model is loaded once per process under a lock and cached
  so the second ``/run`` call does not re-download or re-load weights.
* Failure policy: if model load or transcription fails the service still emits
  an empty transcript (no segments) and a warning so the rest of the Phase 3
  pipeline can proceed (filler-word cut becomes a no-op for that job).
"""

from __future__ import annotations

import threading
from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


TRANSCRIPT_SCHEMA_VERSION = "3.0.0"

_VALID_MODELS = frozenset(
    {
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
    }
)
_VALID_COMPUTE_TYPES = frozenset({"int8", "int8_float16", "float16", "float32"})

_DEFAULT_FILLER_WORDS_TH = ("เอ่อ", "อืม", "อ่า", "อ่ะ", "เอ้อ")
_DEFAULT_FILLER_WORDS_EN = ("um", "uh", "uhh", "uhm", "ah", "er", "erm")

_model_lock = threading.Lock()
_model_cache: dict[tuple[str, str], Any] = {}


class TranscriptionService:
    service_id = "transcription"

    def run(self, context: ServiceContext) -> RunResponse:
        config = self._config(context)
        warnings: list[ServiceWarning] = []

        audio_key, _audio_kind = self._resolve_audio_key(context)
        vad_payload = self._read_vad_payload(context)
        speech_intervals = _speech_intervals_from_vad(vad_payload)

        if not self._transcription_required(context):
            empty_payload = {
                "schema_version": TRANSCRIPT_SCHEMA_VERSION,
                "job_id": context.job_id,
                "audio_object_key": audio_key,
                "model": config["model"],
                "compute_type": config["compute_type"],
                "language": "skipped",
                "segments": [],
                "metrics": {
                    "total_words": 0,
                    "filler_word_count": 0,
                    "average_confidence": None,
                    "speech_segment_count_input": len(speech_intervals),
                    "skipped_reason": "remove_filler_words feature disabled",
                },
            }
            output_key = context.expected_output_key("transcript")
            context.write_json(output_key, empty_payload)
            return RunResponse(
                service_id=self.service_id,
                outputs={"transcript": output_key},
                warnings=warnings,
                metrics={
                    "skipped": True,
                    "reason": "remove_filler_words feature disabled",
                },
            )

        try:
            audio_bytes = context.read_bytes(audio_key)
            language = config["language"]
            segments_payload, detected_language = _transcribe_with_faster_whisper(
                audio_bytes=audio_bytes,
                model_name=config["model"],
                compute_type=config["compute_type"],
                language=None if language == "auto" else language,
                speech_intervals=speech_intervals,
            )
        except Exception as exc:  # noqa: BLE001 - we want a graceful degrade
            warnings.append(
                ServiceWarning(
                    code="TRANSCRIPTION_FAILED",
                    message=(
                        "faster-whisper transcription failed; emitting an empty "
                        f"transcript so the pipeline can continue. Error: {exc}"
                    ),
                    step=self.service_id,
                )
            )
            segments_payload = []
            detected_language = config["language"] if config["language"] != "auto" else "unknown"

        filler_set = _build_filler_set(config)
        filler_min_silence = float(config["filler_min_silence_around_seconds"])
        annotated_segments = _annotate_filler_words(
            segments=segments_payload,
            filler_set=filler_set,
            filler_min_silence_around_seconds=filler_min_silence,
        )

        total_words = sum(len(segment.get("words", [])) for segment in annotated_segments)
        filler_count = sum(
            1
            for segment in annotated_segments
            for word in segment.get("words", [])
            if word.get("is_filler") is True
        )
        confidences = [
            float(word["confidence"])
            for segment in annotated_segments
            for word in segment.get("words", [])
            if "confidence" in word
        ]
        average_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )

        payload = {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "job_id": context.job_id,
            "audio_object_key": audio_key,
            "model": config["model"],
            "compute_type": config["compute_type"],
            "language": detected_language,
            "segments": annotated_segments,
            "metrics": {
                "total_words": total_words,
                "filler_word_count": filler_count,
                "average_confidence": average_confidence,
                "speech_segment_count_input": len(speech_intervals),
            },
        }

        output_key = context.expected_output_key("transcript")
        context.write_json(output_key, payload)
        return RunResponse(
            service_id=self.service_id,
            outputs={"transcript": output_key},
            warnings=warnings,
            metrics={
                "total_words": total_words,
                "filler_word_count": filler_count,
                "language": detected_language,
            },
        )

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            # ``small`` is the default because it downloads quickly (~50 MB int8)
            # and is reliable to bootstrap on a fresh machine. For better Thai
            # accuracy, override to ``medium`` (or ``large-v3``) via the job
            # manifest after pre-downloading the model — first download of
            # ``medium`` takes ~2 min and can stall behind HuggingFace Hub
            # locks if the cache directory has stale state.
            "model": "small",
            "language": "auto",
            "compute_type": "int8",
            "filler_words_th": list(_DEFAULT_FILLER_WORDS_TH),
            "filler_words_en": list(_DEFAULT_FILLER_WORDS_EN),
            "filler_min_silence_around_seconds": 0.05,
        }
        defaults.update(context.request.config)

        if defaults["model"] not in _VALID_MODELS:
            raise ValueError(
                f"Invalid transcription.model '{defaults['model']}'. "
                f"Allowed: {', '.join(sorted(_VALID_MODELS))}"
            )
        if defaults["compute_type"] not in _VALID_COMPUTE_TYPES:
            raise ValueError(
                f"Invalid transcription.compute_type '{defaults['compute_type']}'. "
                f"Allowed: {', '.join(sorted(_VALID_COMPUTE_TYPES))}"
            )
        return defaults

    def _transcription_required(self, context: ServiceContext) -> bool:
        """Return ``True`` only when downstream features actually need ASR.

        Skipping the heavy faster-whisper inference when the user has not
        enabled ``remove_filler_words`` saves 30s–2min per Phase 3 job. The
        service still writes an empty ``transcript.json`` artifact so the
        ``dead_air_cut_planning`` step (and the frontend) sees a well-formed
        contract regardless.
        """
        try:
            job_manifest_key = context.input_key("job_manifest")
        except ValueError:
            return True
        if not context.exists(job_manifest_key):
            return True
        manifest = context.read_json(job_manifest_key)
        return bool(
            manifest.get("enabled_features", {}).get("remove_filler_words", False)
        )

    def _resolve_audio_key(self, context: ServiceContext) -> tuple[str, str]:
        manifest_artifacts = self._artifact_manifest_entries(context)
        for artifact_key in ("enhanced_audio", "extracted_audio"):
            entry = manifest_artifacts.get(artifact_key) or {}
            object_key = entry.get("object_key") if isinstance(entry, dict) else None
            if isinstance(object_key, str) and context.exists(object_key):
                return object_key, artifact_key
        for artifact_key in ("enhanced_audio", "extracted_audio"):
            try:
                resolved = context.input_key(artifact_key)
            except ValueError:
                continue
            if context.exists(resolved):
                return resolved, artifact_key
        raise ValueError(
            "transcription requires either enhanced_audio or extracted_audio in inputs or artifact manifest"
        )

    def _artifact_manifest_entries(self, context: ServiceContext) -> dict[str, Any]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if not artifact_manifest_key or not context.exists(artifact_manifest_key):
            return {}
        manifest = context.read_json(artifact_manifest_key)
        artifacts = manifest.get("artifacts", {}) if isinstance(manifest, dict) else {}
        return artifacts if isinstance(artifacts, dict) else {}

    def _read_vad_payload(self, context: ServiceContext) -> dict[str, Any]:
        manifest_artifacts = self._artifact_manifest_entries(context)
        vad_entry = manifest_artifacts.get("vad_segments") or {}
        if isinstance(vad_entry, dict):
            object_key = vad_entry.get("object_key")
            if isinstance(object_key, str) and context.exists(object_key):
                return context.read_json(object_key)
        try:
            vad_key = context.input_key("vad_segments")
        except ValueError:
            return {}
        if context.exists(vad_key):
            return context.read_json(vad_key)
        return {}


def _speech_intervals_from_vad(vad_payload: dict[str, Any]) -> list[tuple[float, float]]:
    segments = vad_payload.get("segments") if isinstance(vad_payload, dict) else None
    if not isinstance(segments, list):
        return []
    intervals: list[tuple[float, float]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if segment.get("type") != "speech":
            continue
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            intervals.append((start, end))
    return intervals


def _build_filler_set(config: dict[str, Any]) -> frozenset[str]:
    raw: list[str] = []
    for key in ("filler_words_th", "filler_words_en"):
        value = config.get(key)
        if isinstance(value, list):
            raw.extend(str(item) for item in value if isinstance(item, str))
    return frozenset(_normalize_filler_token(token) for token in raw if token)


def _normalize_filler_token(token: str) -> str:
    return token.strip().lower()


def _load_faster_whisper_model(model_name: str, compute_type: str) -> Any:
    cache_key = (model_name, compute_type)
    cached = _model_cache.get(cache_key)
    if cached is not None:
        return cached
    with _model_lock:
        cached = _model_cache.get(cache_key)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
        _model_cache[cache_key] = model
        return model


def warmup_model(
    *,
    model_name: str = "small",
    compute_type: str = "int8",
) -> tuple[bool, str | None]:
    """Trigger a one-shot model download/load so the first ``/run`` call is fast.

    Returns ``(ok, error_message)`` so callers can log a warning instead of
    crashing if the network is unavailable. Safe to call multiple times — the
    cache makes subsequent calls cheap.
    """
    try:
        _load_faster_whisper_model(model_name, compute_type)
    except Exception as exc:  # noqa: BLE001 - warmup must never crash startup
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def _transcribe_with_faster_whisper(
    *,
    audio_bytes: bytes,
    model_name: str,
    compute_type: str,
    language: str | None,
    speech_intervals: list[tuple[float, float]],
) -> tuple[list[dict[str, Any]], str]:
    import io
    import struct
    import wave

    import numpy as np

    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_in:
        sample_rate = wav_in.getframerate()
        channels = wav_in.getnchannels()
        sample_width = wav_in.getsampwidth()
        n_frames = wav_in.getnframes()
        raw = wav_in.readframes(n_frames)

    if sample_width != 2:
        raise ValueError(
            "transcription expects 16-bit PCM WAV input; got sample_width="
            f"{sample_width}"
        )
    total_samples = n_frames * channels
    pcm = np.array(struct.unpack(f"<{total_samples}h", raw), dtype=np.int16) if total_samples else np.zeros(0, dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    waveform = pcm.astype(np.float32) / 32768.0

    if speech_intervals:
        clip_specs = [
            (
                int(round(start * sample_rate)),
                int(round(end * sample_rate)),
                start,
            )
            for (start, end) in speech_intervals
        ]
    else:
        clip_specs = [(0, waveform.size, 0.0)]

    model = _load_faster_whisper_model(model_name, compute_type)
    aggregated_segments: list[dict[str, Any]] = []
    detected_language: str | None = language

    for start_sample, end_sample, offset_seconds in clip_specs:
        start_sample = max(0, start_sample)
        end_sample = min(waveform.size, end_sample)
        if end_sample <= start_sample:
            continue
        chunk = waveform[start_sample:end_sample]
        if chunk.size == 0:
            continue
        segments, info = model.transcribe(
            chunk,
            language=language,
            beam_size=1,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        if detected_language is None and getattr(info, "language", None):
            detected_language = info.language

        for segment in segments:
            words: list[dict[str, Any]] = []
            for word in (segment.words or []):
                if word.start is None or word.end is None:
                    continue
                words.append(
                    {
                        "word": str(word.word).strip(),
                        "start": round(float(word.start) + offset_seconds, 6),
                        "end": round(float(word.end) + offset_seconds, 6),
                        "confidence": (
                            round(float(word.probability), 4)
                            if word.probability is not None
                            else None
                        ),
                    }
                )
            if not words and (segment.start is None or segment.end is None):
                continue
            aggregated_segments.append(
                {
                    "start": round(float(segment.start or 0.0) + offset_seconds, 6),
                    "end": round(float(segment.end or 0.0) + offset_seconds, 6),
                    "text": str(segment.text).strip(),
                    "words": words,
                }
            )

    aggregated_segments.sort(key=lambda seg: seg["start"])
    return aggregated_segments, detected_language or "unknown"


def _annotate_filler_words(
    *,
    segments: list[dict[str, Any]],
    filler_set: frozenset[str],
    filler_min_silence_around_seconds: float,
) -> list[dict[str, Any]]:
    if not segments or not filler_set:
        return segments

    annotated: list[dict[str, Any]] = []
    for seg_idx, segment in enumerate(segments):
        words = list(segment.get("words", []))
        for word_idx, word in enumerate(words):
            cleaned = _normalize_filler_token(str(word.get("word", "")))
            if cleaned and cleaned in filler_set:
                if _has_silence_padding(
                    segments=segments,
                    seg_idx=seg_idx,
                    word_idx=word_idx,
                    min_silence=filler_min_silence_around_seconds,
                ):
                    word["is_filler"] = True
        annotated.append({**segment, "words": words})
    return annotated


def _has_silence_padding(
    *,
    segments: list[dict[str, Any]],
    seg_idx: int,
    word_idx: int,
    min_silence: float,
) -> bool:
    """Return ``True`` if both edges of the candidate word have at least
    ``min_silence`` seconds of silence (i.e., gap to the neighbouring word)."""
    if min_silence <= 0:
        return True

    segment = segments[seg_idx]
    words = segment.get("words", [])
    word = words[word_idx]
    word_start = float(word["start"])
    word_end = float(word["end"])

    prev_end: float | None = None
    if word_idx > 0:
        prev_end = float(words[word_idx - 1]["end"])
    elif seg_idx > 0:
        prev_words = segments[seg_idx - 1].get("words") or []
        if prev_words:
            prev_end = float(prev_words[-1]["end"])

    next_start: float | None = None
    if word_idx < len(words) - 1:
        next_start = float(words[word_idx + 1]["start"])
    elif seg_idx < len(segments) - 1:
        next_words = segments[seg_idx + 1].get("words") or []
        if next_words:
            next_start = float(next_words[0]["start"])

    if prev_end is not None and word_start - prev_end < min_silence:
        return False
    if next_start is not None and next_start - word_end < min_silence:
        return False
    return True
