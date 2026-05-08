from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.easing_smoothing.service import EasingSmoothingService
from services.easing_smoothing.service import smooth_keyframes


class EasingSmoothingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="easing_smoothing",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "reframe_plan_smooth": "jobs/job_test/artifacts/reframe_plan_smooth.json",
            },
        )
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "reframe_plan_raw": {"object_key": "jobs/job_test/artifacts/reframe_plan_raw.json"},
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/reframe_plan_raw.json",
            {
                "crop_width": 608,
                "crop_height": 1080,
                "source_resolution": {"width": 1920, "height": 1080},
                "target_resolution": {"width": 1080, "height": 1920},
                "keyframes": [
                    {"frame_index": 0, "t": 0.0, "x": 0.0, "y": 0.0, "confidence": 0.9},
                    {"frame_index": 1, "t": 0.2, "x": 100.0, "y": 0.0, "confidence": 0.9},
                    {"frame_index": 2, "t": 0.4, "x": 900.0, "y": 0.0, "confidence": 0.9},
                ],
            },
        )
        self.service = EasingSmoothingService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_smooths_large_movement_and_preserves_bounds(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["reframe_plan_smooth"])

        self.assertEqual(response.outputs["reframe_plan_smooth"], self.request.expected_outputs["reframe_plan_smooth"])
        self.assertEqual(payload["keyframes"][0]["x"], 0.0)
        self.assertGreater(payload["keyframes"][1]["x"], 0.0)
        self.assertLess(payload["keyframes"][1]["x"], 100.0)
        self.assertGreater(payload["keyframes"][2]["x"], 0.0)
        self.assertLess(payload["keyframes"][2]["x"], 900.0)
        self.assertTrue(payload["keyframes"][2]["smoothed"])

    def test_caps_dead_zone_for_small_crop_widths(self) -> None:
        keyframes = [
            {"frame_index": 0, "t": 0.0, "x": 161.08, "y": 0.0},
            {"frame_index": 1, "t": 0.2, "x": 74.94, "y": 0.0},
            {"frame_index": 2, "t": 0.4, "x": 74.94, "y": 0.0},
            {"frame_index": 3, "t": 0.6, "x": 74.94, "y": 0.0},
        ]

        smoothed = smooth_keyframes(
            keyframes=keyframes,
            crop_width=202,
            source_width=640,
            smoothing_strength=0.82,
            max_velocity_px_per_second=700.0,
            max_acceleration_px_per_second2=1600.0,
            dead_zone_px=80.0,
            easing="easeInOutCubic",
        )

        self.assertLess(smoothed[1]["x"], 161.08)
        self.assertLess(smoothed[2]["x"], smoothed[1]["x"])
        self.assertLess(smoothed[3]["x"], smoothed[2]["x"])

    def test_snaps_on_confirmed_subject_switch(self) -> None:
        keyframes = [
            {"frame_index": 0, "t": 9.8, "x": 232.79, "y": 0.0},
            {"frame_index": 1, "t": 10.0, "x": 232.70, "y": 0.0},
            {"frame_index": 2, "t": 10.2, "x": 232.33, "y": 0.0},
            {"frame_index": 3, "t": 10.4, "x": 232.14, "y": 0.0},
            {"frame_index": 4, "t": 10.6, "x": 332.19, "y": 0.0},
            {"frame_index": 5, "t": 10.8, "x": 322.71, "y": 0.0},
        ]

        smoothed = smooth_keyframes(
            keyframes=keyframes,
            crop_width=202,
            source_width=640,
            smoothing_strength=0.82,
            max_velocity_px_per_second=700.0,
            max_acceleration_px_per_second2=1600.0,
            dead_zone_px=80.0,
            easing="easeInOutCubic",
        )

        self.assertEqual(smoothed[4]["x"], 332.19)
