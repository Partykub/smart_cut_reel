import unittest

from orchestrator.path_resolver import KNOWN_ARTIFACT_KEYS
from orchestrator.path_resolver import artifact_path
from orchestrator.path_resolver import input_path
from orchestrator.path_resolver import job_prefix
from orchestrator.path_resolver import log_path
from orchestrator.path_resolver import manifest_path
from orchestrator.path_resolver import output_path
from orchestrator.path_resolver import validate_artifact_key
from orchestrator.path_resolver import validate_job_id


class PathResolverTests(unittest.TestCase):
    def test_job_prefix_uses_phase_one_layout(self) -> None:
        self.assertEqual(job_prefix("job_001"), "jobs/job_001")

    def test_input_path_is_fixed(self) -> None:
        self.assertEqual(input_path("job_001"), "jobs/job_001/input/source.mp4")

    def test_manifest_paths_match_contract(self) -> None:
        self.assertEqual(
            manifest_path("job_001", "job_manifest"),
            "jobs/job_001/manifests/job_manifest.json",
        )
        self.assertEqual(
            manifest_path("job_001", "artifact_manifest"),
            "jobs/job_001/manifests/artifact_manifest.json",
        )
        self.assertEqual(
            manifest_path("job_001", "service_status"),
            "jobs/job_001/manifests/service_status.json",
        )

    def test_artifact_paths_cover_all_known_keys(self) -> None:
        expected = {
            "metadata": "jobs/job_001/artifacts/metadata.json",
            "extracted_audio": "jobs/job_001/artifacts/extracted_audio.wav",
            "enhanced_audio": "jobs/job_001/artifacts/enhanced_audio.wav",
            "vad_segments": "jobs/job_001/artifacts/vad_segments.json",
            "transcript": "jobs/job_001/artifacts/transcript.json",
            "cut_plan": "jobs/job_001/artifacts/cut_plan.json",
            "proxy": "jobs/job_001/artifacts/proxy.mp4",
            "sampled_frames": "jobs/job_001/artifacts/sampled_frames.json",
            "body_tracks_raw": "jobs/job_001/artifacts/body_tracks_raw.json",
            "body_tracks_interpolated": "jobs/job_001/artifacts/body_tracks_interpolated.json",
            "reframe_plan_raw": "jobs/job_001/artifacts/reframe_plan_raw.json",
            "reframe_plan_smooth": "jobs/job_001/artifacts/reframe_plan_smooth.json",
            "render_plan": "jobs/job_001/artifacts/render_plan.json",
            "final_9x16": "jobs/job_001/outputs/final_9x16.mp4",
            "source_overlay": "jobs/job_001/outputs/source_overlay.mp4",
        }
        self.assertEqual(set(KNOWN_ARTIFACT_KEYS), set(expected))
        for artifact_key, object_key in expected.items():
            self.assertEqual(artifact_path("job_001", artifact_key), object_key)

    def test_output_path_is_final_video(self) -> None:
        self.assertEqual(output_path("job_001"), "jobs/job_001/outputs/final_9x16.mp4")

    def test_log_path_uses_service_id(self) -> None:
        self.assertEqual(
            log_path("job_001", "body_detection"),
            "jobs/job_001/logs/body_detection.log",
        )

    def test_validate_job_id_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            validate_job_id("bad/job")

    def test_validate_artifact_key_rejects_unknown_value(self) -> None:
        with self.assertRaises(KeyError):
            validate_artifact_key("unknown")

    def test_manifest_name_rejects_unknown_value(self) -> None:
        with self.assertRaises(KeyError):
            manifest_path("job_001", "timeline")

    def test_phase2_audio_artifact_paths(self) -> None:
        self.assertEqual(
            artifact_path("job_xyz", "extracted_audio"),
            "jobs/job_xyz/artifacts/extracted_audio.wav",
        )
        self.assertEqual(
            artifact_path("job_xyz", "vad_segments"),
            "jobs/job_xyz/artifacts/vad_segments.json",
        )
        self.assertEqual(
            artifact_path("job_xyz", "cut_plan"),
            "jobs/job_xyz/artifacts/cut_plan.json",
        )


if __name__ == "__main__":
    unittest.main()