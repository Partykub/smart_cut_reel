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

    def test_create_job_dead_air_preset(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["pipeline"]["pipeline_id"], "reframe_16x9_to_9x16_dead_air_enhanced"
        )
        self.assertEqual(len(payload["pipeline"]["steps"]), 13)
        self.assertEqual(
            payload["enabled_features"],
            {"remove_dead_air": True, "enhance_audio": True},
        )
        self.assertEqual(len(payload["service_status"]["steps"]), 13)
        self.assertIn("audio_extraction", payload["service_status"]["steps"])

    def test_create_job_audio_profile_social_merges_manifest(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air_enhanced",
                "audio_profile": "social",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        job_id = payload["job_id"]
        manifest = self.service.manifest_manager.read_job_manifest(job_id)
        ae = manifest["service_config"]["audio_enhancement"]
        self.assertEqual(ae["target_lufs"], -14.0)
        self.assertEqual(ae["denoise_model"], "off")
        self.assertEqual(ae["highpass_frequency_hz"], 0.0)
        self.assertTrue(ae["loudness_normalization_enabled"])
        self.assertEqual(manifest.get("audio_profile"), "social")
        self.assertEqual(payload.get("audio_profile"), "social")
        self.assertEqual(payload.get("audio_enhancement", {}).get("target_lufs"), -14.0)
        self.assertEqual(
            manifest["service_config"]["render_plan_compiler"]["output_audio_source"],
            "enhanced_wav",
        )
        self.assertEqual(payload.get("output_audio_source"), "enhanced_wav")

    def test_create_job_audio_profile_original_keeps_source_video_mux(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air_enhanced",
                "audio_profile": "original",
            },
        )
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        manifest = self.service.manifest_manager.read_job_manifest(job_id)
        self.assertEqual(
            manifest["service_config"]["render_plan_compiler"]["output_audio_source"],
            "source_video",
        )
        ae = manifest["service_config"]["audio_enhancement"]
        self.assertFalse(ae["loudness_normalization_enabled"])
        self.assertEqual(ae["denoise_model"], "off")
        self.assertNotIn("target_lufs", ae)

    def test_create_job_explicit_output_audio_source_overrides_profile_default(
        self,
    ) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air_enhanced",
                "audio_profile": "social",
                "output_audio_source": "source_video",
            },
        )
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        manifest = self.service.manifest_manager.read_job_manifest(job_id)
        self.assertEqual(
            manifest["service_config"]["render_plan_compiler"]["output_audio_source"],
            "source_video",
        )

    def test_create_job_rejects_audio_profile_on_reframe_only(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16",
                "audio_profile": "podcast",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("audio_enhancement step", response.json()["detail"])

    def test_create_job_rejects_invalid_audio_profile(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air_enhanced",
                "audio_profile": "not_a_profile",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("audio_profile", response.json()["detail"])

    def test_create_job_audio_enhancement_json_partial_merges(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air_enhanced",
                "audio_enhancement": json.dumps({"denoise_model": "off"}),
            },
        )
        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        manifest = self.service.manifest_manager.read_job_manifest(job_id)
        self.assertEqual(manifest["service_config"]["audio_enhancement"]["denoise_model"], "off")
        self.assertIsNone(manifest.get("audio_profile"))

    def test_create_job_dead_air_alias_forces_enhance_audio_even_if_disabled_in_form(
        self,
    ) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air",
                "enabled_features": json.dumps({"remove_dead_air": True, "enhance_audio": False}),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["pipeline"]["pipeline_id"], "reframe_16x9_to_9x16_dead_air_enhanced"
        )
        self.assertEqual(
            payload["enabled_features"],
            {"remove_dead_air": True, "enhance_audio": True},
        )

    def test_create_job_rejects_unknown_pipeline_id(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={"created_by": "debug_frontend", "pipeline_id": "phase99_made_up"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown pipeline_id", response.json()["detail"])

    def test_create_job_rejects_legacy_phase_pipeline_id_alias(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "phase2_smooth_reframe_dead_air_cut",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown pipeline_id", response.json()["detail"])

    def test_create_job_overrides_enabled_features_with_form_field(self) -> None:
        """The frontend can flip individual feature flags by sending an
        ``enabled_features`` JSON object alongside ``pipeline_id``; the
        orchestrator merges those flags onto the manifest template so users
        can e.g. opt out of filler-word cutting on audio-quality preset jobs.
        """
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_audio_quality",
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
                "pipeline_id": "reframe_16x9_to_9x16_dead_air",
                "enabled_features": "not-json",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("enabled_features", response.json()["detail"])

    def test_create_job_merges_service_config_overrides(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "service_config": json.dumps(
                    {
                        "body_detection": {
                            "face_detector_backend": "retinaface",
                            "face_min_confidence": 0.6,
                        }
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        manifest = self.service.manifest_manager.read_job_manifest(payload["job_id"])
        body_detection_config = manifest["service_config"]["body_detection"]
        self.assertEqual(body_detection_config["face_detector_backend"], "retinaface")
        self.assertEqual(body_detection_config["face_min_confidence"], 0.6)
        self.assertEqual(body_detection_config["model_path"], "yolov8m.pt")

    def test_create_job_rejects_invalid_service_config_json(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "service_config": "not-json",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("service_config", response.json()["detail"])

    def test_create_job_rejects_non_object_service_config_values(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "service_config": json.dumps({"body_detection": True}),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("service_config values", response.json()["detail"])

    def test_run_job_with_dead_air_preset_marks_all_steps_complete(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air",
            },
        ).json()

        response = self.client.post(f"/jobs/{created['job_id']}/run").json()

        self.assertEqual(response["service_status"]["status"], "success")
        terminal_statuses = {state["status"] for state in response["service_status"]["steps"].values()}
        self.assertEqual(terminal_statuses, {"success"})

    def test_create_job_smooth_audio_pipeline_has_eleven_steps_and_audio_profile(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_smooth_audio",
                "audio_profile": "social",
            },
        )
        self.assertEqual(created.status_code, 200)
        payload = created.json()
        self.assertEqual(payload["pipeline"]["pipeline_id"], "reframe_16x9_to_9x16_smooth_audio")
        self.assertEqual(len(payload["pipeline"]["steps"]), 11)
        self.assertIn("audio_enhancement", payload["pipeline"]["steps"])
        self.assertEqual(payload["audio_profile"], "social")
        self.assertEqual(payload["output_audio_source"], "enhanced_wav")

    def test_create_job_rejects_output_audio_enhanced_wav_without_enhancement_pipeline(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16",
                "output_audio_source": "enhanced_wav",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("audio_enhancement", response.json()["detail"])

    def test_create_job_rejects_vad_audio_source_on_reframe_only(self) -> None:
        response = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16",
                "vad_audio_source": "extracted_audio",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("voice_activity_detection", response.json()["detail"])

    def test_create_job_persists_output_and_vad_audio_routing(self) -> None:
        created = self.client.post(
            "/jobs",
            files={"source": ("clip.mp4", b"video-bytes", "video/mp4")},
            data={
                "created_by": "debug_frontend",
                "pipeline_id": "reframe_16x9_to_9x16_dead_air_enhanced",
                "output_audio_source": "enhanced_wav",
                "vad_audio_source": "extracted_audio",
            },
        )
        self.assertEqual(created.status_code, 200)
        job_id = created.json()["job_id"]
        status = self.client.get(f"/jobs/{job_id}/status").json()
        self.assertEqual(status["output_audio_source"], "enhanced_wav")
        self.assertEqual(status["vad_audio_source"], "extracted_audio")
