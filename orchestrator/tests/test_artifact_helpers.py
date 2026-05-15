import json
from pathlib import Path
import tempfile
import unittest

from orchestrator.artifact_helper import ArtifactHelper
from orchestrator.manifest_manager import ManifestManager
from orchestrator.object_store import FilesystemObjectStore
from orchestrator.path_resolver import artifact_path
from orchestrator.path_resolver import input_path
from orchestrator.path_resolver import manifest_path


class ArtifactHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.manifest_manager = ManifestManager(self.store)
        self.helper = ArtifactHelper(self.store, self.manifest_manager)
        self.job_manifest = json.loads(
            Path("contracts/examples/job_manifest.reframe_16x9_to_9x16.sample.json").read_text(
                encoding="utf-8"
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_initial_job_state_writes_all_manifests(self) -> None:
        self.manifest_manager.create_initial_job_state(self.job_manifest)

        self.assertTrue(self.store.exists(manifest_path("job_001", "job_manifest")))
        self.assertTrue(self.store.exists(manifest_path("job_001", "artifact_manifest")))
        self.assertTrue(self.store.exists(manifest_path("job_001", "service_status")))

        service_status = self.manifest_manager.read_service_status("job_001")
        self.assertEqual(service_status["status"], "pending")
        self.assertEqual(service_status["current_step"], None)
        self.assertEqual(len(service_status["steps"]), 9)

    def test_upload_source_video_writes_fixed_input_path(self) -> None:
        object_key = self.helper.upload_source_video("job_001", b"video-bytes")

        self.assertEqual(object_key, input_path("job_001"))
        self.assertTrue(self.store.exists(object_key))

    def test_upload_json_artifact_registers_entry_and_roundtrips(self) -> None:
        self.manifest_manager.create_initial_job_state(self.job_manifest)

        entry = self.helper.upload_json_artifact(
            "job_001",
            "metadata",
            {
                "width": 1920,
                "height": 1080,
                "fps": 30,
            },
        )

        self.assertEqual(entry["object_key"], artifact_path("job_001", "metadata"))
        self.assertEqual(entry["produced_by"], "media_metadata")
        self.assertEqual(entry["content_type"], "application/json")

        artifact_manifest = self.manifest_manager.read_artifact_manifest("job_001")
        self.assertIn("metadata", artifact_manifest["artifacts"])

        payload = self.helper.read_artifact("job_001", "metadata", deserialize_json=True)
        self.assertEqual(payload["width"], 1920)
        self.assertEqual(payload["height"], 1080)

    def test_service_status_updates_are_schema_compliant(self) -> None:
        self.manifest_manager.create_initial_job_state(self.job_manifest)

        self.manifest_manager.set_step_state(
            "job_001",
            "validation",
            step_status="running",
            started_at="2026-05-06T10:00:01Z",
            overall_status="running",
            current_step="validation",
        )
        self.manifest_manager.append_warning(
            "job_001",
            code="VALIDATION_NEAR_16X9",
            message="Aspect ratio is close to 16:9 but not exact.",
            step="validation",
            created_at="2026-05-06T10:00:01Z",
        )

        service_status = self.manifest_manager.read_service_status("job_001")
        self.assertEqual(service_status["status"], "running")
        self.assertEqual(service_status["current_step"], "validation")
        self.assertEqual(service_status["steps"]["validation"]["status"], "running")
        self.assertEqual(service_status["warnings"][0]["code"], "VALIDATION_NEAR_16X9")

    def test_set_step_state_can_attach_service_metrics(self) -> None:
        smooth_manifest = json.loads(
            Path(
                "contracts/examples/job_manifest.reframe_16x9_to_9x16_smooth_audio.sample.json"
            ).read_text(encoding="utf-8")
        )
        self.manifest_manager.create_initial_job_state(smooth_manifest)

        self.manifest_manager.set_step_state(
            smooth_manifest["job_id"],
            "audio_enhancement",
            step_status="success",
            finished_at="2026-05-06T10:00:02Z",
            overall_status="running",
            current_step="proxy_frame_sampling",
            step_metrics={"peak_sample_dbfs": -15.2, "peak_within_window": True},
        )

        service_status = self.manifest_manager.read_service_status(smooth_manifest["job_id"])
        metrics = service_status["steps"]["audio_enhancement"].get("metrics")
        self.assertEqual(metrics["peak_sample_dbfs"], -15.2)
        self.assertTrue(metrics["peak_within_window"])

    def test_register_artifact_requires_existing_object(self) -> None:
        self.manifest_manager.create_initial_job_state(self.job_manifest)

        with self.assertRaises(FileNotFoundError):
            self.manifest_manager.register_artifact("job_001", "metadata")

    def test_two_jobs_stay_isolated(self) -> None:
        self.manifest_manager.create_initial_job_state(self.job_manifest)

        second_manifest = json.loads(json.dumps(self.job_manifest))
        second_manifest["job_id"] = "job_002"
        second_manifest["input"]["source_video"]["object_key"] = "jobs/job_002/input/source.mp4"
        second_manifest["target_output"]["object_key"] = "jobs/job_002/outputs/final_9x16.mp4"
        self.manifest_manager.create_initial_job_state(second_manifest)

        self.helper.upload_json_artifact("job_002", "metadata", {"width": 1280, "height": 720})

        self.assertEqual(self.helper.list_artifacts("job_001"), {})
        self.assertIn("metadata", self.helper.list_artifacts("job_002"))
        self.assertTrue(
            all(object_key.startswith("jobs/job_002/") for object_key in self.helper.list_job_objects("job_002"))
        )
        self.assertTrue(
            all(object_key.startswith("jobs/job_001/") for object_key in self.helper.list_job_objects("job_001"))
        )

    def test_dead_air_preset_initial_job_state_creates_twelve_steps(self) -> None:
        dead_air_manifest = json.loads(
            Path(
                "contracts/examples/job_manifest.reframe_16x9_to_9x16_dead_air.sample.json"
            ).read_text(encoding="utf-8")
        )
        self.manifest_manager.create_initial_job_state(dead_air_manifest)

        service_status = self.manifest_manager.read_service_status(dead_air_manifest["job_id"])
        self.assertEqual(service_status["schema_version"], "2.0.0")
        self.assertEqual(len(service_status["steps"]), 12)
        self.assertIn("audio_extraction", service_status["steps"])
        self.assertIn("voice_activity_detection", service_status["steps"])
        self.assertIn("dead_air_cut_planning", service_status["steps"])

        artifact_manifest = self.manifest_manager.read_artifact_manifest(dead_air_manifest["job_id"])
        self.assertEqual(artifact_manifest["schema_version"], "2.0.0")

    def test_dead_air_preset_register_audio_artifacts(self) -> None:
        dead_air_manifest = json.loads(
            Path(
                "contracts/examples/job_manifest.reframe_16x9_to_9x16_dead_air.sample.json"
            ).read_text(encoding="utf-8")
        )
        self.manifest_manager.create_initial_job_state(dead_air_manifest)
        job_id = dead_air_manifest["job_id"]

        self.store.upload_bytes(artifact_path(job_id, "extracted_audio"), b"WAVE-bytes", content_type="audio/wav")
        entry = self.manifest_manager.register_artifact(job_id, "extracted_audio")
        self.assertEqual(entry["produced_by"], "audio_extraction")
        self.assertEqual(entry["content_type"], "audio/wav")
        self.assertEqual(entry["object_key"], artifact_path(job_id, "extracted_audio"))

        self.helper.upload_json_artifact(
            job_id,
            "vad_segments",
            {"segments": [{"start": 0.0, "end": 1.0, "type": "speech", "confidence": 0.9}]},
        )
        self.helper.upload_json_artifact(
            job_id,
            "cut_plan",
            {"keep_segments": [{"source_start": 0.0, "source_end": 1.0}]},
        )

        artifact_manifest = self.manifest_manager.read_artifact_manifest(job_id)
        self.assertEqual(artifact_manifest["artifacts"]["vad_segments"]["produced_by"], "voice_activity_detection")
        self.assertEqual(artifact_manifest["artifacts"]["cut_plan"]["produced_by"], "dead_air_cut_planning")