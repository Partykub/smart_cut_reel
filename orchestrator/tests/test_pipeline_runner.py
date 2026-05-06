import json
from pathlib import Path
import tempfile
import unittest

import httpx

from orchestrator.contracts import ARTIFACT_CONTENT_TYPES
from orchestrator.contracts import ARTIFACT_PRODUCERS
from orchestrator.contracts import PIPELINE_STEP_IDS
from orchestrator.object_store import FilesystemObjectStore
from orchestrator.pipeline_runner import HttpPipelineRunner
from orchestrator.service import OrchestratorService


class HttpPipelineRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_run_job_calls_services_in_order_and_registers_outputs(self) -> None:
        seen_steps: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            step_id = payload["step_id"]
            seen_steps.append(step_id)

            for artifact_key, object_key in payload["expected_outputs"].items():
                self.store.upload_bytes(
                    object_key,
                    f"{step_id}:{artifact_key}".encode("utf-8"),
                    content_type=ARTIFACT_CONTENT_TYPES[artifact_key],
                )

            warnings = []
            if step_id == "body_detection":
                warnings.append(
                    {
                        "code": "BODY_DETECTION_FALLBACK",
                        "message": "Detector used fallback boxes for 2 frames.",
                    }
                )

            return httpx.Response(
                200,
                json={
                    "service_id": step_id,
                    "status": "success",
                    "outputs": payload["expected_outputs"],
                    "warnings": warnings,
                },
            )

        transport = httpx.MockTransport(handler)
        runner = HttpPipelineRunner(
            service_endpoints={step_id: f"http://{step_id}.service" for step_id in PIPELINE_STEP_IDS},
            minio_bucket="smart-cut",
            client_factory=lambda: httpx.Client(transport=transport),
        )
        service = OrchestratorService(self.store, runner=runner)

        created = service.create_job(
            source_bytes=b"video-bytes",
            original_filename="clip.mp4",
            job_id="job_http_runner_success",
        )
        result = service.run_job(created["job_id"])

        self.assertEqual(seen_steps, list(PIPELINE_STEP_IDS))
        self.assertEqual(result["service_status"]["status"], "success")
        self.assertIsNone(result["service_status"]["current_step"])
        self.assertEqual(set(result["artifacts"]), set(ARTIFACT_PRODUCERS))
        self.assertEqual(result["service_status"]["warnings"][0]["code"], "BODY_DETECTION_FALLBACK")
        self.assertEqual(result["service_status"]["warnings"][0]["step"], "body_detection")

    def test_run_job_marks_step_failed_and_stops_pipeline(self) -> None:
        seen_steps: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            step_id = payload["step_id"]
            seen_steps.append(step_id)

            if step_id == "proxy_frame_sampling":
                return httpx.Response(
                    200,
                    json={
                        "service_id": step_id,
                        "status": "failed",
                        "error": "proxy generation crashed",
                        "outputs": {},
                        "warnings": [],
                    },
                )

            for artifact_key, object_key in payload["expected_outputs"].items():
                self.store.upload_bytes(
                    object_key,
                    f"{step_id}:{artifact_key}".encode("utf-8"),
                    content_type=ARTIFACT_CONTENT_TYPES[artifact_key],
                )

            return httpx.Response(
                200,
                json={
                    "service_id": step_id,
                    "status": "success",
                    "outputs": payload["expected_outputs"],
                    "warnings": [],
                },
            )

        transport = httpx.MockTransport(handler)
        runner = HttpPipelineRunner(
            service_endpoints={step_id: f"http://{step_id}.service" for step_id in PIPELINE_STEP_IDS},
            minio_bucket="smart-cut",
            client_factory=lambda: httpx.Client(transport=transport),
        )
        service = OrchestratorService(self.store, runner=runner)

        created = service.create_job(
            source_bytes=b"video-bytes",
            original_filename="clip.mp4",
            job_id="job_http_runner_failure",
        )
        result = service.run_job(created["job_id"])

        self.assertEqual(seen_steps, ["validation", "media_metadata", "proxy_frame_sampling"])
        self.assertEqual(result["service_status"]["status"], "failed")
        self.assertIsNone(result["service_status"]["current_step"])
        self.assertEqual(result["service_status"]["steps"]["proxy_frame_sampling"]["status"], "failed")
        self.assertEqual(result["service_status"]["steps"]["body_detection"]["status"], "pending")
        self.assertEqual(result["service_status"]["errors"], ["proxy_frame_sampling: proxy generation crashed"])
        self.assertEqual(set(result["artifacts"]), {"metadata"})