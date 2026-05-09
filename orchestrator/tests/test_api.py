import json
import tempfile
import threading
import unittest
from pathlib import Path

from orchestrator.api import create_app
from orchestrator.object_store import FilesystemObjectStore
from orchestrator.pipeline_runner import MockPipelineRunner
from orchestrator.service import OrchestratorService


class BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, *, job_id: str, manifest_manager, artifact_helper) -> dict:
        del artifact_helper
        manifest_manager.set_step_state(
            job_id,
            "validation",
            step_status="running",
            started_at="2026-05-08T00:00:00Z",
            overall_status="running",
            current_step="validation",
        )
        self.started.set()
        self.release.wait(timeout=5)
        return manifest_manager.read_service_status(job_id)


class OrchestratorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = OrchestratorService(
            FilesystemObjectStore(Path(self.temp_dir.name)),
            runner=MockPipelineRunner(),
        )

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

    def test_status_endpoint_stays_available_while_run_is_executing(self) -> None:
        runner = BlockingRunner()
        service = OrchestratorService(
            FilesystemObjectStore(Path(self.temp_dir.name)),
            runner=runner,
        )

        from fastapi.testclient import TestClient

        client = TestClient(create_app(service))
        created = client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend"},
        ).json()

        run_response: dict[str, object] = {}

        def call_run() -> None:
            run_response["response"] = client.post(f"/jobs/{created['job_id']}/run")

        thread = threading.Thread(target=call_run)
        thread.start()

        self.assertTrue(runner.started.wait(timeout=2))

        status_response = client.get(f"/jobs/{created['job_id']}/status")

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["service_status"]["status"], "running")
        self.assertEqual(status_response.json()["service_status"]["current_step"], "validation")

        runner.release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(run_response["response"].status_code, 200)  # type: ignore[union-attr]

    def test_create_job_with_phase2_pipeline_id(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "phase2_smooth_reframe_dead_air_cut",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["pipeline"]["pipeline_id"], "phase2_smooth_reframe_dead_air_cut")
        self.assertEqual(len(payload["pipeline"]["steps"]), 12)
        self.assertEqual(payload["enabled_features"], {"remove_dead_air": True})
        self.assertEqual(len(payload["service_status"]["steps"]), 12)
        self.assertIn("audio_extraction", payload["service_status"]["steps"])

    def test_create_job_rejects_unknown_pipeline_id(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend", "pipeline_id": "phase99_made_up"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown pipeline_id", response.json()["detail"])

    def test_create_job_overrides_enabled_features_with_form_field(self) -> None:
        """The frontend can flip individual feature flags by sending an
        ``enabled_features`` JSON object alongside ``pipeline_id``; the
        orchestrator merges those flags onto the manifest template so users
        can e.g. opt out of filler-word cutting on Phase 3 jobs.
        """
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "phase3_audio_quality_cut",
                "enabled_features": json.dumps(
                    {
                        "remove_dead_air": True,
                        "enhance_audio": True,
                        "remove_filler_words": False,
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["enabled_features"],
            {"remove_dead_air": True, "enhance_audio": True},
        )

    def test_create_job_rejects_invalid_enabled_features_json(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "phase2_smooth_reframe_dead_air_cut",
                "enabled_features": "not-json",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("enabled_features", response.json()["detail"])

    def test_run_job_with_phase2_pipeline_marks_all_twelve_steps_complete(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "phase2_smooth_reframe_dead_air_cut",
            },
        ).json()

        response = self.client.post(f"/jobs/{created['job_id']}/run").json()

        self.assertEqual(response["service_status"]["status"], "success")
        terminal_statuses = {state["status"] for state in response["service_status"]["steps"].values()}
        self.assertEqual(terminal_statuses, {"success"})
