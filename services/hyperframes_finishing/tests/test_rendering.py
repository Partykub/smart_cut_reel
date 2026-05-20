from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from services.hyperframes_finishing.models import CompositionConfig
from services.hyperframes_finishing.models import NormalizedAssets
from services.hyperframes_finishing.models import NormalizedRenderSpec
from services.hyperframes_finishing.rendering import HyperframesCliRenderExecutor
from services.hyperframes_finishing.rendering import _host_layout_profile
from services.hyperframes_finishing.rendering import _template_preset_profile
from services.hyperframes_finishing.rendering import _resolve_variant_render_plan
from services.hyperframes_finishing.rendering import SubtitleCue
from services.hyperframes_finishing.rendering import _parse_json_subtitles
from services.hyperframes_finishing.rendering import _parse_srt_subtitles
from services.hyperframes_finishing.storage import HyperframesFilesystemStore


def _runtime_available() -> bool:
    runtime_dir = Path(__file__).resolve().parent.parent / "hyperframes"
    return runtime_dir.exists() and shutil.which("ffmpeg") is not None and shutil.which("npx") is not None


class SubtitleParsingTests(unittest.TestCase):
    def test_parse_json_subtitles_supports_segments_and_words(self) -> None:
        cues = _parse_json_subtitles(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "hello world",
                    },
                    {
                        "words": [
                            {"text": "smart", "start": 1.2, "end": 1.5},
                            {"text": "cut", "start": 1.5, "end": 1.8},
                        ]
                    },
                ]
            }
        )

        self.assertEqual(
            cues,
            [
                SubtitleCue(start_seconds=0.0, end_seconds=1.0, text="hello world"),
                SubtitleCue(start_seconds=1.2, end_seconds=1.5, text="smart"),
                SubtitleCue(start_seconds=1.5, end_seconds=1.8, text="cut"),
            ],
        )

    def test_parse_srt_subtitles_supports_basic_blocks(self) -> None:
        cues = _parse_srt_subtitles(
            """1
00:00:00,000 --> 00:00:00,500
hello world

2
00:00:00,500 --> 00:00:01,000
second line
"""
        )

        self.assertEqual(
            cues,
            [
                SubtitleCue(start_seconds=0.0, end_seconds=0.5, text="hello world"),
                SubtitleCue(start_seconds=0.5, end_seconds=1.0, text="second line"),
            ],
        )


