import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

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
            "jobs/job_test/manifests/artifact_manifest.json",
            {
                "artifacts": {
                    "render_plan": {"object_key": "jobs/job_test/artifacts/render_plan.json"},
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
            "jobs/job_test/manifests/artifact_manifest.json",
            {
                "artifacts": {
                    "render_plan": {"object_key": "jobs/job_test/artifacts/render_plan.json"},
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
            },
            config={},
        )
        self.service = FFmpegRendererService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_smooth_segments_writes_mp4(self) -> None:
        response = self.service.run(build_context(self.request, self.store))
        self.assertIn("final_9x16", response.outputs)
        data = self.store.download_bytes(self.request.expected_outputs["final_9x16"])
        self.assertGreater(len(data), 1000)


if __name__ == "__main__":
    unittest.main()
