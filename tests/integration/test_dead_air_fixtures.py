"""Validate that the canned dead-air fixtures match the contract schemas
and satisfy the invariants the downstream services rely on.

Each fixture variant must:

1. Parse as JSON.
2. Match the high-level shape that the producing service writes
   (``vad_segments.json`` / ``cut_plan.json`` / ``reframe_plan_smooth.json``).
3. Have internally consistent metrics — i.e. the metrics in ``cut_plan.json``
   actually reflect the ``keep_segments`` listed.
4. Stay inside ``[0, source_duration_seconds]`` and never overlap.

This is the QA harness referenced by P2-I04 in the Phase 2 todo. It pins the
fixtures so they cannot silently drift away from the contract; if you change
either contract or fixture you must update both.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "dead_air"
VARIANTS = ("heavy_cut", "light_cut", "no_cut")


def _load(variant: str, name: str) -> dict:
    return json.loads((FIXTURE_ROOT / variant / name).read_text(encoding="utf-8"))


class DeadAirFixtureShapeTests(unittest.TestCase):
    def test_each_variant_provides_three_artifacts(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                base = FIXTURE_ROOT / variant
                self.assertTrue((base / "vad_segments.json").is_file())
                self.assertTrue((base / "cut_plan.json").is_file())
                self.assertTrue((base / "reframe_plan_smooth.json").is_file())


class DeadAirVadSegmentsTests(unittest.TestCase):
    def test_segments_cover_full_duration_without_gaps(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                payload = _load(variant, "vad_segments.json")
                self.assertEqual(payload["schema_version"], "2.0.0")
                self.assertEqual(payload["model"], "energy")
                duration = float(payload["duration_seconds"])
                segments = payload["segments"]
                self.assertGreater(len(segments), 0)

                self.assertEqual(float(segments[0]["start"]), 0.0)
                self.assertAlmostEqual(float(segments[-1]["end"]), duration, places=6)

                for prev, curr in zip(segments, segments[1:]):
                    self.assertAlmostEqual(
                        float(prev["end"]),
                        float(curr["start"]),
                        places=6,
                        msg="VAD segments must be contiguous",
                    )

                for seg in segments:
                    self.assertIn(seg["type"], {"speech", "silence"})

    def test_metrics_match_segments(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                payload = _load(variant, "vad_segments.json")
                segments = payload["segments"]
                speech_total = sum(
                    float(seg["end"]) - float(seg["start"])
                    for seg in segments
                    if seg["type"] == "speech"
                )
                silence_total = sum(
                    float(seg["end"]) - float(seg["start"])
                    for seg in segments
                    if seg["type"] == "silence"
                )
                metrics = payload["metrics"]
                self.assertAlmostEqual(metrics["total_speech_seconds"], speech_total, places=6)
                self.assertAlmostEqual(metrics["total_silence_seconds"], silence_total, places=6)
                self.assertEqual(
                    metrics["speech_segment_count"],
                    sum(1 for seg in segments if seg["type"] == "speech"),
                )
                self.assertEqual(
                    metrics["silence_segment_count"],
                    sum(1 for seg in segments if seg["type"] == "silence"),
                )


class DeadAirCutPlanTests(unittest.TestCase):
    def test_keep_segments_stay_inside_source_and_are_sorted(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                payload = _load(variant, "cut_plan.json")
                duration = float(payload["source_duration_seconds"])
                segs = payload["keep_segments"]
                self.assertGreater(len(segs), 0)
                last_end = -1.0
                for seg in segs:
                    start = float(seg["source_start"])
                    end = float(seg["source_end"])
                    self.assertGreaterEqual(start, 0.0)
                    self.assertLessEqual(end, duration + 1e-6)
                    self.assertGreater(end, start)
                    self.assertGreaterEqual(start, last_end - 1e-6)
                    last_end = end

    def test_metrics_match_keep_segments(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                payload = _load(variant, "cut_plan.json")
                duration = float(payload["source_duration_seconds"])
                segs = payload["keep_segments"]
                kept = sum(float(s["source_end"]) - float(s["source_start"]) for s in segs)
                removed = duration - kept
                metrics = payload["metrics"]
                self.assertAlmostEqual(metrics["total_kept_seconds"], kept, places=4)
                self.assertAlmostEqual(metrics["total_removed_seconds"], removed, places=4)
                self.assertEqual(metrics["cut_count"], max(0, len(segs) - 1))
                self.assertAlmostEqual(
                    metrics["compression_ratio"], kept / duration, places=4
                )

    def test_no_cut_variant_is_identity_plan(self) -> None:
        payload = _load("no_cut", "cut_plan.json")
        self.assertFalse(payload["feature_enabled"])
        self.assertEqual(len(payload["keep_segments"]), 1)
        self.assertEqual(payload["metrics"]["cut_count"], 0)
        self.assertAlmostEqual(payload["metrics"]["compression_ratio"], 1.0, places=6)

    def test_heavy_cut_drops_more_than_half_the_clip(self) -> None:
        payload = _load("heavy_cut", "cut_plan.json")
        ratio = payload["metrics"]["compression_ratio"]
        self.assertTrue(payload["feature_enabled"])
        self.assertLess(ratio, 0.5, "heavy_cut fixture should keep < 50% of source")
        self.assertGreater(payload["metrics"]["cut_count"], 1)

    def test_light_cut_keeps_most_of_the_clip(self) -> None:
        payload = _load("light_cut", "cut_plan.json")
        ratio = payload["metrics"]["compression_ratio"]
        self.assertTrue(payload["feature_enabled"])
        self.assertGreater(ratio, 0.9, "light_cut fixture should keep > 90% of source")
        self.assertEqual(payload["metrics"]["cut_count"], 1)


class DeadAirReframePlanTests(unittest.TestCase):
    def test_keyframes_cover_source_timeline(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                payload = _load(variant, "reframe_plan_smooth.json")
                duration = float(_load(variant, "cut_plan.json")["source_duration_seconds"])
                keyframes = payload["keyframes"]
                self.assertGreater(len(keyframes), 1)
                self.assertAlmostEqual(float(keyframes[0]["t"]), 0.0, places=6)
                self.assertGreaterEqual(float(keyframes[-1]["t"]), duration - 1e-6)
                last_t = -math.inf
                for kf in keyframes:
                    self.assertGreaterEqual(float(kf["t"]), last_t)
                    last_t = float(kf["t"])
                    self.assertTrue(kf.get("smoothed"))

    def test_crop_dimensions_are_consistent(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                payload = _load(variant, "reframe_plan_smooth.json")
                self.assertEqual(payload["crop_width"], 608)
                self.assertEqual(payload["crop_height"], 1080)
                self.assertEqual(payload["source_resolution"], {"width": 1920, "height": 1080})


if __name__ == "__main__":
    unittest.main()
