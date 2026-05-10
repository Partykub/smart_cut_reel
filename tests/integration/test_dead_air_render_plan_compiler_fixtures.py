"""Drive the render-plan compiler with the canned dead-air fixtures.

This test wires the fixtures from ``fixtures/dead_air/{heavy_cut,light_cut,no_cut}``
through ``RenderPlanCompilerService`` to confirm the compiler emits a
``render_plan.json`` whose:

* ``segments`` exactly mirror the fixture's ``cut_plan.keep_segments``;
* ``metadata.rendered_duration`` matches ``cut_plan.metrics.total_kept_seconds``;
* ``segments[*].crop_keyframes`` are *segment-relative* and start at ``t=0``.

Together these assertions cover the primary contract between the dead-air
planner and the renderer, without requiring ffmpeg or any of the heavier
upstream services to run.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.render_plan_compiler.service import RenderPlanCompilerService


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "dead_air"


def _load(variant: str, name: str) -> dict:
    return json.loads((FIXTURE_ROOT / variant / name).read_text(encoding="utf-8"))


class _FixtureHarness:
    """Stage one dead-air fixture variant into a Filesystem-backed object store."""

    def __init__(self, variant: str, root: Path) -> None:
        self.variant = variant
        self.job_id = f"job_{variant}"
        self.store = FilesystemObjectStore(root)

        cut_plan = _load(variant, "cut_plan.json")
        smooth_plan = _load(variant, "reframe_plan_smooth.json")
        duration = float(cut_plan["source_duration_seconds"])

        self.cut_plan = cut_plan
        self.smooth_plan = smooth_plan
        self.duration = duration

        prefix = f"jobs/{self.job_id}"
        self.metadata_key = f"{prefix}/artifacts/metadata.json"
        self.smooth_key = f"{prefix}/artifacts/reframe_plan_smooth.json"
        self.cut_plan_key = f"{prefix}/artifacts/cut_plan.json"
        self.artifact_manifest_key = f"{prefix}/manifests/artifact_manifest.json"
        self.job_manifest_key = f"{prefix}/manifests/job_manifest.json"
        self.source_key = f"{prefix}/input/source.mp4"
        self.output_key = f"{prefix}/outputs/final_9x16.mp4"
        self.render_plan_key = f"{prefix}/artifacts/render_plan.json"

        self.store.upload_json(
            self.metadata_key,
            {
                "duration": duration,
                "fps": 30.0,
                "width": 1920,
                "height": 1080,
            },
        )
        self.store.upload_json(self.smooth_key, smooth_plan)
        self.store.upload_json(self.cut_plan_key, cut_plan)
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "schema_version": "2.0.0",
                "job_id": self.job_id,
                "updated_at": "2026-05-08T00:00:00Z",
                "artifacts": {
                    "metadata": {
                        "object_key": self.metadata_key,
                        "produced_by": "media_metadata",
                        "created_at": "2026-05-08T00:00:00Z",
                        "content_type": "application/json",
                    },
                    "reframe_plan_smooth": {
                        "object_key": self.smooth_key,
                        "produced_by": "easing_smoothing",
                        "created_at": "2026-05-08T00:00:00Z",
                        "content_type": "application/json",
                    },
                    "cut_plan": {
                        "object_key": self.cut_plan_key,
                        "produced_by": "dead_air_cut_planning",
                        "created_at": "2026-05-08T00:00:00Z",
                        "content_type": "application/json",
                    },
                },
            },
        )
        self.store.upload_json(
            self.job_manifest_key,
            {
                "schema_version": "2.0.0",
                "job_id": self.job_id,
                "input": {"source_video": {"object_key": self.source_key}},
                "target_output": {
                    "aspect_ratio": "9:16",
                    "resolution": {"width": 1080, "height": 1920},
                    "format": "mp4",
                    "object_key": self.output_key,
                },
                "enabled_features": {
                    "remove_dead_air": cut_plan.get("feature_enabled", False),
                },
            },
        )

    def request(self) -> RunRequest:
        return RunRequest(
            job_id=self.job_id,
            step_id="render_plan_compiler",
            minio=RunMinIO(bucket="smart-cut", prefix=f"jobs/{self.job_id}/"),
            inputs={
                "artifact_manifest": self.artifact_manifest_key,
                "job_manifest": self.job_manifest_key,
            },
            expected_outputs={"render_plan": self.render_plan_key},
            config={
                "crop_representation": "keyframe_list",
                "audio_policy": "aac_transcode",
                "compiler_render_mode": "smooth_crop_with_cuts",
            },
        )


class DeadAirRenderPlanCompilerFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_variant(self, variant: str) -> dict:
        harness = _FixtureHarness(variant, self.root / variant)
        service = RenderPlanCompilerService()
        service.run(build_context(harness.request(), harness.store))
        return harness.store.download_json(harness.render_plan_key), harness

    def test_heavy_cut_render_plan_matches_fixture_segments(self) -> None:
        plan, harness = self._run_variant("heavy_cut")
        expected_segments = harness.cut_plan["keep_segments"]
        self.assertEqual(plan["render_mode"], "smooth_crop_with_cuts")
        self.assertEqual(len(plan["segments"]), len(expected_segments))
        for plan_seg, fixture_seg in zip(plan["segments"], expected_segments):
            self.assertAlmostEqual(
                plan_seg["source_start"], fixture_seg["source_start"], places=4
            )
            self.assertAlmostEqual(
                plan_seg["source_end"], fixture_seg["source_end"], places=4
            )

        kept = sum(s["source_end"] - s["source_start"] for s in plan["segments"])
        self.assertAlmostEqual(
            plan["metadata"]["rendered_duration"], kept, places=4
        )
        self.assertAlmostEqual(
            plan["metadata"]["rendered_duration"],
            harness.cut_plan["metrics"]["total_kept_seconds"],
            places=4,
        )

    def test_light_cut_produces_two_segments_around_padded_silence(self) -> None:
        plan, harness = self._run_variant("light_cut")
        self.assertEqual(plan["render_mode"], "smooth_crop_with_cuts")
        self.assertEqual(len(plan["segments"]), 2)
        first, second = plan["segments"]
        self.assertAlmostEqual(first["source_start"], 0.0, places=4)
        self.assertGreater(second["source_start"], first["source_end"])
        kept = sum(s["source_end"] - s["source_start"] for s in plan["segments"])
        self.assertAlmostEqual(
            kept, harness.cut_plan["metrics"]["total_kept_seconds"], places=4
        )

    def test_no_cut_collapses_to_single_full_length_segment(self) -> None:
        plan, harness = self._run_variant("no_cut")
        self.assertEqual(plan["render_mode"], "smooth_crop_with_cuts")
        self.assertEqual(len(plan["segments"]), 1)
        only = plan["segments"][0]
        self.assertAlmostEqual(only["source_start"], 0.0, places=4)
        self.assertAlmostEqual(only["source_end"], harness.duration, places=4)
        self.assertAlmostEqual(
            plan["metadata"]["rendered_duration"], harness.duration, places=4
        )

    def test_each_segment_crop_keyframes_are_segment_relative(self) -> None:
        for variant in ("heavy_cut", "light_cut", "no_cut"):
            with self.subTest(variant=variant):
                plan, _ = self._run_variant(variant)
                for seg in plan["segments"]:
                    keyframes = seg["crop_keyframes"]
                    self.assertGreaterEqual(len(keyframes), 1)
                    self.assertAlmostEqual(
                        float(keyframes[0]["t"]), 0.0, places=4
                    )
                    seg_duration = seg["source_end"] - seg["source_start"]
                    self.assertLessEqual(
                        float(keyframes[-1]["t"]), seg_duration + 1e-3
                    )

    def test_compiler_rejects_missing_cut_plan(self) -> None:
        harness = _FixtureHarness("heavy_cut", self.root / "no_cut_plan")
        harness.store.upload_json(
            harness.artifact_manifest_key,
            {
                "schema_version": "2.0.0",
                "job_id": harness.job_id,
                "updated_at": "2026-05-08T00:00:00Z",
                "artifacts": {
                    "metadata": {
                        "object_key": harness.metadata_key,
                        "produced_by": "media_metadata",
                        "created_at": "2026-05-08T00:00:00Z",
                        "content_type": "application/json",
                    },
                    "reframe_plan_smooth": {
                        "object_key": harness.smooth_key,
                        "produced_by": "easing_smoothing",
                        "created_at": "2026-05-08T00:00:00Z",
                        "content_type": "application/json",
                    },
                },
            },
        )
        service = RenderPlanCompilerService()
        with self.assertRaises(ValueError):
            service.run(build_context(harness.request(), harness.store))


if __name__ == "__main__":
    unittest.main()
