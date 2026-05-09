"""Integration tests for the Phase 2 dead air cut planning FastAPI app."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from orchestrator.object_store import FilesystemObjectStore
from services.dead_air_cut_planning.api import create_app


class DeadAirCutPlanningApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))

        self.cut_plan_key = "jobs/job_test/artifacts/cut_plan.json"
        self.metadata_key = "jobs/job_test/artifacts/metadata.json"
        self.vad_key = "jobs/job_test/artifacts/vad_segments.json"
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.job_manifest_key = "jobs/job_test/manifests/job_manifest.json"

        self.store.upload_json(
            self.metadata_key,
            {"duration": 10.0, "fps": 30.0, "width": 1920, "height": 1080},
        )
        self.store.upload_json(
            self.vad_key,
            {
                "segments": [
                    {"start": 0.0, "end": 3.0, "type": "speech", "confidence": 0.9},
                    {"start": 3.0, "end": 7.0, "type": "silence", "confidence": 0.95},
                    {"start": 7.0, "end": 10.0, "type": "speech", "confidence": 0.9},
                ]
            },
        )
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "metadata": {"object_key": self.metadata_key},
                    "vad_segments": {"object_key": self.vad_key},
                }
            },
        )
        self.store.upload_json(
            self.job_manifest_key,
            {"job_id": "job_test", "enabled_features": {"remove_dead_air": True}},
        )

        self.previous_root = os.environ.get("SMART_CUT_OBJECT_STORE_ROOT")
        os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.temp_dir.name

        from fastapi.testclient import TestClient

        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        if self.previous_root is None:
            os.environ.pop("SMART_CUT_OBJECT_STORE_ROOT", None)
        else:
            os.environ["SMART_CUT_OBJECT_STORE_ROOT"] = self.previous_root
        self.temp_dir.cleanup()

    def test_run_endpoint_writes_cut_plan(self) -> None:
        response = self.client.post(
            "/run",
            json={
                "job_id": "job_test",
                "step_id": "dead_air_cut_planning",
                "minio": {"bucket": "smart-cut", "prefix": "jobs/job_test/"},
                "inputs": {
                    "job_manifest": self.job_manifest_key,
                    "artifact_manifest": self.artifact_manifest_key,
                },
                "expected_outputs": {"cut_plan": self.cut_plan_key},
                "config": {
                    "silence_threshold_seconds": 1.0,
                    "keep_padding_before": 0.0,
                    "keep_padding_after": 0.0,
                    "min_keep_segment_seconds": 0.0,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["outputs"], {"cut_plan": self.cut_plan_key})
        plan = self.store.download_json(self.cut_plan_key)
        self.assertEqual(len(plan["keep_segments"]), 2)
        self.assertEqual(plan["metrics"]["cut_count"], 1)


if __name__ == "__main__":
    unittest.main()
