from pathlib import Path
import tempfile
import unittest

from orchestrator.object_store import FilesystemObjectStore
from services.render_plan_compiler.api import create_app


class RenderPlanCompilerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.store.upload_json(
            "jobs/job_test/manifests/job_manifest.json",
            {
                "input": {"source_video": {"object_key": "jobs/job_test/input/source.mp4"}},
                "target_output": {
                    "object_key": "jobs/job_test/outputs/final_9x16.mp4",
                    "resolution": {"width": 1080, "height": 1920},
                },
            },
        )
        self.store.upload_json(
            "jobs/job_test/manifests/artifact_manifest.json",
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
            {"width": 1920, "height": 1080, "fps": 30.0, "duration": 5.0},
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/reframe_plan_smooth.json",
            {
                "crop_width": 608,
                "crop_height": 1080,
                "source_resolution": {"width": 1920, "height": 1080},
                "keyframes": [{"t": 0.0, "x": 50.0, "y": 0.0}],
            },
        )

        import os

        self.previous_root = os.environ.get("SMART_CUT_OBJECT_STORE_ROOT")
        os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.temp_dir.name

        from fastapi.testclient import TestClient

        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        import os

        if self.previous_root is None:
            os.environ.pop("SMART_CUT_OBJECT_STORE_ROOT", None)
        else:
            os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.previous_root
        self.temp_dir.cleanup()

    def test_run_returns_render_plan(self) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "render_plan_compiler",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "job_manifest": "jobs/job_test/manifests/job_manifest.json",
                    "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
                },
                "expected_outputs": {"render_plan": "jobs/job_test/artifacts/render_plan.json"},
                "config": {},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("render_plan", response.json()["outputs"])


if __name__ == "__main__":
    unittest.main()
