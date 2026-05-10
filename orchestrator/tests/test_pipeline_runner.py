import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from orchestrator.contracts import ARTIFACT_CONTENT_TYPES
from orchestrator.contracts import ARTIFACT_PRODUCERS
from orchestrator.contracts import PIPELINE_ID_REFRAME_DEAD_AIR
from orchestrator.contracts import REFRAME_DEAD_AIR_STEP_IDS
from orchestrator.contracts import PIPELINE_STEP_IDS
from orchestrator.object_store import FilesystemObjectStore
from orchestrator.pipeline_runner import HttpPipelineRunner
from orchestrator.service import OrchestratorService
from orchestrator.path_resolver import artifact_path
from services.body_detection.service import BodyDetectionService
from services.body_detection.service import DetectionCandidate
from services.body_detection.service import DetectionRunResult
from services.common.runtime import build_context
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.easing_smoothing.service import EasingSmoothingService
from services.media_metadata.service import MediaMetadataService
from services.proxy_frame_sampling.service import ProxyFrameSamplingService
from services.reframe_planning.service import ReframePlanningService
from services.track_interpolation.service import TrackInterpolationService
from services.validation.service import ValidationService


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
        reframe_only_artifact_keys = {
            artifact_key
            for artifact_key, producer in ARTIFACT_PRODUCERS.items()
            if producer in PIPELINE_STEP_IDS
        }
        self.assertEqual(set(result["artifacts"]), reframe_only_artifact_keys)
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

    def test_run_job_uses_real_service_apps_for_early_pipeline_steps(self) -> None:
        validation_service = ValidationService()
        metadata_service = MediaMetadataService()
        proxy_frame_sampling_service = ProxyFrameSamplingService()
        body_detection_service = BodyDetectionService()
        track_interpolation_service = TrackInterpolationService()
        reframe_planning_service = ReframePlanningService()
        easing_smoothing_service = EasingSmoothingService()

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            step_id = payload["step_id"]

            if step_id == "validation":
                response = validation_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

            if step_id == "media_metadata":
                response = metadata_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

            if step_id == "proxy_frame_sampling":
                response = proxy_frame_sampling_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

            if step_id == "body_detection":
                response = body_detection_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

            if step_id == "track_interpolation":
                response = track_interpolation_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

            if step_id == "reframe_planning":
                response = reframe_planning_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

            if step_id == "easing_smoothing":
                response = easing_smoothing_service.run(self._build_service_context(payload))
                return httpx.Response(200, json=self._serialize_response(response))

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

        probe_document = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                    "avg_frame_rate": "30000/1001",
                }
            ],
            "format": {"duration": "9.5"},
        }

        with (
            patch("services.validation.service.probe_video_bytes", return_value=probe_document),
            patch("services.media_metadata.service.probe_video_bytes", return_value=probe_document),
            patch("services.proxy_frame_sampling.service.build_proxy_video_bytes", return_value=b"proxy-bytes"),
            patch.object(
                BodyDetectionService,
                "_detect_proxy_frames",
                return_value=DetectionRunResult(
                    detections_by_frame={0: DetectionCandidate(x=100.0, y=120.0, w=400.0, h=800.0, confidence=0.92)},
                    detector_backend="yolo_ultralytics_cpu",
                    track_source="yolo_person_detector",
                    warnings=[],
                ),
            ),
        ):
            created = service.create_job(
                source_bytes=b"video-bytes",
                original_filename="clip.mp4",
                job_id="job_http_runner_real_services",
            )
            result = service.run_job(created["job_id"])

        metadata = self.store.download_json(f"jobs/{created['job_id']}/artifacts/metadata.json")
        sampled_frames = self.store.download_json(f"jobs/{created['job_id']}/artifacts/sampled_frames.json")
        raw_tracks = self.store.download_json(f"jobs/{created['job_id']}/artifacts/body_tracks_raw.json")
        interpolated_tracks = self.store.download_json(f"jobs/{created['job_id']}/artifacts/body_tracks_interpolated.json")
        reframe_plan = self.store.download_json(f"jobs/{created['job_id']}/artifacts/reframe_plan_raw.json")
        smooth_plan = self.store.download_json(f"jobs/{created['job_id']}/artifacts/reframe_plan_smooth.json")

        self.assertEqual(result["service_status"]["status"], "success")
        self.assertEqual(metadata["source_aspect_ratio"], "16:9")
        self.assertEqual(metadata["target_crop"], {"width": 608, "height": 1080})
        self.assertEqual(sampled_frames["proxy_resolution"], {"width": 960, "height": 540})
        self.assertEqual(sampled_frames["frames"][0], {"index": 0, "t": 0.0})
        self.assertEqual(raw_tracks["coordinate_space"], "source")
        self.assertEqual(raw_tracks["detector_backend"], "yolo_ultralytics_cpu")
        self.assertEqual(len(raw_tracks["tracks"]), len(sampled_frames["frames"]))
        self.assertEqual(raw_tracks["tracks"][0]["center"], {"x": 300.0, "y": 520.0})
        self.assertEqual(interpolated_tracks["coordinate_space"], "source")
        self.assertEqual(len(interpolated_tracks["tracks"]), len(raw_tracks["tracks"]))
        self.assertEqual(reframe_plan["crop_width"], 608)
        self.assertEqual(reframe_plan["crop_height"], 1080)
        self.assertEqual(len(reframe_plan["keyframes"]), len(interpolated_tracks["tracks"]))
        self.assertEqual(smooth_plan["crop_width"], 608)
        self.assertEqual(len(smooth_plan["keyframes"]), len(reframe_plan["keyframes"]))
        self.assertTrue(smooth_plan["keyframes"][0]["smoothed"])
        warning_codes = [warning["code"] for warning in result["service_status"]["warnings"]]
        self.assertIn("BODY_DETECTION_MISSING_FRAMES", warning_codes)

    def test_get_job_status_reconciles_completed_ffmpeg_outputs(self) -> None:
        service = OrchestratorService(self.store)

        created = service.create_job(
            source_bytes=b"video-bytes",
            original_filename="clip.mp4",
            job_id="job_reconcile_ffmpeg_success",
        )
        job_id = created["job_id"]

        service.manifest_manager.set_step_state(
            job_id,
            "validation",
            step_status="success",
            started_at="2026-05-08T09:50:46Z",
            finished_at="2026-05-08T09:50:46Z",
            overall_status="running",
            current_step="media_metadata",
        )
        for step_id in PIPELINE_STEP_IDS[1:-1]:
            service.manifest_manager.set_step_state(
                job_id,
                step_id,
                step_status="success",
                started_at="2026-05-08T09:51:00Z",
                finished_at="2026-05-08T09:51:01Z",
                overall_status="running",
                current_step="ffmpeg_renderer",
            )
        service.manifest_manager.set_step_state(
            job_id,
            "ffmpeg_renderer",
            step_status="running",
            started_at="2026-05-08T09:51:39Z",
            overall_status="running",
            current_step="ffmpeg_renderer",
        )

        self.store.upload_bytes(
            artifact_path(job_id, "final_9x16"),
            b"final-video",
            content_type=ARTIFACT_CONTENT_TYPES["final_9x16"],
        )
        self.store.upload_bytes(
            artifact_path(job_id, "source_overlay"),
            b"overlay-video",
            content_type=ARTIFACT_CONTENT_TYPES["source_overlay"],
        )

        result = service.get_job_status(job_id)

        self.assertEqual(result["service_status"]["status"], "success")
        self.assertIsNone(result["service_status"]["current_step"])
        self.assertEqual(result["service_status"]["steps"]["ffmpeg_renderer"]["status"], "success")
        self.assertIn("final_9x16", result["artifacts"])
        self.assertIn("source_overlay", result["artifacts"])

    def _build_service_context(self, payload: dict[str, object]):
        request = RunRequest(
            job_id=str(payload["job_id"]),
            step_id=str(payload["step_id"]),
            minio=RunMinIO(**payload["minio"]),
            inputs=dict(payload["inputs"]),
            expected_outputs=dict(payload["expected_outputs"]),
            config=dict(payload.get("config", {})),
        )
        return build_context(request, self.store)

    def _serialize_response(self, response):
        return {
            "service_id": response.service_id,
            "status": response.status,
            "outputs": response.outputs,
            "warnings": [
                {
                    "code": warning.code,
                    "message": warning.message,
                    **({"step": warning.step} if warning.step is not None else {}),
                    **({"created_at": warning.created_at} if warning.created_at is not None else {}),
                }
                for warning in response.warnings
            ],
        }


class HttpPipelineRunnerDeadAirPresetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dead_air_runner_invokes_all_twelve_steps_in_order(self) -> None:
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
            service_endpoints={
                step_id: f"http://{step_id}.service" for step_id in REFRAME_DEAD_AIR_STEP_IDS
            },
            minio_bucket="smart-cut",
            client_factory=lambda: httpx.Client(transport=transport),
        )
        service = OrchestratorService(self.store, runner=runner)

        created = service.create_job(
            source_bytes=b"video-bytes",
            original_filename="clip.mp4",
            job_id="job_dead_air_runner_success",
            pipeline_id=PIPELINE_ID_REFRAME_DEAD_AIR,
        )
        result = service.run_job(created["job_id"])

        expected_dead_air_artifacts = {
            artifact_key
            for artifact_key, producer in ARTIFACT_PRODUCERS.items()
            if producer in REFRAME_DEAD_AIR_STEP_IDS
        }
        self.assertEqual(seen_steps, list(REFRAME_DEAD_AIR_STEP_IDS))
        self.assertEqual(result["service_status"]["status"], "success")
        self.assertEqual(set(result["artifacts"]), expected_dead_air_artifacts)
        self.assertEqual(result["pipeline"]["pipeline_id"], PIPELINE_ID_REFRAME_DEAD_AIR)
        self.assertEqual(result["enabled_features"], {"remove_dead_air": True})

    def test_dead_air_runner_passes_preset_service_config_through_to_each_step(self) -> None:
        observed_configs: dict[str, dict] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            observed_configs[payload["step_id"]] = dict(payload.get("config") or {})

            for artifact_key, object_key in payload["expected_outputs"].items():
                self.store.upload_bytes(
                    object_key,
                    f"{payload['step_id']}:{artifact_key}".encode("utf-8"),
                    content_type=ARTIFACT_CONTENT_TYPES[artifact_key],
                )

            return httpx.Response(
                200,
                json={
                    "service_id": payload["step_id"],
                    "status": "success",
                    "outputs": payload["expected_outputs"],
                    "warnings": [],
                },
            )

        transport = httpx.MockTransport(handler)
        runner = HttpPipelineRunner(
            service_endpoints={
                step_id: f"http://{step_id}.service" for step_id in REFRAME_DEAD_AIR_STEP_IDS
            },
            minio_bucket="smart-cut",
            client_factory=lambda: httpx.Client(transport=transport),
        )
        service = OrchestratorService(self.store, runner=runner)

        created = service.create_job(
            source_bytes=b"video-bytes",
            original_filename="clip.mp4",
            job_id="job_dead_air_runner_config",
            pipeline_id=PIPELINE_ID_REFRAME_DEAD_AIR,
        )
        service.run_job(created["job_id"])

        self.assertIn("audio_extraction", observed_configs)
        self.assertEqual(observed_configs["audio_extraction"]["sample_rate"], 16000)
        self.assertEqual(
            observed_configs["voice_activity_detection"]["model"], "silero_v5"
        )
        self.assertEqual(
            observed_configs["render_plan_compiler"]["compiler_render_mode"],
            "smooth_crop_with_cuts",
        )