from pathlib import Path
import tempfile
import unittest

from orchestrator.api import create_app
from orchestrator.object_store import FilesystemObjectStore
from orchestrator.service import OrchestratorService


class OrchestratorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = OrchestratorService(FilesystemObjectStore(Path(self.temp_dir.name)))

        from fastapi.testclient import TestClient

        self.client = TestClient(create_app(self.service))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_job_endpoint_creates_pending_job(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["job_id"].startswith("job_"))
        self.assertEqual(payload["service_status"]["status"], "pending")
        self.assertEqual(payload["paths"]["input"], f"jobs/{payload['job_id']}/input/source.mp4")

    def test_get_status_endpoint_reads_existing_job(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend"},
        ).json()

        response = self.client.get(f"/jobs/{created['job_id']}/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_id"], created["job_id"])
        self.assertEqual(payload["service_status"]["status"], "pending")

    def test_run_job_endpoint_uses_mock_runner(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend"},
        ).json()

        response = self.client.post(f"/jobs/{created['job_id']}/run")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["service_status"]["status"], "success")
        self.assertIsNone(payload["service_status"]["current_step"])
        self.assertEqual(payload["service_status"]["warnings"][0]["code"], "PIPELINE_RUNNER_MOCK")

    def test_status_endpoint_returns_not_found_for_unknown_job(self) -> None:
        response = self.client.get("/jobs/job_missing/status")

        self.assertEqual(response.status_code, 404)

    def test_get_artifact_returns_bytes_when_registered(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend"},
        ).json()
        job_id = created["job_id"]
        out_key = f"jobs/{job_id}/outputs/final_9x16.mp4"
        payload = b"\x00\x00\x00\x20ftypmp42"
        self.service.store.upload_bytes(out_key, payload, content_type="video/mp4")
        self.service.manifest_manager.register_artifact(job_id, "final_9x16")

        response = self.client.get(f"/jobs/{job_id}/artifacts/final_9x16")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, payload)
        self.assertIn("video", response.headers.get("content-type", ""))

    def test_get_artifact_not_found_when_missing(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend"},
        ).json()

        response = self.client.get(f"/jobs/{created['job_id']}/artifacts/final_9x16")

        self.assertEqual(response.status_code, 404)
