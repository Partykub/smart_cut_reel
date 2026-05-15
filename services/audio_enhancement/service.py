"""Phase 3 audio enhancement service.

Reads ``extracted_audio.wav`` and produces ``enhanced_audio.wav`` after running
a CPU-only ffmpeg filter chain that combines:

* a high-pass filter (default 80 Hz) to remove HVAC rumble and DC bias,
* light FFT denoise (``afftdn``) when ``denoise_model`` is not ``off``, and
* optional EBU R128 loudness normalization (``loudnorm``) when
  ``loudness_normalization_enabled`` is true (default). When enabled, the
  service runs an **explicit two-pass** workflow (measurement to ``null``,
  then ``linear=true`` with ``measured_*`` from the JSON) so integrated
  loudness tracks ``I=`` more reliably than a single encode on some FFmpeg
  builds/material; pass 2 raises the ``LRA`` target when the source measured
  LRA exceeds the configured preset so linear mode is not forced back to
  dynamic; it falls back to one combined graph if pass 2 fails.

When high-pass is off, denoise is off, and loudness normalization is off, the
service copies ``extracted_audio.wav`` to ``enhanced_audio.wav`` without ffmpeg.

The output WAV keeps the same sample rate and channel layout as the input so
downstream services (``voice_activity_detection``, ``transcription``) can
consume it transparently.

Failure policy: any ffmpeg failure is degraded to a warning and the service
falls back to copying ``extracted_audio.wav`` to ``enhanced_audio.wav`` so the
rest of the pipeline can still proceed.

Optional **sample-peak window** (default ``-18`` … ``-14`` dBFS) uses ffmpeg
``astats`` overall *Peak level dB* as a practical stand-in for station “Audio
Level” specs. The service **always** runs that astats probe on the WAV after
the loudnorm/highpass/denoise chain and **before** any ``volume`` (peak-force)
pass, and records ``peak_sample_dbfs_pre_peak_force`` when the probe succeeds.
``peak_window_report_enabled`` only affects how aggressively we warn on probe
failure; it does not skip the pre-force measurement. ``peak_force_to_window_enabled`` applies one or more ``volume`` trim/boost passes until
the astats overall peak sits in the configured window (or a small pass limit is hit).
Positive gain is uncapped by default (``peak_force_max_boost_db`` = 0); set a positive
value only when you want to limit how much quiet material may be boosted.
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

_PEAK_LEVEL_LINE = re.compile(r"Peak level dB:\s*(-?\d+(?:\.\d+)?)")


class AudioEnhancementService:
    service_id = "audio_enhancement"

    def run(self, context: ServiceContext) -> RunResponse:
        config = self._config(context)
        source_key = self._resolve_source_key(context)
        source_bytes = context.read_bytes(source_key)

        warnings: list[ServiceWarning] = []
        loudnorm_diag: dict[str, Any] = {}
        sample_rate, channels, duration = _probe_wav(source_bytes)
        if duration <= 0:
            raise ValueError("audio_enhancement received an empty audio stream")

        if _is_bypass(config):
            enhanced_bytes = source_bytes
            loudness_metrics: dict[str, float | None] = {"input_lufs": None, "output_lufs": None}
        else:
            try:
                enhanced_bytes, loudness_metrics, loudnorm_diag = _run_ffmpeg_chain(
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
                loudnorm_diag = {}

        peak_report = bool(config.get("peak_window_report_enabled", True))
        peak_force = bool(config.get("peak_force_to_window_enabled", False))
        peak_low = float(config["peak_level_window_low_dbfs"])
        peak_high = float(config["peak_level_window_high_dbfs"])
        peak_gain_total = 0.0
        peak_force_applied = False
        peak_db: float | None = None
        peak_db_pre_peak_force: float | None = None
        peak_within: bool | None = None
        peak_within_pre_peak_force: bool | None = None

        # Always measure overall sample peak (ffmpeg astats) on the WAV leaving the
        # enhancement chain — i.e. after loudnorm (if any) and *before* the optional
        # peak-force volume pass. This must not be gated on peak_window_report_enabled
        # alone; otherwise peak-force can run without a persisted pre-force astats value.
        peak_db = _measure_wav_overall_peak_dbfs(enhanced_bytes)
        peak_db_pre_peak_force = peak_db
        if peak_db is None and (peak_report or peak_force):
            warnings.append(
                ServiceWarning(
                    code="AUDIO_PEAK_MEASURE_FAILED",
                    message="Could not measure sample peak (astats); peak window fields are null.",
                    step=self.service_id,
                )
            )
        if peak_db is not None:
            peak_within = peak_low <= peak_db <= peak_high
            peak_within_pre_peak_force = peak_within
        if peak_force and peak_db is not None:
            max_boost_db = float(config["peak_force_max_boost_db"])
            for _ in range(3):
                if peak_within:
                    break
                gain = _peak_window_gain_db(
                    peak_db,
                    low_dbfs=peak_low,
                    high_dbfs=peak_high,
                    max_boost_db=max_boost_db,
                )
                if abs(gain) < 1e-6:
                    break
                try:
                    enhanced_bytes = _apply_volume_gain_db(
                        enhanced_bytes,
                        gain_db=gain,
                        sample_rate=sample_rate,
                        channels=channels,
                    )
                    peak_gain_total += gain
                    peak_force_applied = True
                except _FfmpegFilterError as exc:
                    warnings.append(
                        ServiceWarning(
                            code="AUDIO_PEAK_FORCE_FAILED",
                            message=f"Peak-window gain pass failed; leaving prior audio. {exc}",
                            step=self.service_id,
                        )
                    )
                    break
                peak_db = _measure_wav_overall_peak_dbfs(enhanced_bytes)
                peak_within = peak_db is not None and peak_low <= peak_db <= peak_high
            if peak_force_applied and peak_within is False:
                warnings.append(
                    ServiceWarning(
                        code="AUDIO_PEAK_WINDOW_FORCE_INCOMPLETE",
                        message=(
                            "Peak force did not place overall peak inside the "
                            f"configured window [{peak_low}, {peak_high}] dBFS (astats)."
                        ),
                        step=self.service_id,
                    )
                )
            if peak_force_applied:
                warnings.append(
                    ServiceWarning(
                        code="AUDIO_PEAK_WINDOW_FORCE_LUFS_DRIFT",
                        message=(
                            "Peak-window gain was applied after loudness processing; "
                            "integrated LUFS may no longer match loudnorm targets."
                        ),
                        step=self.service_id,
                    )
                )

        output_key = context.expected_output_key("enhanced_audio")
        context.write_bytes(output_key, enhanced_bytes, content_type="audio/wav")

        ln_on = bool(config.get("loudness_normalization_enabled", True))
        fb = loudnorm_diag.get("loudnorm_fallback_reason")
        if fb == "measured_parse":
            warnings.append(
                ServiceWarning(
                    code="LOUDNORM_TWO_PASS_PARSE_FALLBACK",
                    message=(
                        "loudnorm pass-1 JSON did not yield all measured_* fields; "
                        "using a single-pass encode (integrated LUFS may miss I=)."
                    ),
                    step=self.service_id,
                )
            )
        elif fb == "pass2_encode":
            warnings.append(
                ServiceWarning(
                    code="LOUDNORM_TWO_PASS_ENCODE_FALLBACK",
                    message=(
                        "loudnorm linear pass 2 failed; using single-pass encode "
                        "(integrated LUFS may miss I=)."
                    ),
                    step=self.service_id,
                )
            )

        metrics: dict[str, Any] = {
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
                "peak_level_window_low_dbfs": peak_low,
                "peak_level_window_high_dbfs": peak_high,
                "peak_window_report_enabled": peak_report,
                "peak_force_to_window_enabled": peak_force,
                "peak_sample_dbfs_pre_peak_force": peak_db_pre_peak_force,
                "peak_within_window_pre_peak_force": peak_within_pre_peak_force,
                "peak_sample_dbfs": peak_db,
                "peak_within_window": peak_within,
                "peak_force_applied": peak_force_applied,
                "peak_force_gain_db_total": round(peak_gain_total, 4),
        }
        metrics.update(loudnorm_diag)
        return RunResponse(
            service_id=self.service_id,
            outputs={"enhanced_audio": output_key},
            warnings=warnings,
            metrics=metrics,
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
            "peak_level_window_low_dbfs": -18.0,
            "peak_level_window_high_dbfs": -14.0,
            "peak_window_report_enabled": True,
            "peak_force_to_window_enabled": False,
            "peak_force_max_boost_db": 0.0,
        }
        defaults.update(context.request.config)

        ln = defaults.get("loudness_normalization_enabled", True)
        defaults["loudness_normalization_enabled"] = bool(ln)

        if defaults["loudness_normalization_enabled"]:
            defaults.setdefault("target_lufs", -16.0)
            defaults.setdefault("true_peak_db", -1.5)
            defaults.setdefault("loudness_range", 11.0)

        defaults["peak_window_report_enabled"] = bool(defaults.get("peak_window_report_enabled", True))
        defaults["peak_force_to_window_enabled"] = bool(
            defaults.get("peak_force_to_window_enabled", False)
        )
        defaults["peak_level_window_low_dbfs"] = float(defaults["peak_level_window_low_dbfs"])
        defaults["peak_level_window_high_dbfs"] = float(defaults["peak_level_window_high_dbfs"])
        defaults["peak_force_max_boost_db"] = float(defaults["peak_force_max_boost_db"])

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
) -> tuple[bytes, dict[str, float | None], dict[str, Any]]:
    """Run the enhancement chain; ``loudnorm`` uses an explicit two-pass workflow.

    FFmpeg's ``loudnorm`` can report ``input_i`` ≈ ``output_i`` on some material
    when a single encode pass does not apply the linear-gain second stage
    reliably. We always run pass 1 to ``-f null`` (measurement JSON on stderr),
    then pass 2 with ``linear=true`` and ``measured_*`` from that JSON, matching
    the documented two-pass procedure. If measurement parsing or pass 2 fails,
    we fall back to one combined filter graph (previous behavior).

    Pass 2 uses ``LRA=max(configured LRA, measured input LRA)`` so FFmpeg's
    linear mode is not invalidated when the broadcast LRA target (7) is below
    the source's measured loudness range (common on speech + music beds).
    """
    if bool(config.get("loudness_normalization_enabled", True)):
        return _run_ffmpeg_chain_loudnorm_two_pass(
            source_bytes,
            sample_rate=sample_rate,
            channels=channels,
            config=config,
        )

    wav, loud, _ = _run_ffmpeg_chain_single_pass(
        source_bytes,
        sample_rate=sample_rate,
        channels=channels,
        filter_chain=_build_filter_chain(config),
    )
    return wav, loud, {"loudnorm_two_pass": False}


def _run_ffmpeg_chain_single_pass(
    source_bytes: bytes,
    *,
    sample_rate: int,
    channels: int,
    filter_chain: str,
) -> tuple[bytes, dict[str, float | None], dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "input.wav"
        dst = Path(tmp_dir) / "output.wav"
        src.write_bytes(source_bytes)

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(src),
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
            str(dst),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed"
            raise _FfmpegFilterError(detail)

        loudness = _parse_loudnorm_metrics(completed.stderr)
        return dst.read_bytes(), loudness, {}


def _run_ffmpeg_chain_loudnorm_two_pass(
    source_bytes: bytes,
    *,
    sample_rate: int,
    channels: int,
    config: dict[str, Any],
) -> tuple[bytes, dict[str, float | None], dict[str, Any]]:
    pre = _pre_loudnorm_filter_parts(config)
    pass1_token = _loudnorm_pass1_token(config)
    pass1_chain = _join_af_filters([*pre, pass1_token])
    fallback_chain = _build_filter_chain(config)

    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "input.wav"
        dst = Path(tmp_dir) / "output.wav"
        src.write_bytes(source_bytes)

        cmd1 = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(src),
            "-af",
            pass1_chain,
            "-f",
            "null",
            "-",
        ]
        completed1 = subprocess.run(cmd1, check=False, capture_output=True, text=True)
        if completed1.returncode != 0:
            detail = completed1.stderr.strip() or completed1.stdout.strip() or "ffmpeg loudnorm pass 1 failed"
            raise _FfmpegFilterError(detail)

        measured = _parse_loudnorm_measured_inputs(completed1.stderr)
        if measured is None:
            wav, loud, _ = _run_ffmpeg_chain_single_pass(
                source_bytes,
                sample_rate=sample_rate,
                channels=channels,
                filter_chain=fallback_chain,
            )
            return wav, loud, {
                "loudnorm_two_pass": True,
                "loudnorm_pass2_applied": False,
                "loudnorm_fallback_reason": "measured_parse",
            }

        pass2_token = _loudnorm_pass2_linear_token(config, measured)
        pass2_chain = _join_af_filters([*pre, pass2_token])
        cmd2 = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(src),
            "-af",
            pass2_chain,
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
        completed2 = subprocess.run(cmd2, check=False, capture_output=True, text=True)
        if completed2.returncode != 0:
            wav, loud, _ = _run_ffmpeg_chain_single_pass(
                source_bytes,
                sample_rate=sample_rate,
                channels=channels,
                filter_chain=fallback_chain,
            )
            return wav, loud, {
                "loudnorm_two_pass": True,
                "loudnorm_pass2_applied": False,
                "loudnorm_fallback_reason": "pass2_encode",
            }

        loudness = _parse_loudnorm_metrics(completed2.stderr)
        lra_eff = max(float(config["loudness_range"]), measured[2])
        return dst.read_bytes(), loudness, {
            "loudnorm_two_pass": True,
            "loudnorm_pass2_applied": True,
            "loudnorm_pass2_lra_effective": round(lra_eff, 4),
            "loudnorm_normalization_type": _last_loudnorm_normalization_type(
                completed2.stderr
            ),
        }


def _pre_loudnorm_filter_parts(config: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    highpass_freq = float(config["highpass_frequency_hz"])
    if highpass_freq > 0:
        parts.append(f"highpass=f={int(round(highpass_freq))}")
    denoise_model = str(config["denoise_model"])
    if denoise_model != "off":
        parts.append("afftdn=nf=-25:nt=w")
    return parts


def _loudnorm_pass1_token(config: dict[str, Any]) -> str:
    target_lufs = float(config["target_lufs"])
    true_peak_db = float(config["true_peak_db"])
    loudness_range = float(config["loudness_range"])
    return (
        "loudnorm="
        f"I={target_lufs:.2f}:TP={true_peak_db:.2f}:LRA={loudness_range:.2f}:print_format=json"
    )


def _loudnorm_pass2_linear_token(
    config: dict[str, Any],
    measured: tuple[float, float, float, float],
) -> str:
    mi, mtp, mlra, mth = measured
    target_lufs = float(config["target_lufs"])
    true_peak_db = float(config["true_peak_db"])
    lra_cfg = float(config["loudness_range"])
    # FFmpeg: target LRA must not be below the source measured LRA or linear mode
    # reverts to dynamic and may miss I= (common with broadcast LRA=7 on wide-range sources).
    lra_pass2 = max(lra_cfg, mlra)
    return (
        "loudnorm=linear=true:"
        f"I={target_lufs:.2f}:TP={true_peak_db:.2f}:LRA={lra_pass2:.2f}:"
        f"measured_I={mi:.6f}:measured_TP={mtp:.6f}:measured_LRA={mlra:.6f}:measured_thresh={mth:.6f}:"
        "print_format=json"
    )


def _join_af_filters(parts: list[str]) -> str:
    if not parts:
        return "anull"
    return ",".join(parts)


def _build_filter_chain(config: dict[str, Any]) -> str:
    parts = _pre_loudnorm_filter_parts(config)
    if bool(config.get("loudness_normalization_enabled", True)):
        parts.append(_loudnorm_pass1_token(config))
    return _join_af_filters(parts)


_LOUDNORM_KEYS = {
    "input_lufs": "input_i",
    "output_lufs": "output_i",
}

_LOUDNORM_MEASURED_INPUT_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh")


def _last_json_number(stderr: str, key: str) -> float | None:
    """Parse a numeric JSON field; try quoted string form first, then bare number."""
    quoted = list(
        re.finditer(rf'"{re.escape(key)}"\s*:\s*"(?P<value>-?\d+(?:\.\d+)?)"', stderr)
    )
    if quoted:
        try:
            return float(quoted[-1].group("value"))
        except ValueError:
            pass
    bare = list(re.finditer(rf'"{re.escape(key)}"\s*:\s*(?P<value>-?\d+(?:\.\d+)?)', stderr))
    if bare:
        try:
            return float(bare[-1].group("value"))
        except ValueError:
            return None
    return None


def _last_loudnorm_normalization_type(stderr: str) -> str | None:
    matches = list(
        re.finditer(r'"normalization_type"\s*:\s*"(?P<value>[^"]+)"', stderr)
    )
    if not matches:
        return None
    return matches[-1].group("value")


def _parse_loudnorm_measured_inputs(stderr: str) -> tuple[float, float, float, float] | None:
    """Parse ``input_*`` fields from the last ``loudnorm`` JSON block for pass 2 ``measured_*``."""
    vals: list[float] = []
    for key in _LOUDNORM_MEASURED_INPUT_KEYS:
        v = _last_json_number(stderr, key)
        if v is None:
            return None
        vals.append(v)
    return (vals[0], vals[1], vals[2], vals[3])


def _parse_astats_overall_peak_db(stderr: str) -> float | None:
    matches = _PEAK_LEVEL_LINE.findall(stderr)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _measure_wav_overall_peak_dbfs(wav_bytes: bytes) -> float | None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "probe.wav"
        src.write_bytes(wav_bytes)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(src),
            "-af",
            "astats=metadata=1:reset=1",
            "-f",
            "null",
            "-",
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            return None
        return _parse_astats_overall_peak_db(completed.stderr)


def _peak_window_gain_db(
    peak_dbfs: float,
    *,
    low_dbfs: float,
    high_dbfs: float,
    max_boost_db: float,
) -> float:
    """Return dB gain to move overall peak toward the configured window."""
    if peak_dbfs > high_dbfs:
        return high_dbfs - peak_dbfs
    if peak_dbfs < low_dbfs:
        mid = 0.5 * (low_dbfs + high_dbfs)
        raw = mid - peak_dbfs
        if max_boost_db > 0:
            return min(max_boost_db, raw)
        return raw
    return 0.0


def _apply_volume_gain_db(
    wav_bytes: bytes,
    *,
    gain_db: float,
    sample_rate: int,
    channels: int,
) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "in.wav"
        dst = Path(tmp_dir) / "out.wav"
        src.write_bytes(wav_bytes)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-y",
            "-i",
            str(src),
            "-af",
            f"volume={gain_db:.4f}dB",
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
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed"
            raise _FfmpegFilterError(detail)
        return dst.read_bytes()


def _parse_loudnorm_metrics(stderr: str) -> dict[str, float | None]:
    """Best-effort parse of the ffmpeg ``loudnorm`` JSON metrics block.

    ``loudnorm=print_format=json`` writes a JSON document inside the stderr
    stream. Some ffmpeg builds emit more than one JSON block; we take the
    **last** match for each field so we read the final pass, not an earlier
    analysis snapshot.
    """
    metrics: dict[str, float | None] = {key: None for key in _LOUDNORM_KEYS}
    for metric_name, ffmpeg_key in _LOUDNORM_KEYS.items():
        v = _last_json_number(stderr, ffmpeg_key)
        if v is not None:
            metrics[metric_name] = v
    return metrics
