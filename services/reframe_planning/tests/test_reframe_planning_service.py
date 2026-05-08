from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.reframe_planning.service import ReframePlanningService


class ReframePlanningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="reframe_planning",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "reframe_plan_raw": "jobs/job_test/artifacts/reframe_plan_raw.json",
            },
        )
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "metadata": {"object_key": "jobs/job_test/artifacts/metadata.json"},
                    "body_tracks_interpolated": {"object_key": "jobs/job_test/artifacts/body_tracks_interpolated.json"},
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/metadata.json",
            {
                "width": 1920,
                "height": 1080,
                "target_crop": {"width": 608, "height": 1080},
                "target_resolution": {"width": 1080, "height": 1920},
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_interpolated.json",
            {
                "tracks": [
                    {
                        "frame_index": 0,
                        "t": 0.0,
                        "center": {"x": 300.0, "y": 520.0},
                        "confidence": 0.9,
                        "source": "detected",
                    },
                    {
                        "frame_index": 1,
                        "t": 0.2,
                        "center": {"x": 1700.0, "y": 520.0},
                        "confidence": 0.8,
                        "source": "detected",
                        "interpolated": True,
                    },
                ]
            },
        )
        self.service = ReframePlanningService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_builds_clamped_reframe_keyframes(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["reframe_plan_raw"])

        self.assertEqual(response.outputs["reframe_plan_raw"], self.request.expected_outputs["reframe_plan_raw"])
        self.assertEqual(payload["crop_width"], 608)
        self.assertEqual(payload["crop_height"], 1080)
        self.assertEqual(payload["keyframes"][0]["x"], 0.0)
        self.assertEqual(payload["keyframes"][1]["x"], 1312.0)
        self.assertEqual(payload["keyframes"][1]["y"], 0.0)
        self.assertTrue(payload["keyframes"][1]["interpolated"])
