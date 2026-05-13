"""Phase 3 audio enhancement service.

Reads ``extracted_audio.wav`` and produces ``enhanced_audio.wav`` after running
a CPU-only ffmpeg filter chain that combines:

* a high-pass filter (default 80 Hz) to remove HVAC rumble and DC bias,
* light FFT denoise (``afftdn``) when ``denoise_model`` is not ``off``, and
* optional EBU R128 loudness normalization (``loudnorm``) when
  ``loudness_normalization_enabled`` is true (default).

When high-pass is off, denoise is off, and loudness normalization is off, the
service copies ``extracted_audio.wav`` to ``enhanced_audio.wav`` without ffmpeg.

The output WAV keeps the same sample rate and channel layout as the input so
downstream services (``voice_activity_detection``, ``transcription``) can
consume it transparently.

Failure policy: any ffmpeg failure is degraded to a warning and the service
falls back to copying ``extracted_audio.wav`` to ``enhanced_audio.wav`` so the
rest of the pipeline can still proceed.
"""

from __future__ import annotations

import io
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


_VALID_DENOISE_MODELS = frozenset({"off", "std", "leaky"})


class AudioEnhancementService:
    service_id = "audio_enhancement"

    def run(self, context: ServiceContext) -> RunResponse:
        config = self._config(context)
        source_key = self._resolve_source_key(context)
        source_bytes = context.read_bytes(source_key)

        warnings: list[ServiceWarning] = []
        sample_rate, channels, duration = _probe_wav(source_bytes)
        if duration <= 0:
            raise ValueError("audio_enhancement received an empty audio stream")

        if _is_bypass(config):
            enhanced_bytes = source_bytes
            loudness_metrics: dict[str, float | None] = {"input_lufs": None, "output_lufs": None}
        else:
            try:
                enhanced_bytes, loudness_metrics = _run_ffmpeg_chain(
                    source_bytes,
                    sample_rate=sample_rate,
                    channels=channels,
                    config=config,
                )
            except _FfmpegFilterError as exc:
                warnings.append(
                    ServiceWarning(
                        code="AUDIO_ENHANCEMENT_FALLBACK",
                        message=(
                            "Audio enhancement filter chain failed; falling back to the "
                            f"raw extracted audio. Underlying error: {exc}"
                        ),
                        step=self.service_id,
                    )
                )
                enhanced_bytes = source_bytes
                loudness_metrics = {"input_lufs": None, "output_lufs": None}

        output_key = context.expected_output_key("enhanced_audio")
        context.write_bytes(output_key, enhanced_bytes, content_type="audio/wav")

        ln_on = bool(config.get("loudness_normalization_enabled", True))
        return RunResponse(
            service_id=self.service_id,
            outputs={"enhanced_audio": output_key},
            warnings=warnings,
            metrics={
                "sample_rate": sample_rate,
                "channels": channels,
                "duration_seconds": round(duration, 6),
                "denoise_model": config["denoise_model"],
                "target_lufs": (
                    float(config["target_lufs"])
                    if ln_on and config.get("target_lufs") is not None
                    else None
                ),
                "true_peak_db": (
                    float(config["true_peak_db"])
                    if ln_on and config.get("true_peak_db") is not None
                    else None
                ),
                "loudness_range": (
                    float(config["loudness_range"])
                    if ln_on and config.get("loudness_range") is not None
                    else None
                ),
                "highpass_frequency_hz": float(config["highpass_frequency_hz"]),
                "loudness_normalization_enabled": ln_on,
                "input_lufs": loudness_metrics.get("input_lufs"),
                "output_lufs": loudness_metrics.get("output_lufs"),
            },
        )

    def _resolve_source_key(self, context: ServiceContext) -> str:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if artifact_manifest_key and context.exists(artifact_manifest_key):
            artifact_manifest = context.read_json(artifact_manifest_key)
            entry = artifact_manifest.get("artifacts", {}).get("extracted_audio") or {}
            object_key = entry.get("object_key") if isinstance(entry, dict) else None
            if isinstance(object_key, str) and context.exists(object_key):
                return object_key

        try:
            return context.input_key("extracted_audio")
        except ValueError as exc:
            raise ValueError(
                "audio_enhancement requires either an artifact_manifest with "
                "extracted_audio or an explicit 'extracted_audio' input"
            ) from exc

    def _config(self, context: ServiceContext) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "denoise_model": "std",
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
            "highpass_frequency_hz": 80,
            "loudness_normalization_enabled": True,
        }
        defaults.update(context.request.config)

        ln = defaults.get("loudness_normalization_enabled", True)
        defaults["loudness_normalization_enabled"] = bool(ln)

        if defaults["loudness_normalization_enabled"]:
            defaults.setdefault("target_lufs", -16.0)
            defaults.setdefault("true_peak_db", -1.5)
            defaults.setdefault("loudness_range", 11.0)

        denoise = str(defaults["denoise_model"])
        if denoise not in _VALID_DENOISE_MODELS:
            allowed = ", ".join(sorted(_VALID_DENOISE_MODELS))
            raise ValueError(
                f"Invalid audio_enhancement.denoise_model '{denoise}'. Allowed: {allowed}"
            )
        defaults["denoise_model"] = denoise
        return defaults


