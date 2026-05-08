from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.render_plan_compiler.service import RenderPlanCompilerService


class RenderPlanCompilerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.request = RunRequest(
            job_id="job_test",
            step_id="render_plan_compiler",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "job_manifest": "jobs/job_test/manifests/job_manifest.json",
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "render_plan": "jobs/job_test/artifacts/render_plan.json",
            },
            config={
                "crop_representation": "keyframe_list",
                "audio_policy": "copy_if_possible_else_aac",
            },
        )
        self.store.upload_json(
            self.request.inputs["job_manifest"],
            {
                "input": {
                    "source_video": {"object_key": "jobs/job_test/input/source.mp4"},
                },
                "target_output": {
                    "object_key": "jobs/job_test/outputs/final_9x16.mp4",
                    "resolution": {"width": 1080, "height": 1920},
                },
            },
        )
        self.store.upload_json(
            self.request.inputs["artifact_manifest"],
            {
                "artifacts": {
                    "metadata": {"object_key": "jobs/job_test/artifacts/metadata.json"},
                    "reframe_plan_smooth": {
                        "object_key": "jobs/job_test/artifacts/reframe_plan_smooth.json"
                    },
                }
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/metadata.json",
            {
                "job_id": "job_test",
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "duration": 10.0,
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/reframe_plan_smooth.json",
            {
                "crop_width": 608,
                "crop_height": 1080,
                "source_resolution": {"width": 1920, "height": 1080},
                "target_resolution": {"width": 1080, "height": 1920},
                "keyframes": [
                    {"t": 0.0, "x": 100.0, "y": 0.0},
                    {"t": 1.0, "x": 200.0, "y": 0.0},
                ],
            },
        )
        self.service = RenderPlanCompilerService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_writes_render_plan_with_crop_plan(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        payload = self.store.download_json(self.request.expected_outputs["render_plan"])

        self.assertEqual(response.outputs["render_plan"], self.request.expected_outputs["render_plan"])
        self.assertEqual(payload["schema_version"], "1.0.0")
        self.assertEqual(payload["crop_representation"], "keyframe_list")
        self.assertEqual(payload["source_video"]["object_key"], "jobs/job_test/input/source.mp4")
        self.assertEqual(payload["output"]["object_key"], "jobs/job_test/outputs/final_9x16.mp4")
        self.assertEqual(payload["metadata"]["fps"], 30.0)
        self.assertEqual(len(payload["crop_plan"]["keyframes"]), 2)
        self.assertEqual(payload["render_mode"], "static_crop")


if __name__ == "__main__":
    unittest.main()