class VariantRenderPlanTests(unittest.TestCase):
    def test_catalog_variants_map_to_distinct_render_plans(self) -> None:
        vfx_plan = _resolve_variant_render_plan(
            template_variant="vfx-text-cursor",
            has_logo=False,
            has_intro_video=False,
            has_outro_video=False,
        )
        lower_third_plan = _resolve_variant_render_plan(
            template_variant="yt-lower-third",
            has_logo=False,
            has_intro_video=False,
            has_outro_video=False,
        )
        lens_plan = _resolve_variant_render_plan(
            template_variant="gravitational-lens",
            has_logo=False,
            has_intro_video=False,
            has_outro_video=False,
        )
        ui_plan = _resolve_variant_render_plan(
            template_variant="ui-3d-reveal",
            has_logo=False,
            has_intro_video=False,
            has_outro_video=False,
        )

        self.assertEqual(vfx_plan.intro_clip.composition_id, "vfx-text-cursor")
        self.assertIsNone(vfx_plan.overlay_clip)
        self.assertEqual(lower_third_plan.overlay_clip.composition_id, "yt-lower-third")
        self.assertEqual(lens_plan.overlay_clip.composition_id, "gravitational-lens")
        self.assertEqual(ui_plan.intro_clip.composition_id, "ui-3d-reveal")
        self.assertIsNone(ui_plan.overlay_clip)

    def test_default_variant_keeps_logo_intro_fallback(self) -> None:
        plan = _resolve_variant_render_plan(
            template_variant="default",
            has_logo=True,
            has_intro_video=False,
            has_outro_video=False,
        )

        self.assertIsNotNone(plan.intro_clip)
        self.assertEqual(plan.intro_clip.composition_id, "default-logo-reveal")

    def test_vfx_profile_auto_generates_intro_and_outro_from_logo(self) -> None:
        profile = _template_preset_profile(template_variant="vfx-text-cursor", has_logo=True)
        plan = _resolve_variant_render_plan(
            template_variant="vfx-text-cursor",
            has_logo=True,
            has_intro_video=False,
            has_outro_video=False,
        )

        self.assertEqual(profile.intro_preset, "vfx-text-cursor")
        self.assertIsNone(profile.main_preset)
        self.assertEqual(profile.outro_preset, "vfx-text-cursor-outro")
        self.assertTrue(profile.auto_generate_intro)
        self.assertTrue(profile.auto_generate_outro)
        self.assertTrue(profile.uses_logo_as_intro_subject)
        self.assertEqual(plan.intro_clip.composition_id, "vfx-text-cursor")
        self.assertEqual(plan.outro_clip.composition_id, "vfx-text-cursor-outro")

    def test_uploaded_intro_and_outro_disable_auto_generated_preset_clips(self) -> None:
        plan = _resolve_variant_render_plan(
            template_variant="ui-3d-reveal",
            has_logo=True,
            has_intro_video=True,
            has_outro_video=True,
        )

        self.assertIsNone(plan.intro_clip)
        self.assertIsNone(plan.outro_clip)

    def test_host_layout_profile_changes_from_default_for_catalog_variants(self) -> None:
        default_layout = _host_layout_profile("horizontal", "default")
        vfx_layout = _host_layout_profile("horizontal", "vfx-text-cursor")
        ui_layout = _host_layout_profile("horizontal", "ui-3d-reveal")
        yt_layout = _host_layout_profile("horizontal", "yt-lower-third")

        self.assertTrue(default_layout.use_background_video)
        self.assertEqual(vfx_layout, default_layout)
        self.assertEqual(ui_layout, default_layout)
        self.assertIsNone(yt_layout.logo_style)