class _FfmpegFilterError(RuntimeError):
    """Raised when the audio enhancement filter chain fails."""


def _is_bypass(config: dict[str, Any]) -> bool:
    if float(config["highpass_frequency_hz"]) > 0:
        return False
    if str(config["denoise_model"]) != "off":
        return False
    if bool(config.get("loudness_normalization_enabled", True)):
        return False
    return True


def _probe_wav(audio_bytes: bytes) -> tuple[int, int, float]:
    with io.BytesIO(audio_bytes) as buffer:
        with wave.open(buffer, "rb") as wav_in:
            sample_rate = wav_in.getframerate()
            channels = wav_in.getnchannels()
            n_frames = wav_in.getnframes()
    duration = (n_frames / float(sample_rate)) if sample_rate > 0 else 0.0
    return sample_rate, channels, duration


def _run_ffmpeg_chain(
    source_bytes: bytes,
    *,
    sample_rate: int,
    channels: int,
    config: dict[str, Any],
) -> tuple[bytes, dict[str, float | None]]:
    filter_chain = _build_filter_chain(config)
    with (
        tempfile.NamedTemporaryFile(suffix=".wav") as src_handle,
        tempfile.NamedTemporaryFile(suffix=".wav") as dst_handle,
    ):
        src_handle.write(source_bytes)
        src_handle.flush()

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src_handle.name),
            "-af",
            filter_chain,
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(dst_handle.name),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed"
            raise _FfmpegFilterError(detail)

        loudness = _parse_loudnorm_metrics(completed.stderr)
        return Path(dst_handle.name).read_bytes(), loudness


def _build_filter_chain(config: dict[str, Any]) -> str:
    filters: list[str] = []

    highpass_freq = float(config["highpass_frequency_hz"])
    if highpass_freq > 0:
        filters.append(f"highpass=f={int(round(highpass_freq))}")

    denoise_model = str(config["denoise_model"])
    if denoise_model != "off":
        filters.append("afftdn=nf=-25:nt=w")

    if bool(config.get("loudness_normalization_enabled", True)):
        target_lufs = float(config["target_lufs"])
        true_peak_db = float(config["true_peak_db"])
        loudness_range = float(config["loudness_range"])
        filters.append(
            "loudnorm="
            f"I={target_lufs:.2f}:TP={true_peak_db:.2f}:LRA={loudness_range:.2f}:print_format=json"
        )

    if not filters:
        return "anull"
    return ",".join(filters)


_LOUDNORM_KEYS = {
    "input_lufs": "input_i",
    "output_lufs": "output_i",
}


def _parse_loudnorm_metrics(stderr: str) -> dict[str, float | None]:
    """Best-effort parse of the ffmpeg ``loudnorm`` JSON metrics block.

    ``loudnorm=print_format=json`` writes a JSON document inside the stderr
    stream. We use a permissive regex so we degrade gracefully if ffmpeg's
    output format changes between releases.
    """
    metrics: dict[str, float | None] = {key: None for key in _LOUDNORM_KEYS}
    for metric_name, ffmpeg_key in _LOUDNORM_KEYS.items():
        match = re.search(rf'"{ffmpeg_key}"\s*:\s*"(?P<value>-?\d+(?:\.\d+)?)"', stderr)
        if match is not None:
            try:
                metrics[metric_name] = float(match.group("value"))
            except ValueError:
                metrics[metric_name] = None
    return metrics
