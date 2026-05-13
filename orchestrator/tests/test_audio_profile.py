"""Tests for ``orchestrator.audio_profile`` merge helpers."""

from __future__ import annotations

import unittest

from orchestrator.audio_profile import merge_audio_enhancement_service_config


class AudioProfileMergeTests(unittest.TestCase):
    def test_social_profile_sets_target_lufs(self) -> None:
        base = {
            "denoise_model": "std",
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
            "highpass_frequency_hz": 80.0,
            "loudness_normalization_enabled": True,
        }
        merged = merge_audio_enhancement_service_config(
            base, profile_id="social", partial=None
        )
        self.assertEqual(merged["target_lufs"], -14.0)
        self.assertEqual(merged["denoise_model"], "off")
        self.assertEqual(merged["highpass_frequency_hz"], 0.0)

    def test_partial_overrides_profile(self) -> None:
        base = {
            "denoise_model": "std",
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
            "highpass_frequency_hz": 80.0,
            "loudness_normalization_enabled": True,
        }
        merged = merge_audio_enhancement_service_config(
            base,
            profile_id="podcast",
            partial={"target_lufs": -15.0},
        )
        self.assertEqual(merged["target_lufs"], -15.0)
        self.assertEqual(merged["denoise_model"], "off")

    def test_lufs_presets_default_to_loudnorm_only_no_denoise_highpass(self) -> None:
        base = {
            "denoise_model": "std",
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
            "highpass_frequency_hz": 80.0,
            "loudness_normalization_enabled": True,
        }
        merged = merge_audio_enhancement_service_config(
            base, profile_id="podcast", partial=None
        )
        self.assertEqual(merged["denoise_model"], "off")
        self.assertEqual(merged["highpass_frequency_hz"], 0.0)
        self.assertTrue(merged["loudness_normalization_enabled"])
        self.assertEqual(merged["target_lufs"], -16.0)

    def test_partial_denoise_std_restores_fft_denoise_for_lufs_preset(self) -> None:
        base = {
            "denoise_model": "std",
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
            "highpass_frequency_hz": 80.0,
            "loudness_normalization_enabled": True,
        }
        merged = merge_audio_enhancement_service_config(
            base,
            profile_id="podcast",
            partial={"denoise_model": "std"},
        )
        self.assertEqual(merged["denoise_model"], "std")

    def test_original_profile_drops_unused_loudnorm_fields(self) -> None:
        base = {
            "denoise_model": "std",
            "target_lufs": -16.0,
            "true_peak_db": -1.5,
            "loudness_range": 11.0,
            "highpass_frequency_hz": 80.0,
            "loudness_normalization_enabled": True,
        }
        merged = merge_audio_enhancement_service_config(
            base, profile_id="original", partial=None
        )
        self.assertEqual(merged["denoise_model"], "off")
        self.assertFalse(merged["loudness_normalization_enabled"])
        self.assertEqual(merged["highpass_frequency_hz"], 0.0)
        self.assertNotIn("target_lufs", merged)
        self.assertNotIn("true_peak_db", merged)
        self.assertNotIn("loudness_range", merged)

    def test_unknown_profile_raises(self) -> None:
        with self.assertRaises(ValueError):
            merge_audio_enhancement_service_config({}, profile_id="made_up", partial=None)


if __name__ == "__main__":
    unittest.main()
