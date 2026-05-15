"""Map client ``audio_profile`` presets onto ``service_config.audio_enhancement``.

``podcast`` / ``social`` / ``broadcast`` default to **loudness normalization only**
(``loudnorm``): no FFT denoise and no high-pass, so timbre stays closer to the
source while still targeting platform LUFS. Optional ``denoise_model`` overrides
from the client can re-enable ``afftdn`` for noisy rooms.
"""

from __future__ import annotations

from typing import Any

KNOWN_AUDIO_PROFILE_IDS: frozenset[str] = frozenset(
    {"original", "podcast", "social", "broadcast"}
)

_AUDIO_ENHANCEMENT_KEYS: frozenset[str] = frozenset(
    {
        "denoise_model",
        "target_lufs",
        "true_peak_db",
        "loudness_range",
        "highpass_frequency_hz",
        "loudness_normalization_enabled",
        "peak_level_window_low_dbfs",
        "peak_level_window_high_dbfs",
        "peak_window_report_enabled",
        "peak_force_to_window_enabled",
        "peak_force_max_boost_db",
    }
)

_VALID_DENOISE = frozenset({"off", "std", "leaky"})

# Patches applied on top of the pipeline template's audio_enhancement (if any).
_PROFILE_PATCHES: dict[str, dict[str, Any]] = {
    "original": {
        "highpass_frequency_hz": 0.0,
        "denoise_model": "off",
        "loudness_normalization_enabled": False,
    },
    "podcast": {
        "denoise_model": "off",
        "target_lufs": -16.0,
        "true_peak_db": -1.5,
        "loudness_range": 11.0,
        "highpass_frequency_hz": 0.0,
        "loudness_normalization_enabled": True,
    },
    "social": {
        "denoise_model": "off",
        "target_lufs": -14.0,
        "true_peak_db": -1.5,
        "loudness_range": 11.0,
        "highpass_frequency_hz": 0.0,
        "loudness_normalization_enabled": True,
    },
    "broadcast": {
        "denoise_model": "off",
        "target_lufs": -23.0,
        "true_peak_db": -1.5,
        "loudness_range": 7.0,
        "highpass_frequency_hz": 0.0,
        "loudness_normalization_enabled": True,
    },
}


def merge_audio_enhancement_service_config(
    base: dict[str, Any],
    *,
    profile_id: str | None,
    partial: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a new dict: template ``base`` then profile patch then ``partial`` keys."""
    merged = dict(base)
    if profile_id is not None:
        if profile_id not in KNOWN_AUDIO_PROFILE_IDS:
            allowed = ", ".join(sorted(KNOWN_AUDIO_PROFILE_IDS))
            raise ValueError(
                f"Unknown audio_profile '{profile_id}'. Expected one of: {allowed}."
            )
        merged.update(_PROFILE_PATCHES[profile_id])
    if partial:
        for key, value in partial.items():
            if key not in _AUDIO_ENHANCEMENT_KEYS:
                raise ValueError(
                    f"Unknown key in audio_enhancement override: '{key}'. "
                    f"Allowed: {', '.join(sorted(_AUDIO_ENHANCEMENT_KEYS))}."
                )
            merged[key] = value
    if profile_id == "original":
        # Passthrough preset: do not persist template LUFS / TP / LRA anchors — they
        # implied a podcast-style target while loudnorm is off (confusing in UI/API).
        merged.pop("target_lufs", None)
        merged.pop("true_peak_db", None)
        merged.pop("loudness_range", None)
    _validate_audio_enhancement_dict(merged)
    return merged


def coerce_audio_enhancement_partial(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate a client JSON object for partial audio_enhancement overrides."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in _AUDIO_ENHANCEMENT_KEYS:
            raise ValueError(
                f"Unknown key in audio_enhancement override: '{key}'. "
                f"Allowed: {', '.join(sorted(_AUDIO_ENHANCEMENT_KEYS))}."
            )
        if key == "denoise_model":
            if not isinstance(value, str) or value not in _VALID_DENOISE:
                allowed = ", ".join(sorted(_VALID_DENOISE))
                raise ValueError(
                    f"audio_enhancement.denoise_model must be one of: {allowed}."
                )
            out[key] = value
        elif key in {"loudness_normalization_enabled", "peak_window_report_enabled", "peak_force_to_window_enabled"}:
            out[key] = bool(value)
        elif key in {
            "target_lufs",
            "true_peak_db",
            "loudness_range",
            "highpass_frequency_hz",
            "peak_level_window_low_dbfs",
            "peak_level_window_high_dbfs",
            "peak_force_max_boost_db",
        }:
            try:
                out[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"audio_enhancement.{key} must be a number."
                ) from exc
        else:
            out[key] = value
    if out:
        _validate_audio_enhancement_dict({**_podcast_defaults(), **out})
    return out


def _podcast_defaults() -> dict[str, Any]:
    return dict(_PROFILE_PATCHES["podcast"])


def _validate_audio_enhancement_dict(cfg: dict[str, Any]) -> None:
    denoise = str(cfg.get("denoise_model", "std"))
    if denoise not in _VALID_DENOISE:
        allowed = ", ".join(sorted(_VALID_DENOISE))
        raise ValueError(f"Invalid denoise_model '{denoise}'. Allowed: {allowed}.")
    if float(cfg.get("highpass_frequency_hz", 0)) < 0:
        raise ValueError("highpass_frequency_hz must be >= 0.")
    if float(cfg.get("loudness_range", 0)) < 0:
        raise ValueError("loudness_range must be >= 0.")
    low = float(cfg.get("peak_level_window_low_dbfs", -18.0))
    high = float(cfg.get("peak_level_window_high_dbfs", -14.0))
    if low >= high:
        raise ValueError("peak_level_window_low_dbfs must be < peak_level_window_high_dbfs (e.g. -18 and -14).")
    if float(cfg.get("peak_force_max_boost_db", 0.0)) < 0:
        raise ValueError("peak_force_max_boost_db must be >= 0 (0 = no boost cap).")
