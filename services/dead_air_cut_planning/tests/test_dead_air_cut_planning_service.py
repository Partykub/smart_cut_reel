"""Unit tests for the Phase 2 dead air cut planning service."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.dead_air_cut_planning.service import DeadAirCutPlanningService


class DeadAirCutPlanningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FilesystemObjectStore(Path(self.temp_dir.name))
        self.cut_plan_key = "jobs/job_test/artifacts/cut_plan.json"
        self.metadata_key = "jobs/job_test/artifacts/metadata.json"
        self.vad_key = "jobs/job_test/artifacts/vad_segments.json"
        self.artifact_manifest_key = "jobs/job_test/manifests/artifact_manifest.json"
        self.job_manifest_key = "jobs/job_test/manifests/job_manifest.json"

        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "metadata": {"object_key": self.metadata_key},
                    "vad_segments": {"object_key": self.vad_key},
                }
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_metadata(self, *, duration: float) -> None:
        self.store.upload_json(self.metadata_key, {"duration": duration, "fps": 30.0, "width": 1920, "height": 1080})

    def _write_vad(self, segments: list[dict]) -> None:
        self.store.upload_json(
            self.vad_key,
            {
                "segments": segments,
                "duration_seconds": segments[-1]["end"] if segments else 0.0,
            },
        )

    def _write_job_manifest(
        self,
        *,
        remove_dead_air: bool,
        remove_filler_words: bool = False,
    ) -> None:
        self.store.upload_json(
            self.job_manifest_key,
            {
                "job_id": "job_test",
                "enabled_features": {
                    "remove_dead_air": remove_dead_air,
                    "remove_filler_words": remove_filler_words,
                },
            },
        )

    def _build_request(self, *, config: dict | None = None) -> RunRequest:
        return RunRequest(
            job_id="job_test",
            step_id="dead_air_cut_planning",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "job_manifest": self.job_manifest_key,
                "artifact_manifest": self.artifact_manifest_key,
            },
            expected_outputs={"cut_plan": self.cut_plan_key},
            config=config or {},
        )

    def test_identity_plan_when_feature_disabled(self) -> None:
        self._write_metadata(duration=12.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 6.0, "type": "speech", "confidence": 0.9},
                {"start": 6.0, "end": 12.0, "type": "silence", "confidence": 0.95},
            ]
        )
        self._write_job_manifest(remove_dead_air=False)

        service = DeadAirCutPlanningService()
        service.run(build_context(self._build_request(), self.store))

        payload = self.store.download_json(self.cut_plan_key)
        self.assertFalse(payload["feature_enabled"])
        self.assertEqual(payload["keep_segments"], [{"source_start": 0.0, "source_end": 12.0}])
        self.assertEqual(payload["metrics"]["cut_count"], 0)
        self.assertEqual(payload["metrics"]["compression_ratio"], 1.0)

    def test_removes_silence_above_threshold_with_padding(self) -> None:
        self._write_metadata(duration=20.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 4.0, "type": "speech", "confidence": 0.9},
                {"start": 4.0, "end": 6.5, "type": "silence", "confidence": 0.95},
                {"start": 6.5, "end": 10.0, "type": "speech", "confidence": 0.9},
                {"start": 10.0, "end": 14.0, "type": "silence", "confidence": 0.97},
                {"start": 14.0, "end": 20.0, "type": "speech", "confidence": 0.92},
            ]
        )
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        service.run(
            build_context(
                self._build_request(
                    config={
                        "silence_threshold_seconds": 1.0,
                        "keep_padding_before": 0.2,
                        "keep_padding_after": 0.3,
                        "min_keep_segment_seconds": 0.0,
                    }
                ),
                self.store,
            )
        )
        payload = self.store.download_json(self.cut_plan_key)

        self.assertTrue(payload["feature_enabled"])
        keep_segments = payload["keep_segments"]
        self.assertEqual(len(keep_segments), 3)
        self.assertEqual(keep_segments[0], {"source_start": 0.0, "source_end": 4.3})
        self.assertEqual(keep_segments[1], {"source_start": 6.3, "source_end": 10.3})
        self.assertEqual(keep_segments[2], {"source_start": 13.8, "source_end": 20.0})
        self.assertEqual(payload["metrics"]["cut_count"], 2)
        self.assertGreater(payload["metrics"]["total_removed_seconds"], 0.0)

    def test_short_silence_below_threshold_is_kept(self) -> None:
        self._write_metadata(duration=10.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 4.0, "type": "speech", "confidence": 0.9},
                {"start": 4.0, "end": 4.5, "type": "silence", "confidence": 0.8},
                {"start": 4.5, "end": 10.0, "type": "speech", "confidence": 0.9},
            ]
        )
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        service.run(
            build_context(
                self._build_request(
                    config={
                        "silence_threshold_seconds": 1.0,
                        "keep_padding_before": 0.0,
                        "keep_padding_after": 0.0,
                        "min_keep_segment_seconds": 0.0,
                    }
                ),
                self.store,
            )
        )
        payload = self.store.download_json(self.cut_plan_key)

        self.assertEqual(payload["keep_segments"], [{"source_start": 0.0, "source_end": 10.0}])
        self.assertEqual(payload["metrics"]["cut_count"], 0)

    def test_padding_merges_adjacent_keep_segments(self) -> None:
        self._write_metadata(duration=10.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 4.0, "type": "speech", "confidence": 0.9},
                {"start": 4.0, "end": 5.0, "type": "silence", "confidence": 0.95},
                {"start": 5.0, "end": 10.0, "type": "speech", "confidence": 0.9},
            ]
        )
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        service.run(
            build_context(
                self._build_request(
                    config={
                        "silence_threshold_seconds": 0.5,
                        "keep_padding_before": 0.6,
                        "keep_padding_after": 0.6,
                        "min_keep_segment_seconds": 0.0,
                    }
                ),
                self.store,
            )
        )
        payload = self.store.download_json(self.cut_plan_key)

        self.assertEqual(payload["keep_segments"], [{"source_start": 0.0, "source_end": 10.0}])

    def test_min_keep_segment_drops_short_window_with_warning_in_plan(self) -> None:
        self._write_metadata(duration=10.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 1.5, "type": "silence", "confidence": 0.95},
                {"start": 1.5, "end": 1.8, "type": "speech", "confidence": 0.9},
                {"start": 1.8, "end": 10.0, "type": "silence", "confidence": 0.95},
            ]
        )
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        response = service.run(
            build_context(
                self._build_request(
                    config={
                        "silence_threshold_seconds": 0.5,
                        "keep_padding_before": 0.0,
                        "keep_padding_after": 0.0,
                        "min_keep_segment_seconds": 1.0,
                    }
                ),
                self.store,
            )
        )
        payload = self.store.download_json(self.cut_plan_key)

        self.assertEqual(len(payload["keep_segments"]), 1)
        self.assertGreaterEqual(payload["keep_segments"][0]["source_end"], 10.0)
        self.assertEqual(
            [w["code"] for w in payload["plan_warnings"]],
            ["DEAD_AIR_DROPPED_SHORT_KEEP_SEGMENTS"],
        )

        warning_codes = [w.code for w in response.warnings]
        self.assertIn("CUT_PLAN_EMPTY_FALLBACK_IDENTITY", warning_codes)

    def test_missing_metadata_artifact_raises(self) -> None:
        self._write_vad(
            [{"start": 0.0, "end": 1.0, "type": "speech", "confidence": 0.9}]
        )
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        with self.assertRaises(ValueError):
            service.run(build_context(self._build_request(), self.store))

    def test_missing_vad_when_feature_enabled_raises(self) -> None:
        self._write_metadata(duration=10.0)
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        with self.assertRaises(ValueError):
            service.run(build_context(self._build_request(), self.store))

    def test_filler_word_cut_subtracts_intervals_from_keep_segments(self) -> None:
        self._write_metadata(duration=12.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 12.0, "type": "speech", "confidence": 0.95},
            ]
        )
        self._write_job_manifest(remove_dead_air=True, remove_filler_words=True)

        transcript_key = "jobs/job_test/artifacts/transcript.json"
        self.store.upload_json(
            transcript_key,
            {
                "schema_version": "3.0.0",
                "job_id": "job_test",
                "model": "small",
                "language": "th",
                "segments": [
                    {
                        "start": 0.0,
                        "end": 12.0,
                        "text": "สวัสดี เอ่อ วันนี้",
                        "words": [
                            {"word": "สวัสดี", "start": 0.0, "end": 1.0, "confidence": 0.9},
                            {
                                "word": "เอ่อ",
                                "start": 4.0,
                                "end": 4.5,
                                "confidence": 0.6,
                                "is_filler": True,
                            },
                            {"word": "วันนี้", "start": 8.0, "end": 9.0, "confidence": 0.9},
                        ],
                    }
                ],
                "metrics": {"total_words": 3, "filler_word_count": 1},
            },
        )
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "artifacts": {
                    "metadata": {"object_key": self.metadata_key},
                    "vad_segments": {"object_key": self.vad_key},
                    "transcript": {"object_key": transcript_key},
                }
            },
        )

        service = DeadAirCutPlanningService()
        service.run(
            build_context(
                self._build_request(
                    config={
                        "silence_threshold_seconds": 1.0,
                        "keep_padding_before": 0.0,
                        "keep_padding_after": 0.0,
                        "min_keep_segment_seconds": 0.1,
                        "filler_padding_before": 0.05,
                        "filler_padding_after": 0.05,
                    }
                ),
                self.store,
            )
        )
        payload = self.store.download_json(self.cut_plan_key)

        keep_segments = payload["keep_segments"]
        self.assertEqual(len(keep_segments), 2)
        first, second = keep_segments
        self.assertAlmostEqual(first["source_start"], 0.0, places=4)
        self.assertAlmostEqual(first["source_end"], 3.95, places=4)
        self.assertAlmostEqual(second["source_start"], 4.55, places=4)
        self.assertAlmostEqual(second["source_end"], 12.0, places=4)
        self.assertGreater(payload["metrics"]["removed_filler_seconds"], 0.5)
        self.assertEqual(payload["metrics"]["filler_word_count"], 1)

    def test_filler_word_cut_skipped_with_warning_when_transcript_missing(self) -> None:
        self._write_metadata(duration=10.0)
        self._write_vad(
            [
                {"start": 0.0, "end": 10.0, "type": "speech", "confidence": 0.95},
            ]
        )
        self._write_job_manifest(remove_dead_air=True, remove_filler_words=True)

        service = DeadAirCutPlanningService()
        response = service.run(build_context(self._build_request(), self.store))
        warning_codes = [w.code for w in response.warnings]
        self.assertIn("FILLER_CUT_TRANSCRIPT_MISSING", warning_codes)

        payload = self.store.download_json(self.cut_plan_key)
        self.assertEqual(payload["metrics"]["removed_filler_seconds"], 0.0)
        self.assertEqual(payload["metrics"]["filler_word_count"], 0)

    def test_negative_config_value_raises(self) -> None:
        self._write_metadata(duration=10.0)
        self._write_vad([{"start": 0.0, "end": 5.0, "type": "speech", "confidence": 0.9}])
        self._write_job_manifest(remove_dead_air=True)

        service = DeadAirCutPlanningService()
        with self.assertRaises(ValueError):
            service.run(
                build_context(
                    self._build_request(config={"silence_threshold_seconds": -1.0}),
                    self.store,
                )
            )


if __name__ == "__main__":
    unittest.main()
