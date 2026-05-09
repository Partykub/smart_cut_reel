"""End-to-end smoke test for the Phase 2 dead-air cutting pipeline.

Generates a synthetic 9-second clip with audio that alternates loud/silent/loud
in 3-second blocks, then drives the new audio chain end-to-end:

* ``audio_extraction`` extracts mono PCM
* ``voice_activity_detection`` segments speech vs silence
* ``dead_air_cut_planning`` collapses silences into a cut plan
* ``render_plan_compiler`` projects the smooth crop onto each keep segment
* ``ffmpeg_renderer`` renders the final 9:16 MP4 with trims + concat + mux

The headline acceptance criterion (P2-I06) is that the rendered MP4's duration
matches ``cut_plan.metrics.total_kept_seconds`` within a small tolerance — i.e.
the renderer faithfully removes every silent block the planner asked it to.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from orchestrator.object_store import FilesystemObjectStore
from services.audio_extraction.service import AudioExtractionService
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.dead_air_cut_planning.service import DeadAirCutPlanningService
from services.ffmpeg_renderer.service import FFmpegRendererService
from services.render_plan_compiler.service import RenderPlanCompilerService
from services.voice_activity_detection.service import VoiceActivityDetectionService


_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _ffprobe_format_duration(path: Path) -> float:
    result = subprocess.run(
        [
            _FFPROBE or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _generate_synthetic_clip(out_path: Path) -> None:
    """Write a 9-second 320x180 clip with a loud / silent / loud audio pattern.

    Three audio blocks at 0–3 s, 3–6 s, 6–9 s. The middle block is anullsrc
    (digital silence) which the energy VAD must classify as silence.
    """
    cmd = [
        _FFMPEG or "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=9:size=320x180:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=9:sample_rate=16000",
        "-filter_complex",
        "[1:a]volume=enable='between(t,3,6)':volume=0[aout]",
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


@unittest.skipUnless(_FFMPEG and _FFPROBE, "ffmpeg/ffprobe not installed")
class Phase2DeadAirEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = FilesystemObjectStore(self.root)
        self.job_id = "job_phase2_e2e"
        self.prefix = f"jobs/{self.job_id}"

        src_path = self.root / "source.mp4"
        _generate_synthetic_clip(src_path)
        self.duration = _ffprobe_format_duration(src_path)
        self.assertGreater(self.duration, 8.5)
        self.assertLess(self.duration, 9.5)

        self.source_key = f"{self.prefix}/input/source.mp4"
        self.store.upload_bytes(
            self.source_key, src_path.read_bytes(), content_type="video/mp4"
        )

        self.metadata_key = f"{self.prefix}/artifacts/metadata.json"
        self.store.upload_json(
            self.metadata_key,
            {
                "duration": self.duration,
                "fps": 30.0,
                "width": 320,
                "height": 180,
            },
        )

        self.smooth_key = f"{self.prefix}/artifacts/reframe_plan_smooth.json"
        self.store.upload_json(
            self.smooth_key,
            {
                "job_id": self.job_id,
                "crop_width": 96,
                "crop_height": 180,
                "source_resolution": {"width": 320, "height": 180},
                "target_resolution": {"width": 108, "height": 192},
                "smoothing_method": "exponential",
                "smoothing_strength": 0.82,
                "max_velocity_px_per_second": 700.0,
                "max_acceleration_px_per_second2": 1600.0,
                "dead_zone_px": 80.0,
                "easing": "easeInOutCubic",
                "keyframes": [
                    {"frame_index": 0, "t": 0.0, "x": 112.0, "y": 0.0, "smoothed": True},
                    {"frame_index": 270, "t": 9.0, "x": 112.0, "y": 0.0, "smoothed": True},
                ],
            },
        )

        self.job_manifest_key = f"{self.prefix}/manifests/job_manifest.json"
        self.output_key = f"{self.prefix}/outputs/final_9x16.mp4"
        self.store.upload_json(
            self.job_manifest_key,
            {
                "schema_version": "2.0.0",
                "job_id": self.job_id,
                "input": {"source_video": {"object_key": self.source_key}},
                "target_output": {
                    "aspect_ratio": "9:16",
                    "resolution": {"width": 108, "height": 192},
                    "format": "mp4",
                    "object_key": self.output_key,
                },
                "enabled_features": {"remove_dead_air": True},
            },
        )

        self.artifact_manifest_key = f"{self.prefix}/manifests/artifact_manifest.json"
        self._refresh_artifact_manifest()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _refresh_artifact_manifest(self, **extra: dict) -> None:
        artifacts: dict = {
            "metadata": {
                "object_key": self.metadata_key,
                "produced_by": "media_metadata",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
            "reframe_plan_smooth": {
                "object_key": self.smooth_key,
                "produced_by": "easing_smoothing",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        }
        artifacts.update(extra)
        self.store.upload_json(
            self.artifact_manifest_key,
            {
                "schema_version": "2.0.0",
                "job_id": self.job_id,
                "updated_at": "2026-05-08T00:00:00Z",
                "artifacts": artifacts,
            },
        )

    def _ctx(self, request: RunRequest):
        return build_context(request, self.store)

    def test_pipeline_renders_only_kept_segments(self) -> None:
        audio_key = f"{self.prefix}/artifacts/extracted_audio.wav"
        AudioExtractionService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="audio_extraction",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={"source_video": self.source_key},
                    expected_outputs={"extracted_audio": audio_key},
                    config={"sample_rate": 16000, "channels": 1},
                )
            )
        )
        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": audio_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            }
        )

        vad_key = f"{self.prefix}/artifacts/vad_segments.json"
        VoiceActivityDetectionService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="voice_activity_detection",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={"artifact_manifest": self.artifact_manifest_key},
                    expected_outputs={"vad_segments": vad_key},
                    config={
                        "model": "energy",
                        "energy_threshold_db": -45.0,
                        "min_speech_duration_seconds": 0.25,
                        "min_silence_duration_seconds": 0.2,
                        "frame_duration_seconds": 0.03,
                    },
                )
            )
        )
        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": audio_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            vad_segments={
                "object_key": vad_key,
                "produced_by": "voice_activity_detection",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        )

        cut_plan_key = f"{self.prefix}/artifacts/cut_plan.json"
        DeadAirCutPlanningService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="dead_air_cut_planning",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={
                        "artifact_manifest": self.artifact_manifest_key,
                        "job_manifest": self.job_manifest_key,
                    },
                    expected_outputs={"cut_plan": cut_plan_key},
                    config={
                        "silence_threshold_seconds": 0.8,
                        "keep_padding_before": 0.05,
                        "keep_padding_after": 0.05,
                        "min_keep_segment_seconds": 0.5,
                    },
                )
            )
        )
        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": audio_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            vad_segments={
                "object_key": vad_key,
                "produced_by": "voice_activity_detection",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
            cut_plan={
                "object_key": cut_plan_key,
                "produced_by": "dead_air_cut_planning",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        )

        cut_plan = self.store.download_json(cut_plan_key)
        self.assertTrue(cut_plan["feature_enabled"])
        self.assertGreaterEqual(cut_plan["metrics"]["cut_count"], 1)
        kept_seconds = cut_plan["metrics"]["total_kept_seconds"]
        self.assertLess(
            kept_seconds,
            self.duration - 1.5,
            f"VAD did not detect the silent block (kept={kept_seconds}, duration={self.duration})",
        )

        render_plan_key = f"{self.prefix}/artifacts/render_plan.json"
        RenderPlanCompilerService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="render_plan_compiler",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={
                        "artifact_manifest": self.artifact_manifest_key,
                        "job_manifest": self.job_manifest_key,
                    },
                    expected_outputs={"render_plan": render_plan_key},
                    config={
                        "crop_representation": "keyframe_list",
                        "audio_policy": "aac_transcode",
                        "compiler_render_mode": "smooth_crop_with_cuts",
                    },
                )
            )
        )
        render_plan = self.store.download_json(render_plan_key)
        self.assertEqual(render_plan["render_mode"], "smooth_crop_with_cuts")
        self.assertAlmostEqual(
            render_plan["metadata"]["rendered_duration"],
            kept_seconds,
            places=4,
        )

        self._refresh_artifact_manifest(
            extracted_audio={
                "object_key": audio_key,
                "produced_by": "audio_extraction",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "audio/wav",
            },
            vad_segments={
                "object_key": vad_key,
                "produced_by": "voice_activity_detection",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
            cut_plan={
                "object_key": cut_plan_key,
                "produced_by": "dead_air_cut_planning",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
            render_plan={
                "object_key": render_plan_key,
                "produced_by": "render_plan_compiler",
                "created_at": "2026-05-08T00:00:00Z",
                "content_type": "application/json",
            },
        )

        FFmpegRendererService().run(
            self._ctx(
                RunRequest(
                    job_id=self.job_id,
                    step_id="ffmpeg_renderer",
                    minio=RunMinIO(bucket="smart-cut", prefix=f"{self.prefix}/"),
                    inputs={"artifact_manifest": self.artifact_manifest_key},
                    expected_outputs={"final_9x16": self.output_key},
                    config={"video_codec": "libx264", "audio_codec": "aac"},
                )
            )
        )
        out_bytes = self.store.download_bytes(self.output_key)
        out_path = self.root / "final.mp4"
        out_path.write_bytes(out_bytes)
        rendered_duration = _ffprobe_format_duration(out_path)

        self.assertAlmostEqual(rendered_duration, kept_seconds, delta=0.4)
        self.assertGreater(len(out_bytes), 1000)


if __name__ == "__main__":
    unittest.main()
