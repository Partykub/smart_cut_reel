import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import json

from orchestrator.object_store import FilesystemObjectStore
from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import build_context
from services.ffmpeg_renderer.service import FFmpegRendererService


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _write_minimal_mp4(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x180:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _probe_streams(path: Path) -> dict:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg not installed")
class FFmpegRendererServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = FilesystemObjectStore(self.root)
        src_mp4 = self.root / "in.mp4"
        _write_minimal_mp4(src_mp4)
        video_bytes = src_mp4.read_bytes()

        self.store.upload_bytes(
            "jobs/job_test/input/source.mp4",
            video_bytes,
            content_type="video/mp4",
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/render_plan.json",
            {
                "schema_version": "1.0.0",
                "job_id": "job_test",
                "audio_policy": "copy_if_possible_else_aac",
                "source_video": {"object_key": "jobs/job_test/input/source.mp4"},
                "target_resolution": {"width": 108, "height": 192},
                "metadata": {"duration": 1.0, "fps": 30.0},
                "crop_plan": {
                    "crop_width": 96,
                    "crop_height": 180,
                    "keyframes": [{"t": 0.0, "x": 112.0, "y": 0.0}],
                },
                "render_mode": "static_crop",
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_raw.json",
            {
                "job_id": "job_test",
                "tracks": [
                    {
                        "t": 0.0,
                        "frame_index": 0,
                        "missing": False,
                        "bbox": {"x": 96.0, "y": 20.0, "w": 110.0, "h": 120.0},
                        "confidence": 0.93,
                        "source": "yolo_person_detector",
                    }
                ],
            },
        )
        self.store.upload_json(
            "jobs/job_test/manifests/artifact_manifest.json",
            {
                "artifacts": {
                    "render_plan": {"object_key": "jobs/job_test/artifacts/render_plan.json"},
                    "body_tracks_raw": {"object_key": "jobs/job_test/artifacts/body_tracks_raw.json"},
                }
            },
        )

        self.request = RunRequest(
            job_id="job_test",
            step_id="ffmpeg_renderer",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "final_9x16": "jobs/job_test/outputs/final_9x16.mp4",
                "source_overlay": "jobs/job_test/outputs/source_overlay.mp4",
            },
            config={"video_codec": "libx264", "audio_codec": "aac"},
        )
        self.service = FFmpegRendererService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_static_crop_writes_mp4(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        out_key = self.request.expected_outputs["final_9x16"]
        self.assertEqual(response.outputs["final_9x16"], out_key)
        data = self.store.download_bytes(out_key)
        self.assertGreater(len(data), 1000)
        self.assertEqual(data[4:8], b"ftyp")
        overlay_key = self.request.expected_outputs["source_overlay"]
        self.assertEqual(response.outputs["source_overlay"], overlay_key)
        overlay_data = self.store.download_bytes(overlay_key)
        self.assertGreater(len(overlay_data), 1000)
        self.assertEqual(overlay_data[4:8], b"ftyp")
        overlay_path = self.root / "overlay.mp4"
        overlay_path.write_bytes(overlay_data)
        streams = _probe_streams(overlay_path)["streams"]
        self.assertEqual(streams[0]["codec_name"], "h264")


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg not installed")
class FFmpegRendererSmoothTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = FilesystemObjectStore(self.root)
        src_mp4 = self.root / "in.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=2:size=320x180:rate=30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(src_mp4),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        video_bytes = src_mp4.read_bytes()
        self.store.upload_bytes("jobs/job_test/input/source.mp4", video_bytes, content_type="video/mp4")

        self.store.upload_json(
            "jobs/job_test/artifacts/render_plan.json",
            {
                "schema_version": "1.0.0",
                "job_id": "job_test",
                "audio_policy": "copy_if_possible_else_aac",
                "source_video": {"object_key": "jobs/job_test/input/source.mp4"},
                "target_resolution": {"width": 108, "height": 192},
                "metadata": {"duration": 2.0, "fps": 30.0},
                "crop_plan": {
                    "crop_width": 96,
                    "crop_height": 180,
                    "keyframes": [
                        {"t": 0.0, "x": 0.0, "y": 0.0},
                        {"t": 1.0, "x": 50.0, "y": 0.0},
                    ],
                },
                "render_mode": "smooth_crop",
            },
        )
        self.store.upload_json(
            "jobs/job_test/artifacts/body_tracks_raw.json",
            {
                "job_id": "job_test",
                "tracks": [
                    {
                        "t": 0.0,
                        "frame_index": 0,
                        "missing": False,
                        "bbox": {"x": 40.0, "y": 10.0, "w": 100.0, "h": 130.0},
                        "confidence": 0.91,
                        "source": "yolo_person_detector",
                    },
                    {
                        "t": 1.0,
                        "frame_index": 30,
                        "missing": False,
                        "bbox": {"x": 120.0, "y": 12.0, "w": 102.0, "h": 130.0},
                        "confidence": 0.9,
                        "source": "yolo_person_detector",
                    }
                ],
            },
        )
        self.store.upload_json(
            "jobs/job_test/manifests/artifact_manifest.json",
            {
                "artifacts": {
                    "render_plan": {"object_key": "jobs/job_test/artifacts/render_plan.json"},
                    "body_tracks_raw": {"object_key": "jobs/job_test/artifacts/body_tracks_raw.json"},
                }
            },
        )
        self.request = RunRequest(
            job_id="job_test",
            step_id="ffmpeg_renderer",
            minio=RunMinIO(bucket="smart-cut", prefix="jobs/job_test/"),
            inputs={
                "artifact_manifest": "jobs/job_test/manifests/artifact_manifest.json",
            },
            expected_outputs={
                "final_9x16": "jobs/job_test/outputs/final_9x16.mp4",
                "source_overlay": "jobs/job_test/outputs/source_overlay.mp4",
            },
            config={},
        )
        self.service = FFmpegRendererService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_smooth_segments_writes_mp4(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        self.assertIn("final_9x16", response.outputs)
        self.assertIn("source_overlay", response.outputs)
        data = self.store.download_bytes(self.request.expected_outputs["final_9x16"])
        self.assertGreater(len(data), 1000)
        overlay_data = self.store.download_bytes(self.request.expected_outputs["source_overlay"])
        self.assertGreater(len(overlay_data), 1000)
        overlay_path = self.root / "overlay_smooth.mp4"
        overlay_path.write_bytes(overlay_data)
        streams = _probe_streams(overlay_path)["streams"]
        self.assertEqual(streams[0]["codec_name"], "h264")


class FFmpegRendererTrackLookupTests(unittest.TestCase):
    def test_overlay_uses_current_or_previous_track_not_future_track(self) -> None:
        service = FFmpegRendererService()
        tracks = [
            {"frame_index": 789, "t": 157.8, "bbox": {"x": 10}},
            {"frame_index": 790, "t": 158.0, "bbox": {"x": 20}},
            {"frame_index": 791, "t": 158.2, "bbox": {"x": 30}},
        ]
        track_times = [157.8, 158.0, 158.2]

        selected = service._track_for_time(tracks, track_times, 158.1)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["frame_index"], 790)


if __name__ == "__main__":
    unittest.main()