@unittest.skipUnless(_runtime_available(), "Hyperframes runtime, ffmpeg, and npx are required")
class HyperframesCliRenderExecutorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = HyperframesFilesystemStore(Path(self.temp_dir.name) / "store")
        self.executor = HyperframesCliRenderExecutor(workers="1", quality="draft")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_render_generates_mp4_for_vertical_and_horizontal_jobs(self) -> None:
        for template_family, size, color in [
            ("horizontal", "320x180", "red"),
            ("vertical", "180x320", "blue"),
        ]:
            with self.subTest(template_family=template_family):
                paths = self.store.create_job()
                source_video = Path(self.temp_dir.name) / f"{template_family}.mp4"
                self._build_sample_video(source_video, size=size, color=color)
                source_key = f"{paths.assets}/source_video.mp4"
                self.store.write_bytes(source_key, source_video.read_bytes())

                spec = NormalizedRenderSpec(
                    job_id=paths.job_id,
                    template_family=template_family,
                    template_variant="default",
                    orientation_detected=template_family,
                    assets=NormalizedAssets(source_video=source_key),
                    composition=CompositionConfig(
                        brand_theme="default",
                        subtitle_theme="glassmorphism",
                        safe_zone_profile=f"{template_family}_default",
                    ),
                )

                result = self.executor.render(spec=spec, store=self.store, paths=paths)

                output_path = self.store.root_dir.joinpath(*result.output_key.split("/"))
                self.assertTrue(output_path.exists())
                self.assertGreater(output_path.stat().st_size, 0)
                self.assertIn("render_log", result.artifact_keys)

    def test_render_generates_mp4_with_logo_subtitles_and_intro_outro(self) -> None:
        paths = self.store.create_job()
        source_video = Path(self.temp_dir.name) / "source.mp4"
        intro_video = Path(self.temp_dir.name) / "intro.mp4"
        outro_video = Path(self.temp_dir.name) / "outro.mp4"
        logo_file = Path(self.temp_dir.name) / "logo.svg"

        self._build_sample_video(source_video, size="320x180", color="green")
        self._build_sample_video(intro_video, size="320x180", color="black")
        self._build_sample_video(outro_video, size="320x180", color="white")
        logo_file.write_text(
            """
<svg xmlns="http://www.w3.org/2000/svg" width="320" height="96" viewBox="0 0 320 96">
    <rect width="320" height="96" rx="24" fill="#111827" />
    <text x="160" y="58" text-anchor="middle" font-size="42" fill="#f9fafb" font-family="Arial">SCR</text>
</svg>
""".strip(),
                        encoding="utf-8",
                )

        source_key = f"{paths.assets}/source_video.mp4"
        intro_key = f"{paths.assets}/intro_video.mp4"
        outro_key = f"{paths.assets}/outro_video.mp4"
        logo_key = f"{paths.assets}/logo_image.svg"
        subtitle_key = f"{paths.assets}/subtitle_file.json"
        self.store.write_bytes(source_key, source_video.read_bytes())
        self.store.write_bytes(intro_key, intro_video.read_bytes())
        self.store.write_bytes(outro_key, outro_video.read_bytes())
        self.store.write_bytes(logo_key, logo_file.read_bytes())
        self.store.write_json(
            subtitle_key,
            {
                "segments": [
                    {"text": "smart cut", "start": 0.0, "end": 0.3},
                    {"text": "hyperframes", "start": 0.3, "end": 0.6},
                ]
            },
        )

        spec = NormalizedRenderSpec(
            job_id=paths.job_id,
            template_family="horizontal",
            template_variant="default",
            orientation_detected="horizontal",
            assets=NormalizedAssets(
                source_video=source_key,
                intro_video=intro_key,
                outro_video=outro_key,
                logo_image=logo_key,
                subtitle_file=subtitle_key,
            ),
            composition=CompositionConfig(
                brand_theme="default",
                subtitle_theme="glassmorphism",
                safe_zone_profile="horizontal_default",
            ),
        )

        result = self.executor.render(spec=spec, store=self.store, paths=paths)

        output_path = self.store.root_dir.joinpath(*result.output_key.split("/"))
        self.assertTrue(output_path.exists())
        self.assertGreater(output_path.stat().st_size, 0)
        render_log_path = self.store.root_dir.joinpath(*result.artifact_keys["render_log"].split("/"))
        self.assertTrue(render_log_path.exists())

    def test_render_generates_logo_driven_intro_without_intro_video(self) -> None:
        paths = self.store.create_job()
        source_video = Path(self.temp_dir.name) / "source-no-intro.mp4"
        logo_file = Path(self.temp_dir.name) / "logo-no-intro.svg"

        self._build_sample_video(source_video, size="320x180", color="purple")
        logo_file.write_text(
            """
<svg xmlns="http://www.w3.org/2000/svg" width="360" height="120" viewBox="0 0 360 120">
    <rect width="360" height="120" rx="28" fill="#0f172a" />
    <rect x="12" y="12" width="336" height="96" rx="22" fill="#111827" stroke="#67e8f9" stroke-width="4" />
    <text x="180" y="74" text-anchor="middle" font-size="44" fill="#fef08a" font-family="Arial">BUGABOO</text>
</svg>
""".strip(),
            encoding="utf-8",
        )

        source_key = f"{paths.assets}/source_video.mp4"
        logo_key = f"{paths.assets}/logo_image.svg"
        self.store.write_bytes(source_key, source_video.read_bytes())
        self.store.write_bytes(logo_key, logo_file.read_bytes())

        spec = NormalizedRenderSpec(
            job_id=paths.job_id,
            template_family="horizontal",
            template_variant="default",
            orientation_detected="horizontal",
            assets=NormalizedAssets(
                source_video=source_key,
                logo_image=logo_key,
            ),
            composition=CompositionConfig(
                brand_theme="default",
                subtitle_theme="glassmorphism",
                safe_zone_profile="horizontal_default",
            ),
        )

        result = self.executor.render(spec=spec, store=self.store, paths=paths)

        output_path = self.store.root_dir.joinpath(*result.output_key.split("/"))
        self.assertTrue(output_path.exists())
        self.assertGreater(output_path.stat().st_size, 0)

    def _build_sample_video(self, destination: Path, *, size: str, color: str) -> None:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={size}:d=0.7",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed"
            self.fail(detail)