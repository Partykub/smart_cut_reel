from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from typing import Protocol

from services.common.media import run_ffprobe
from services.hyperframes_finishing.models import parse_subtitle_document
from services.hyperframes_finishing.models import NormalizedRenderSpec
from services.hyperframes_finishing.storage import HyperframesFilesystemStore
from services.hyperframes_finishing.storage import JobPaths


@dataclass(frozen=True)
class RenderResult:
    output_key: str
    artifact_keys: dict[str, str]


class RenderExecutor(Protocol):
    def render(
        self,
        *,
        spec: NormalizedRenderSpec,
        store: HyperframesFilesystemStore,
        paths: JobPaths,
    ) -> RenderResult: ...


class MockHyperframesRenderExecutor:
    """Fallback executor until the real Hyperframes runtime is wired in.

    It preserves the full job/contract flow and emits artifacts expected by the
    frontend and tests. The output video is currently a pass-through of the
    uploaded source video so the surrounding service can be developed safely.
    """

    def render(
        self,
        *,
        spec: NormalizedRenderSpec,
        store: HyperframesFilesystemStore,
        paths: JobPaths,
    ) -> RenderResult:
        output_key = f"{paths.output}/final.mp4"
        source_bytes = store.read_bytes(spec.assets.source_video)
        store.write_bytes(output_key, source_bytes)

        render_log_key = f"{paths.artifacts}/render_log.json"
        store.write_json(
            render_log_key,
            {
                "job_id": spec.job_id,
                "renderer": "mock_hyperframes",
                "template_family": spec.template_family,
                "template_variant": spec.template_variant,
                "note": (
                    "Mock executor wrote a pass-through MP4 so API, worker, and frontend can "
                    "be built before the real Hyperframes runtime is installed."
                ),
            },
        )

        return RenderResult(
            output_key=output_key,
            artifact_keys={
                "render_log": render_log_key,
            },
        )


@dataclass(frozen=True)
class SubtitleCue:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class VariantClip:
    composition_id: str
    composition_src: str
    duration: float
    width: int = 1920
    height: int = 1080
    style: str = "position:absolute; inset:0; width:100%; height:100%;"


@dataclass(frozen=True)
class VariantRenderPlan:
    intro_clip: VariantClip | None = None
    overlay_clip: VariantClip | None = None
    outro_clip: VariantClip | None = None


@dataclass(frozen=True)
class TemplatePresetProfile:
    intro_preset: str | None
    main_preset: str | None
    outro_preset: str | None
    auto_generate_intro: bool
    auto_generate_outro: bool
    uses_logo_as_intro_subject: bool


@dataclass(frozen=True)
class HostLayoutProfile:
    use_background_video: bool
    source_video_style: str
    logo_style: str | None


class HyperframesCliRenderExecutor:
    def __init__(
        self,
        *,
        runtime_dir: Path | None = None,
        fps: int = 30,
        quality: str = "draft",
        workers: str = "1",
    ) -> None:
        self.runtime_dir = runtime_dir or Path(__file__).resolve().parent / "hyperframes"
        self.fps = fps
        self.quality = quality
        self.workers = workers

    def render(
        self,
        *,
        spec: NormalizedRenderSpec,
        store: HyperframesFilesystemStore,
        paths: JobPaths,
    ) -> RenderResult:
        if not self.runtime_dir.exists():
            raise RuntimeError(f"Hyperframes runtime directory was not found: {self.runtime_dir}")

        output_key = f"{paths.output}/final.mp4"
        output_path = _store_path(store, output_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        project_dir = _store_path(store, f"{paths.artifacts}/hyperframes_project")
        project_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = project_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        source_local = _copy_asset_to_project(store, spec.assets.source_video, assets_dir, "source")
        intro_local = _copy_optional_asset_to_project(store, spec.assets.intro_video, assets_dir, "intro")
        outro_local = _copy_optional_asset_to_project(store, spec.assets.outro_video, assets_dir, "outro")
        logo_local = _copy_optional_asset_to_project(store, spec.assets.logo_image, assets_dir, "logo")
        subtitle_local = _copy_optional_asset_to_project(
            store,
            spec.assets.subtitle_file,
            assets_dir,
            "subtitles",
        )

        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        logo_from_compositions = (
            os.path.relpath(logo_local, start=compositions_dir) if logo_local is not None else None
        )
        source_from_compositions = os.path.relpath(source_local, start=compositions_dir)
        variant_plan = _prepare_variant_render_plan(
            project_dir=project_dir,
            template_variant=spec.template_variant,
            logo_relative=logo_from_compositions,
            source_relative=source_from_compositions,
            has_intro_video=intro_local is not None,
            has_outro_video=outro_local is not None,
        )

        source_meta = _probe_media(source_local)
        intro_meta = _probe_media(intro_local) if intro_local is not None else None
        outro_meta = _probe_media(outro_local) if outro_local is not None else None
        subtitle_cues = _load_subtitle_cues(subtitle_local)

        canvas_width, canvas_height = _canvas_dimensions(spec.template_family)
        intro_duration = (
            intro_meta["duration_seconds"]
            if intro_meta is not None
            else variant_plan.intro_clip.duration
            if variant_plan.intro_clip is not None
            else 0.0
        )
        source_duration = source_meta["duration_seconds"]
        outro_duration = (
            outro_meta["duration_seconds"]
            if outro_meta is not None
            else variant_plan.outro_clip.duration
            if variant_plan.outro_clip is not None
            else 0.0
        )
        total_duration = max(0.1, intro_duration + source_duration + outro_duration)

        html_path = project_dir / "index.html"
        html_path.write_text(
            _build_composition_html(
                spec=spec,
                source_relative=source_local.relative_to(project_dir).as_posix(),
                intro_relative=intro_local.relative_to(project_dir).as_posix()
                if intro_local is not None
                else None,
                outro_relative=outro_local.relative_to(project_dir).as_posix()
                if outro_local is not None
                else None,
                logo_relative=logo_local.relative_to(project_dir).as_posix()
                if logo_local is not None
                else None,
                subtitle_cues=subtitle_cues,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                variant_plan=variant_plan,
                intro_duration=intro_duration,
                source_duration=source_duration,
                outro_duration=outro_duration,
                total_duration=total_duration,
            ),
            encoding="utf-8",
        )

        (project_dir / "hyperframes.json").write_text(
            json.dumps(
                {
                    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                    "paths": {
                        "assets": "assets",
                        "blocks": "compositions",
                        "components": "compositions/components",
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        command = [
            "npx",
            "hyperframes",
            "render",
            str(project_dir),
            "--composition=index.html",
            f"--output={output_path}",
            f"--fps={self.fps}",
            f"--quality={self.quality}",
            f"--workers={self.workers}",
            f"--format=mp4",
        ]
        env = os.environ.copy()
        env.setdefault("HYPERFRAMES_NO_UPDATE_CHECK", "1")
        completed = subprocess.run(
            command,
            cwd=self.runtime_dir,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        render_log_key = f"{paths.artifacts}/render_log.json"
        store.write_json(
            render_log_key,
            {
                "job_id": spec.job_id,
                "renderer": "hyperframes_cli",
                "template_family": spec.template_family,
                "template_variant": spec.template_variant,
                "runtime_dir": str(self.runtime_dir),
                "project_dir": str(project_dir),
                "composition_path": str(html_path),
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "hyperframes render failed"
            raise RuntimeError(detail)
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise RuntimeError("Hyperframes render did not create a playable output file")

        return RenderResult(
            output_key=output_key,
            artifact_keys={
                "render_log": render_log_key,
            },
        )


def _store_path(store: HyperframesFilesystemStore, object_key: str) -> Path:
    return store.root_dir.joinpath(*object_key.split("/"))


def _copy_asset_to_project(
    store: HyperframesFilesystemStore,
    object_key: str,
    assets_dir: Path,
    stem: str,
) -> Path:
    source_path = _store_path(store, object_key)
    suffix = source_path.suffix or ".bin"
    destination = assets_dir / f"{stem}{suffix}"
    shutil.copyfile(source_path, destination)
    return destination


def _copy_optional_asset_to_project(
    store: HyperframesFilesystemStore,
    object_key: str | None,
    assets_dir: Path,
    stem: str,
) -> Path | None:
    if object_key is None:
        return None
    return _copy_asset_to_project(store, object_key, assets_dir, stem)


def _probe_media(path: Path) -> dict[str, Any]:
    document = run_ffprobe(path)
    duration = _extract_duration_seconds(document)
    if duration <= 0:
        raise ValueError(f"media duration must be greater than zero: {path}")
    return {
        "duration_seconds": duration,
        "document": document,
    }


def _extract_duration_seconds(document: dict[str, Any]) -> float:
    format_section = document.get("format")
    if isinstance(format_section, dict):
        value = format_section.get("duration")
        try:
            duration = float(value)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            return duration

    streams = document.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            value = stream.get("duration")
            try:
                duration = float(value)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                return duration
    return 0.0


def _canvas_dimensions(template_family: str) -> tuple[int, int]:
    if template_family == "vertical":
        return 1080, 1920
    return 1920, 1080


def _load_subtitle_cues(path: Path | None) -> list[SubtitleCue]:
    if path is None:
        return []
    document = parse_subtitle_document(path.name, path.read_bytes())
    return _subtitle_document_to_cues(document)


def _parse_json_subtitles(document: Any) -> list[SubtitleCue]:
    return _subtitle_document_to_cues(
        parse_subtitle_document("subtitles.json", json.dumps(document).encode("utf-8"))
    )


def _subtitle_document_to_cues(document: Any) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    words = getattr(document, "words", [])
    segments = getattr(document, "segments", [])
    if words:
        for word in words:
            cues.append(
                SubtitleCue(
                    start_seconds=word.start,
                    end_seconds=word.end,
                    text=word.text,
                )
            )
    for segment in segments:
        if segment.words:
            for word in segment.words:
                cues.append(
                    SubtitleCue(
                        start_seconds=word.start,
                        end_seconds=word.end,
                        text=word.text,
                    )
                )
            continue
        cues.append(
            SubtitleCue(
                start_seconds=float(segment.start),
                end_seconds=float(segment.end),
                text=str(segment.text),
            )
        )
    return cues


def _parse_srt_subtitles(content: str) -> list[SubtitleCue]:
    return _subtitle_document_to_cues(parse_subtitle_document("subtitles.srt", content.encode("utf-8")))


def _build_composition_html(
    *,
    spec: NormalizedRenderSpec,
    source_relative: str,
    intro_relative: str | None,
    outro_relative: str | None,
    logo_relative: str | None,
    subtitle_cues: list[SubtitleCue],
    canvas_width: int,
    canvas_height: int,
    variant_plan: VariantRenderPlan,
    intro_duration: float,
    source_duration: float,
    outro_duration: float,
    total_duration: float,
) -> str:
    main_start = intro_duration
    outro_start = intro_duration + source_duration
    layout = _host_layout_profile(spec.template_family, spec.template_variant)

    elements: list[str] = []
    track_index = 0
    if layout.use_background_video:
        elements.append(
            _video_clip(
                element_id="background-video",
                src=source_relative,
                start=main_start,
                duration=source_duration,
                track_index=track_index,
                style=(
                    "position:absolute; inset:-3%; width:106%; height:106%; object-fit:cover; "
                    "filter:blur(40px) brightness(0.6); transform:scale(1.08); opacity:0.95;"
                ),
            )
        )
        track_index += 1

    if intro_relative is not None:
        elements.append(
            _video_clip(
                element_id="intro-video",
                src=intro_relative,
                start=0.0,
                duration=intro_duration,
                track_index=track_index,
                style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:#000;",
            )
        )
        track_index += 1

    if variant_plan.intro_clip is not None and intro_duration > 0:
        elements.append(
            _subcomposition_clip(
                element_id=f"intro-{variant_plan.intro_clip.composition_id}",
                composition_id=variant_plan.intro_clip.composition_id,
                composition_src=variant_plan.intro_clip.composition_src,
                start=0.0,
                duration=min(intro_duration, variant_plan.intro_clip.duration),
                track_index=track_index,
                width=variant_plan.intro_clip.width,
                height=variant_plan.intro_clip.height,
                style=variant_plan.intro_clip.style,
            )
        )
        track_index += 1

    elements.append(
        _video_clip(
            element_id="source-video",
            src=source_relative,
            start=main_start,
            duration=source_duration,
            track_index=track_index,
            style=layout.source_video_style,
        )
    )
    track_index += 1

    if variant_plan.overlay_clip is not None:
        elements.append(
            _subcomposition_clip(
                element_id=f"overlay-{variant_plan.overlay_clip.composition_id}",
                composition_id=variant_plan.overlay_clip.composition_id,
                composition_src=variant_plan.overlay_clip.composition_src,
                start=main_start,
                duration=min(source_duration, variant_plan.overlay_clip.duration),
                track_index=track_index,
                width=variant_plan.overlay_clip.width,
                height=variant_plan.overlay_clip.height,
                style=variant_plan.overlay_clip.style,
            )
        )
        track_index += 1

    if outro_relative is not None:
        elements.append(
            _video_clip(
                element_id="outro-video",
                src=outro_relative,
                start=outro_start,
                duration=outro_duration,
                track_index=track_index,
                style="position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:#000;",
            )
        )
        track_index += 1
    elif variant_plan.outro_clip is not None and outro_duration > 0:
        elements.append(
            _subcomposition_clip(
                element_id=f"outro-{variant_plan.outro_clip.composition_id}",
                composition_id=variant_plan.outro_clip.composition_id,
                composition_src=variant_plan.outro_clip.composition_src,
                start=outro_start,
                duration=min(outro_duration, variant_plan.outro_clip.duration),
                track_index=track_index,
                width=variant_plan.outro_clip.width,
                height=variant_plan.outro_clip.height,
                style=variant_plan.outro_clip.style,
            )
        )
        track_index += 1

    if logo_relative is not None and layout.logo_style is not None:
        elements.append(
            _image_clip(
                element_id="brand-logo",
                src=logo_relative,
                start=main_start,
                duration=source_duration,
                track_index=track_index,
                style=layout.logo_style,
            )
        )
        track_index += 1

    for index, cue in enumerate(subtitle_cues):
        elements.append(
            _text_clip(
                element_id=f"subtitle-{index}",
                text=cue.text,
                start=main_start + cue.start_seconds,
                duration=max(0.05, cue.end_seconds - cue.start_seconds),
                track_index=track_index,
                style=_subtitle_style(spec.template_family, spec.composition.subtitle_theme),
            )
        )
        track_index += 1

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "  <head>",
            '    <meta charset="UTF-8" />',
            f'    <meta name="viewport" content="width={canvas_width}, height={canvas_height}" />',
            '    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>',
            "    <style>",
            "      * { margin: 0; padding: 0; box-sizing: border-box; }",
            f"      html, body {{ width: {canvas_width}px; height: {canvas_height}px; overflow: hidden; background: #000; font-family: Arial, sans-serif; }}",
            "      #root { position: relative; width: 100%; height: 100%; overflow: hidden; background: #000; }",
            "      .clip { position: absolute; }",
            "    </style>",
            "  </head>",
            "  <body>",
            "    <div",
            '      id="root"',
            '      data-composition-id="main"',
            '      data-start="0"',
            f'      data-duration="{_format_seconds(total_duration)}"',
            f'      data-width="{canvas_width}"',
            f'      data-height="{canvas_height}"',
            "    >",
            *[f"      {element}" for element in elements],
            "    </div>",
            "    <script>",
            "      window.__timelines = window.__timelines || {};",
            "      window.__timelines['main'] = gsap.timeline({ paused: true });",
            "    </script>",
            "  </body>",
            "</html>",
        ]
    )


def _video_clip(
    *,
    element_id: str,
    src: str,
    start: float,
    duration: float,
    track_index: int,
    style: str,
) -> str:
    return (
        f'<video id="{escape(element_id)}" class="clip" src="{escape(src)}" '
        f'data-start="{_format_seconds(start)}" data-duration="{_format_seconds(duration)}" '
        f'data-track-index="{track_index}" muted playsinline preload="auto" '
        f'style="{escape(style)}"></video>'
    )


def _image_clip(
    *,
    element_id: str,
    src: str,
    start: float,
    duration: float,
    track_index: int,
    style: str,
) -> str:
    return (
        f'<img id="{escape(element_id)}" class="clip" src="{escape(src)}" '
        f'data-start="{_format_seconds(start)}" data-duration="{_format_seconds(duration)}" '
        f'data-track-index="{track_index}" style="{escape(style)}" />'
    )


def _subcomposition_clip(
    *,
    element_id: str,
    composition_id: str,
    composition_src: str,
    start: float,
    duration: float,
    track_index: int,
    width: int,
    height: int,
    style: str,
) -> str:
    return (
        f'<div id="{escape(element_id)}" class="clip" '
        f'data-composition-id="{escape(composition_id)}" '
        f'data-composition-src="{escape(composition_src)}" '
        f'data-start="{_format_seconds(start)}" data-duration="{_format_seconds(duration)}" '
        f'data-track-index="{track_index}" data-width="{width}" data-height="{height}" '
        f'style="{escape(style)}"></div>'
    )


def _text_clip(
    *,
    element_id: str,
    text: str,
    start: float,
    duration: float,
    track_index: int,
    style: str,
) -> str:
    return (
        f'<div id="{escape(element_id)}" class="clip" '
        f'data-start="{_format_seconds(start)}" data-duration="{_format_seconds(duration)}" '
        f'data-track-index="{track_index}" style="{escape(style)}">{escape(text)}</div>'
    )


def _subtitle_style(template_family: str, subtitle_theme: str) -> str:
    if template_family == "vertical":
        base = (
            "left:50%; bottom:10%; width:78%; transform:translateX(-50%); text-align:center; "
            "font-size:52px; line-height:1.2; font-weight:700; color:#fff; padding:20px 28px; border-radius:24px;"
        )
    else:
        base = (
            "left:50%; bottom:8%; width:72%; transform:translateX(-50%); text-align:center; "
            "font-size:46px; line-height:1.2; font-weight:700; color:#fff; padding:18px 26px; border-radius:20px;"
        )
    if subtitle_theme == "glassmorphism":
        return f"{base} background:rgba(0, 0, 0, 0.52); border:1px solid rgba(255, 255, 255, 0.18);"
    return f"{base} background:rgba(0, 0, 0, 0.7);"


def _logo_style(template_family: str) -> str:
    if template_family == "vertical":
        return (
            "top:72px; right:64px; width:180px; height:auto; max-height:120px; object-fit:contain; "
            "opacity:0.96; filter:drop-shadow(0 8px 24px rgba(0, 0, 0, 0.28));"
        )
    return (
        "top:52px; right:56px; width:220px; height:auto; max-height:110px; object-fit:contain; "
        "opacity:0.96; filter:drop-shadow(0 8px 24px rgba(0, 0, 0, 0.28));"
    )


def _format_seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def _resolve_variant_render_plan(
    *,
    template_variant: str,
    has_logo: bool,
    has_intro_video: bool,
    has_outro_video: bool,
) -> VariantRenderPlan:
    profile = _template_preset_profile(template_variant=template_variant, has_logo=has_logo)

    intro_clip: VariantClip | None = None
    overlay_clip: VariantClip | None = None
    outro_clip: VariantClip | None = None

    if profile.auto_generate_intro and not has_intro_video and profile.intro_preset is not None:
        intro_clip = _preset_clip(profile.intro_preset)

    if profile.main_preset == "gravitational-lens":
        overlay_clip = _preset_clip("gravitational-lens")
    elif profile.main_preset == "yt-lower-third":
        overlay_clip = _preset_clip("yt-lower-third")

    if profile.auto_generate_outro and not has_outro_video and profile.outro_preset is not None:
        outro_clip = _preset_clip(profile.outro_preset)

    return VariantRenderPlan(
        intro_clip=intro_clip,
        overlay_clip=overlay_clip,
        outro_clip=outro_clip,
    )


def _template_preset_profile(*, template_variant: str, has_logo: bool) -> TemplatePresetProfile:
    if template_variant == "vfx-text-cursor":
        return TemplatePresetProfile(
            intro_preset="vfx-text-cursor",
            main_preset=None,
            outro_preset="vfx-text-cursor-outro" if has_logo else None,
            auto_generate_intro=True,
            auto_generate_outro=has_logo,
            uses_logo_as_intro_subject=True,
        )

    if template_variant == "ui-3d-reveal":
        return TemplatePresetProfile(
            intro_preset="ui-3d-reveal",
            main_preset=None,
            outro_preset="ui-3d-reveal-outro" if has_logo else None,
            auto_generate_intro=True,
            auto_generate_outro=has_logo,
            uses_logo_as_intro_subject=True,
        )

    if template_variant == "gravitational-lens":
        return TemplatePresetProfile(
            intro_preset=None,
            main_preset="gravitational-lens",
            outro_preset=None,
            auto_generate_intro=False,
            auto_generate_outro=False,
            uses_logo_as_intro_subject=False,
        )

    if template_variant == "yt-lower-third":
        return TemplatePresetProfile(
            intro_preset=None,
            main_preset="yt-lower-third",
            outro_preset=None,
            auto_generate_intro=False,
            auto_generate_outro=False,
            uses_logo_as_intro_subject=False,
        )

    return TemplatePresetProfile(
        intro_preset="default-logo-reveal" if has_logo else None,
        main_preset="default-host",
        outro_preset=None,
        auto_generate_intro=has_logo,
        auto_generate_outro=False,
        uses_logo_as_intro_subject=has_logo,
    )


def _preset_clip(preset_id: str) -> VariantClip:
    if preset_id == "default-logo-reveal":
        return VariantClip(
            composition_id="default-logo-reveal",
            composition_src="compositions/default-logo-reveal.html",
            duration=4.8,
        )
    if preset_id == "vfx-text-cursor":
        return VariantClip(
            composition_id="vfx-text-cursor",
            composition_src="compositions/vfx-text-cursor.html",
            duration=8.0,
        )
    if preset_id == "vfx-text-cursor-outro":
        return VariantClip(
            composition_id="vfx-text-cursor-outro",
            composition_src="compositions/vfx-text-cursor-outro.html",
            duration=4.8,
        )
    if preset_id == "ui-3d-reveal":
        return VariantClip(
            composition_id="ui-3d-reveal",
            composition_src="compositions/ui-3d-reveal.html",
            duration=13.0,
        )
    if preset_id == "ui-3d-reveal-outro":
        return VariantClip(
            composition_id="ui-3d-reveal-outro",
            composition_src="compositions/ui-3d-reveal-outro.html",
            duration=5.2,
        )
    if preset_id == "gravitational-lens":
        return VariantClip(
            composition_id="gravitational-lens",
            composition_src="compositions/gravitational-lens.html",
            duration=4.0,
        )
    if preset_id == "yt-lower-third":
        return VariantClip(
            composition_id="yt-lower-third",
            composition_src="compositions/yt-lower-third.html",
            duration=4.5,
        )
    raise ValueError(f"Unsupported preset clip: {preset_id}")


def _host_layout_profile(template_family: str, template_variant: str) -> HostLayoutProfile:
    default_source_style = (
        "position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:#000;"
    )
    if template_family == "horizontal":
        default_source_style = (
            "position:absolute; top:50%; left:50%; width:78%; height:78%; transform:translate(-50%, -50%); "
            "object-fit:contain; border-radius:36px; box-shadow:0 32px 80px rgba(0, 0, 0, 0.35); background:#000;"
        )

    if template_variant == "gravitational-lens":
        return HostLayoutProfile(
            use_background_video=False,
            source_video_style=(
                "position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:#000;"
            ),
            logo_style=(
                "top:52px; right:56px; width:220px; height:auto; max-height:110px; object-fit:contain; opacity:0.96; "
                "filter:drop-shadow(0 8px 24px rgba(0, 0, 0, 0.28));"
            ),
        )

    if template_variant == "yt-lower-third":
        return HostLayoutProfile(
            use_background_video=False,
            source_video_style=(
                "position:absolute; inset:0; width:100%; height:100%; object-fit:cover; background:#000;"
            ),
            logo_style=None,
        )

    return HostLayoutProfile(
        use_background_video=template_family == "horizontal",
        source_video_style=default_source_style,
        logo_style=_logo_style(template_family),
    )


def _prepare_variant_render_plan(
    *,
    project_dir: Path,
    template_variant: str,
    logo_relative: str | None,
    source_relative: str,
    has_intro_video: bool,
    has_outro_video: bool,
) -> VariantRenderPlan:
    plan = _resolve_variant_render_plan(
        template_variant=template_variant,
        has_logo=logo_relative is not None,
        has_intro_video=has_intro_video,
        has_outro_video=has_outro_video,
    )
    if plan.intro_clip is not None and plan.intro_clip.composition_id == "default-logo-reveal":
        _write_default_logo_intro_block(project_dir=project_dir, avatar_relative=logo_relative)
    if plan.intro_clip is not None and plan.intro_clip.composition_id == "vfx-text-cursor":
        _write_vfx_text_cursor_intro_block(project_dir=project_dir, avatar_relative=logo_relative)
    if plan.intro_clip is not None and plan.intro_clip.composition_id == "ui-3d-reveal":
        _write_ui_3d_reveal_block(project_dir=project_dir, hero_relative=logo_relative)
    if plan.overlay_clip is not None and plan.overlay_clip.composition_id == "gravitational-lens":
        _write_gravitational_lens_block(project_dir=project_dir)
    if plan.overlay_clip is not None and plan.overlay_clip.composition_id == "yt-lower-third":
        _write_yt_lower_third_block(project_dir=project_dir, avatar_relative=logo_relative)
    if plan.outro_clip is not None and plan.outro_clip.composition_id == "vfx-text-cursor-outro":
        _write_vfx_text_cursor_outro_block(project_dir=project_dir, avatar_relative=logo_relative)
    if plan.outro_clip is not None and plan.outro_clip.composition_id == "ui-3d-reveal-outro":
        _write_ui_3d_reveal_outro_block(project_dir=project_dir, hero_relative=logo_relative)
    return plan


def _write_default_logo_intro_block(*, project_dir: Path, avatar_relative: str | None) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        logo_markup = (
            f'<img class="hero-logo" src="{escape(avatar_relative, quote=True)}" alt="Brand logo" crossorigin="anonymous" />'
            if avatar_relative is not None
            else '<div class="hero-logo hero-logo-fallback">SCR</div>'
        )
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
        <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
        <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@600;700;800;900&display=block\" rel=\"stylesheet\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html, body { width: 1920px; height: 1080px; background: #050816; overflow: hidden; }
            body { font-family: Inter, Arial, sans-serif; }
            [data-composition-id=\"default-logo-reveal\"] {
                position: relative;
                width: 1920px;
                height: 1080px;
                overflow: hidden;
                background:
                    radial-gradient(circle at 50% 30%, rgba(115, 224, 255, 0.18), transparent 26%),
                    radial-gradient(circle at 50% 72%, rgba(255, 225, 117, 0.14), transparent 28%),
                    linear-gradient(180deg, #081120 0%, #040812 100%);
            }
            [data-composition-id=\"default-logo-reveal\"] .halo {
                position: absolute;
                left: 50%;
                top: 44%;
                width: 640px;
                height: 640px;
                transform: translate(-50%, -50%);
                border-radius: 50%;
                background: radial-gradient(circle, rgba(115, 224, 255, 0.26), transparent 62%);
                filter: blur(34px);
            }
            [data-composition-id=\"default-logo-reveal\"] .hero-shell {
                position: absolute;
                left: 50%;
                top: 44%;
                transform: translate(-50%, -50%);
                width: 760px;
                height: 280px;
                border-radius: 42px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(180deg, rgba(255,255,255,0.11), rgba(255,255,255,0.04));
                border: 1px solid rgba(255,255,255,0.14);
                box-shadow: 0 28px 84px rgba(0,0,0,0.42);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
                opacity: 0;
            }
            [data-composition-id=\"default-logo-reveal\"] .hero-logo {
                max-width: 560px;
                max-height: 140px;
                width: auto;
                height: auto;
                object-fit: contain;
                filter: drop-shadow(0 18px 50px rgba(0,0,0,0.45));
            }
            [data-composition-id=\"default-logo-reveal\"] .hero-logo-fallback {
                display: grid;
                place-items: center;
                width: 180px;
                height: 180px;
                border-radius: 40px;
                font-size: 76px;
                font-weight: 900;
                color: #f8fafc;
                background: rgba(255,255,255,0.08);
            }
            [data-composition-id=\"default-logo-reveal\"] .headline {
                position: absolute;
                left: 50%;
                bottom: 176px;
                transform: translateX(-50%);
                font-size: 28px;
                letter-spacing: 0.34em;
                text-transform: uppercase;
                color: rgba(255,255,255,0.78);
                opacity: 0;
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"default-logo-reveal\">
            <div class=\"halo\"></div>
            <div class=\"hero-shell\">__LOGO__</div>
            <div class=\"headline\">Smart Cut Reel</div>
        </div>
        <script>
            const timeline = gsap.timeline({ paused: true });
            timeline.fromTo('.halo', { scale: 0.72, opacity: 0 }, { scale: 1.14, opacity: 1, duration: 1.4, ease: 'power2.out' }, 0);
            timeline.fromTo('.hero-shell', { y: 48, scale: 0.9, opacity: 0 }, { y: 0, scale: 1, opacity: 1, duration: 1.2, ease: 'power3.out' }, 0.2);
            timeline.fromTo('.headline', { y: 20, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: 'power2.out' }, 0.9);
            timeline.to('.hero-shell', { scale: 1.02, duration: 1.2, ease: 'sine.inOut', yoyo: true, repeat: 1 }, 1.6);
            window.__timelines = window.__timelines || {};
            window.__timelines['default-logo-reveal'] = timeline;
        </script>
    </body>
</html>
""".replace("__LOGO__", logo_markup)
        (compositions_dir / "default-logo-reveal.html").write_text(html, encoding="utf-8")


def _write_vfx_text_cursor_intro_block(*, project_dir: Path, avatar_relative: str | None) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        logo_markup = (
            f'<img class="stage-logo" src="{escape(avatar_relative, quote=True)}" alt="Brand logo" crossorigin="anonymous" />'
            if avatar_relative is not None
            else '<div class="stage-logo stage-logo-fallback">SCR</div>'
        )
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
        <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
        <link href=\"https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800;900&family=Inter:wght@600;700;800;900&display=block\" rel=\"stylesheet\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html, body { width: 1920px; height: 1080px; background: #000; overflow: hidden; }
            body { font-family: Inter, Arial, sans-serif; }
            #root {
                position: relative;
                width: 1920px;
                height: 1080px;
                overflow: hidden;
                background:
                    radial-gradient(circle at 20% 25%, rgba(85, 216, 255, 0.18), transparent 28%),
                    radial-gradient(circle at 82% 18%, rgba(255, 92, 223, 0.15), transparent 30%),
                    linear-gradient(180deg, #05070b 0%, #020304 100%);
            }
            #root .stage-grid {
                position: absolute;
                inset: 0;
                background-image:
                    linear-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
                background-size: 90px 90px;
                mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.2), rgba(0, 0, 0, 0.85));
                opacity: 0.28;
            }
            #root .stage-glow {
                position: absolute;
                inset: 0;
                background:
                    radial-gradient(circle at 50% 46%, rgba(73, 242, 255, 0.22), transparent 22%),
                    radial-gradient(circle at 50% 46%, rgba(255, 79, 216, 0.14), transparent 34%);
                filter: blur(30px);
            }
            #root .logo-aura {
                position: absolute;
                left: 50%;
                top: 43%;
                width: 980px;
                height: 980px;
                border-radius: 50%;
                transform: translate(-50%, -50%);
                background:
                    radial-gradient(circle, rgba(246, 255, 122, 0.2) 0%, rgba(73, 242, 255, 0.14) 34%, rgba(255, 79, 216, 0.08) 52%, transparent 72%);
                filter: blur(44px);
                opacity: 0.8;
            }
            #root .logo-shell {
                position: absolute;
                left: 50%;
                top: 45%;
                width: 980px;
                height: 360px;
                transform: translate(-50%, -50%);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 2;
                opacity: 0;
                filter: drop-shadow(0 0 26px rgba(73, 242, 255, 0.24));
            }
            #root .logo-shell::before {
                content: \"\";
                position: absolute;
                inset: -18px -28px;
                border-radius: 40px;
                border: 1px solid rgba(255, 255, 255, 0.08);
                background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01));
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
            }
            #root .stage-logo {
                position: relative;
                z-index: 1;
                max-width: 760px;
                max-height: 240px;
                width: auto;
                height: auto;
                object-fit: contain;
                filter:
                    drop-shadow(0 0 18px rgba(73, 242, 255, 0.22))
                    drop-shadow(0 0 28px rgba(255, 79, 216, 0.16))
                    drop-shadow(0 18px 70px rgba(0, 0, 0, 0.55));
            }
            #root .stage-logo-fallback {
                display: grid;
                place-items: center;
                width: 280px;
                height: 280px;
                border-radius: 72px;
                font-size: 112px;
                font-weight: 900;
                letter-spacing: 0.08em;
                color: #f6ff7a;
                background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.05));
                border: 1px solid rgba(255,255,255,0.18);
            }
            #root #next-card {
                position: absolute;
                left: 120px;
                top: 68px;
                width: 1680px;
                height: 945px;
                padding: 96px 126px;
                border-radius: 56px;
                background: linear-gradient(160deg, rgba(255, 255, 255, 0.11) 0%, rgba(255, 255, 255, 0.045) 42%, rgba(255, 255, 255, 0.018) 70%, rgba(255, 255, 255, 0.075) 100%);
                backdrop-filter: blur(14px) saturate(1.12);
                -webkit-backdrop-filter: blur(14px) saturate(1.12);
                border: 1px solid rgba(255, 255, 255, 0.17);
                box-shadow: 0 30px 90px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.22);
                transform-origin: 50% 50%;
                z-index: 3;
                opacity: 0;
                overflow: hidden;
            }
            #root #next-card::before {
                content: \"\";
                position: absolute;
                inset: 0;
                background:
                    radial-gradient(circle at 18% 78%, rgba(73, 242, 255, 0.14), transparent 38%),
                    radial-gradient(circle at 82% 22%, rgba(255, 79, 216, 0.11), transparent 34%);
                pointer-events: none;
            }
            #root .card-text {
                position: absolute;
                z-index: 1;
                left: 126px;
                right: 126px;
                top: 96px;
                bottom: 96px;
                margin: 0;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                color: #ffffff;
                text-align: center;
            }
            #root #phrase-a {
                font-size: 276px;
                line-height: 0.88;
                font-weight: 900;
                text-shadow: -5px 0 18px rgba(73, 242, 255, 0.38), 5px 0 18px rgba(255, 79, 216, 0.28), 0 24px 80px rgba(0, 0, 0, 0.58);
            }
            #root #phrase-b {
                font-size: 156px;
                line-height: 0.94;
                font-weight: 800;
                text-shadow: -5px 0 18px rgba(73, 242, 255, 0.24), 5px 0 18px rgba(255, 79, 216, 0.18), 0 24px 80px rgba(0, 0, 0, 0.58);
            }
            #root .card-text > span { display: block; white-space: nowrap; }
            #root .headline-word { display: inline-block; }
            #root .html-word {
                position: relative;
                width: 1.9em;
                margin-right: 0.08em;
                text-align: left;
                color: #f6ff7a;
                font-family: \"Big Shoulders Display\", Impact, sans-serif;
                font-weight: 900;
                letter-spacing: 0.015em;
                text-transform: uppercase;
                text-shadow: -6px 0 16px rgba(73, 242, 255, 0.48), 6px 0 16px rgba(255, 79, 216, 0.34), 0 0 24px rgba(246, 255, 122, 0.34), 0 24px 72px rgba(0, 0, 0, 0.56);
            }
            #root .html-type,
            #root .html-caret { display: inline-block; }
            #root .html-caret {
                position: absolute;
                left: 0;
                top: 0;
                opacity: 0;
                color: #f6ff7a;
                text-shadow: 0 0 12px rgba(246, 255, 122, 0.7), -4px 0 14px rgba(73, 242, 255, 0.36), 4px 0 14px rgba(255, 79, 216, 0.26);
            }
            #root .supporting-word {
                opacity: 0;
                transform: translateY(54px) scale(0.96);
                filter: blur(10px);
            }
            #root .canvas-word {
                color: #ffffff;
                text-shadow: -4px 0 18px rgba(246, 255, 122, 0.26), 5px 0 18px rgba(255, 79, 216, 0.25), 0 22px 72px rgba(0, 0, 0, 0.58);
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"vfx-text-cursor\" data-width=\"1920\" data-height=\"1080\" data-start=\"0\" data-duration=\"8\">
            <div class=\"stage-grid\"></div>
            <div class=\"stage-glow\"></div>
            <div id=\"logo-aura\" class=\"logo-aura\"></div>
            <div id=\"logo-shell\" class=\"logo-shell\">
                __LOGO_MARKUP__
            </div>
            <div id=\"next-card\" aria-hidden=\"true\">
                <h1 id=\"phrase-a\" class=\"card-text\">
                    <span><span class=\"headline-word html-word\"><span class=\"html-type\"></span><span class=\"html-caret\">|</span></span> <span class=\"headline-word supporting-word\">in</span></span>
                    <span><span class=\"headline-word supporting-word canvas-word\">motion</span></span>
                </h1>
                <h2 id=\"phrase-b\" class=\"card-text\">
                    <span>Ready for</span>
                    <span>Smart Cut Reel</span>
                </h2>
            </div>
        </div>
        <script>
            window.__timelines = window.__timelines || {};
            var tl = gsap.timeline({ paused: true });
            var logoShell = document.getElementById("logo-shell");
            var logoAura = document.getElementById("logo-aura");
            var nextCard = document.getElementById("next-card");
            var phraseA = document.getElementById("phrase-a");
            var phraseB = document.getElementById("phrase-b");
            var htmlWord = document.querySelector(".html-word");
            var htmlType = document.querySelector(".html-type");
            var htmlCaret = document.querySelector(".html-caret");
            var supportingWords = Array.from(document.querySelectorAll(".supporting-word"));
            var htmlText = "LOGO";

            function addTextCardSequence(htmlStart) {
                var typeStep = 0.085;
                var titleHold = 0.25;
                var typeEnd = htmlStart + (htmlText.length - 1) * typeStep;
                var slideStart = typeEnd + titleHold;
                var slideEnd = slideStart + 0.05;

                tl.call(function () {
                    htmlType.textContent = "";
                    htmlCaret.style.left = "0px";
                }, [], 0);
                tl.set(htmlWord, { x: 0, y: 0, scale: 1.24, transformOrigin: "50% 50%" }, 0);
                tl.set(htmlCaret, { opacity: 0 }, 0);
                tl.set(htmlCaret, { opacity: 1 }, htmlStart - 0.05);

                for (var i = 1; i <= htmlText.length; i += 1) {
                    (function (idx) {
                        tl.call(function () {
                            htmlType.textContent = htmlText.slice(0, idx);
                            htmlCaret.style.left = htmlType.offsetWidth + "px";
                            if (idx === htmlText.length) {
                                htmlCaret.style.opacity = "0";
                            }
                        }, [], htmlStart + (idx - 1) * typeStep);
                    })(i);
                }

                tl.to(htmlWord, { x: 0, y: 0, scale: 1, duration: 0.05, ease: "power2.out" }, slideStart);
                tl.to(supportingWords, { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", duration: 0.42, stagger: 0.08, ease: "expo.out" }, slideEnd);
                return slideEnd + 0.42 + (supportingWords.length - 1) * 0.08;
            }

            tl.set(logoShell, { opacity: 0, y: 180, scale: 1.16, filter: "blur(14px)" }, 0);
            tl.set(logoAura, { opacity: 0.15, scale: 0.8 }, 0);
            tl.set(nextCard, { opacity: 0, scale: 1.45, filter: "blur(14px)" }, 0);
            tl.set(phraseA, { opacity: 1, x: 0, y: 0, scale: 1, filter: "blur(0px)" }, 0);
            tl.set(supportingWords, { opacity: 0, y: 54, scale: 0.96, filter: "blur(10px)" }, 0);
            tl.set(phraseB, { opacity: 0, x: 1480, y: 0, scale: 1, filter: "blur(8px)" }, 0);

            tl.to(logoAura, { opacity: 0.72, scale: 1.06, duration: 0.9, ease: "power3.out" }, 0.08);
            tl.to(logoShell, { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", duration: 1.05, ease: "power4.out" }, 0.0);
            tl.to(logoShell, { scale: 1.03, duration: 1.2, ease: "sine.inOut", yoyo: true, repeat: 1 }, 1.18);
            tl.to(logoAura, { opacity: 0.84, duration: 0.32, ease: "sine.inOut", yoyo: true, repeat: 4 }, 1.1);
            tl.to(logoShell, { scale: 0.44, y: -272, duration: 0.24, ease: "expo.in" }, 2.9);
            tl.to(logoAura, { opacity: 0, scale: 1.18, duration: 0.24, ease: "expo.in" }, 2.9);

            tl.set(nextCard, { opacity: 1, scale: 1.45, filter: "blur(14px)" }, 3.1);
            tl.to(nextCard, { scale: 0.88, filter: "blur(0px)", duration: 0.9, ease: "power4.out" }, 3.1);
            tl.to(nextCard, { scale: 0.84, filter: "blur(1.5px)", duration: 0.4, ease: "none" }, 4.0);
            var phraseAReady = addTextCardSequence(3.15);
            var phraseAExit = phraseAReady + 0.5;
            var phraseBStart = phraseAExit + 0.36;
            tl.to(phraseA, { x: -1480, filter: "blur(8px)", duration: 0.36, ease: "power2.in" }, phraseAExit);
            tl.set(phraseA, { opacity: 0 }, phraseBStart);
            tl.set(phraseB, { opacity: 1, x: 1480, y: 0, scale: 1, filter: "blur(8px)" }, phraseBStart);
            tl.to(phraseB, { x: 0, filter: "blur(0px)", duration: 0.48, ease: "expo.out" }, phraseBStart);
            window.__timelines["vfx-text-cursor"] = tl;
        </script>
    </body>
</html>
""".replace("__LOGO_MARKUP__", logo_markup)
        (compositions_dir / "vfx-text-cursor.html").write_text(html, encoding="utf-8")


def _write_vfx_text_cursor_outro_block(*, project_dir: Path, avatar_relative: str | None) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        logo_markup = (
            f'<img class="outro-logo" src="{escape(avatar_relative, quote=True)}" alt="Brand logo" crossorigin="anonymous" />'
            if avatar_relative is not None
            else '<div class="outro-logo outro-logo-fallback">SCR</div>'
        )
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
        <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
        <link href=\"https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800;900&family=Inter:wght@600;700;800&display=block\" rel=\"stylesheet\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html, body { width: 1920px; height: 1080px; background: #000; overflow: hidden; }
            body { font-family: Inter, Arial, sans-serif; }
            #root {
                position: relative;
                width: 1920px;
                height: 1080px;
                overflow: hidden;
                background:
                    radial-gradient(circle at 50% 50%, rgba(73, 242, 255, 0.14), transparent 26%),
                    linear-gradient(180deg, #04070d 0%, #020304 100%);
            }
            #root .frame {
                position: absolute;
                inset: 94px 140px;
                border-radius: 56px;
                border: 1px solid rgba(255,255,255,0.14);
                background: linear-gradient(160deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
                box-shadow: 0 30px 90px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.18);
                opacity: 0;
            }
            #root .outro-logo {
                position: absolute;
                left: 50%;
                top: 46%;
                transform: translate(-50%, -50%);
                max-width: 620px;
                max-height: 180px;
                width: auto;
                height: auto;
                object-fit: contain;
                filter: drop-shadow(0 0 18px rgba(73, 242, 255, 0.22)) drop-shadow(0 0 28px rgba(255, 79, 216, 0.16));
                opacity: 0;
            }
            #root .outro-logo-fallback {
                display: grid;
                place-items: center;
                width: 220px;
                height: 220px;
                border-radius: 54px;
                font: 900 88px/1 Inter, Arial, sans-serif;
                color: #f6ff7a;
                background: rgba(255,255,255,0.06);
            }
            #root .caption {
                position: absolute;
                left: 50%;
                bottom: 154px;
                transform: translateX(-50%);
                font-family: 'Big Shoulders Display', Impact, sans-serif;
                font-size: 84px;
                letter-spacing: 0.08em;
                color: #f7fafc;
                text-transform: uppercase;
                opacity: 0;
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"vfx-text-cursor-outro\" data-width=\"1920\" data-height=\"1080\" data-start=\"0\" data-duration=\"4.8\">
            <div class=\"frame\"></div>
            __LOGO__
            <div class=\"caption\">Stay in frame</div>
        </div>
        <script>
            const timeline = gsap.timeline({ paused: true });
            timeline.fromTo('.frame', { scale: 0.94, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.7, ease: 'power3.out' }, 0);
            timeline.fromTo('.outro-logo', { y: 26, opacity: 0, scale: 0.92 }, { y: 0, opacity: 1, scale: 1, duration: 0.8, ease: 'power3.out' }, 0.28);
            timeline.fromTo('.caption', { y: 18, opacity: 0 }, { y: 0, opacity: 1, duration: 0.55, ease: 'power2.out' }, 0.7);
            timeline.to('.caption', { opacity: 0.24, duration: 1.1, ease: 'sine.inOut' }, 2.5);
            window.__timelines = window.__timelines || {};
            window.__timelines['vfx-text-cursor-outro'] = timeline;
        </script>
    </body>
</html>
""".replace("__LOGO__", logo_markup)
        (compositions_dir / "vfx-text-cursor-outro.html").write_text(html, encoding="utf-8")


def _write_gravitational_lens_block(*, project_dir: Path) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            html, body { width: 1920px; height: 1080px; overflow: hidden; background: transparent; }
            #root { position: relative; width: 1920px; height: 1080px; overflow: hidden; }
            .lens-core {
                position: absolute;
                left: 50%;
                top: 50%;
                width: 360px;
                height: 360px;
                border-radius: 999px;
                transform: translate(-50%, -50%);
                background: radial-gradient(circle, rgba(255,255,255,0.22) 0%, rgba(126,247,197,0.18) 20%, rgba(86,100,255,0.12) 48%, rgba(0,0,0,0) 72%);
                border: 1px solid rgba(255,255,255,0.14);
                box-shadow: 0 0 40px rgba(118,247,197,0.3), 0 0 120px rgba(86,100,255,0.25);
                backdrop-filter: blur(8px) saturate(1.2);
            }
            .halo {
                position: absolute;
                inset: -18%;
                background: radial-gradient(circle, rgba(118,247,197,0.2) 0%, rgba(86,100,255,0.12) 24%, rgba(0,0,0,0) 56%);
                mix-blend-mode: screen;
                opacity: 0.7;
            }
            .ring {
                position: absolute;
                left: 50%;
                top: 50%;
                width: 540px;
                height: 540px;
                border-radius: 999px;
                transform: translate(-50%, -50%);
                border: 1px solid rgba(255,255,255,0.14);
                box-shadow: inset 0 0 32px rgba(255,255,255,0.08), 0 0 36px rgba(255,255,255,0.08);
            }
            .chromatic {
                position: absolute;
                inset: 0;
                background:
                    radial-gradient(circle at 46% 50%, rgba(255,90,164,0.15), transparent 16%),
                    radial-gradient(circle at 54% 50%, rgba(80,220,255,0.15), transparent 16%);
                mix-blend-mode: screen;
                filter: blur(20px);
                opacity: 0;
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"gravitational-lens\" data-width=\"1920\" data-height=\"1080\" data-start=\"0\" data-duration=\"4\">
            <div class=\"halo\"></div>
            <div id=\"ring\" class=\"ring\"></div>
            <div id=\"core\" class=\"lens-core\"></div>
            <div id=\"chromatic\" class=\"chromatic\"></div>
        </div>
        <script>
            window.__timelines = window.__timelines || {};
            var tl = gsap.timeline({ paused: true });
            tl.fromTo('#core', { scale: 0.16, opacity: 0 }, { scale: 1.12, opacity: 1, duration: 1.6, ease: 'expo.out' }, 0);
            tl.fromTo('#ring', { scale: 0.3, opacity: 0 }, { scale: 1.08, opacity: 1, duration: 1.5, ease: 'expo.out' }, 0.1);
            tl.to('#core', { scale: 2.8, opacity: 0, duration: 1.05, ease: 'expo.inOut' }, 2.2);
            tl.to('#ring', { scale: 3.4, opacity: 0, duration: 1.1, ease: 'expo.inOut' }, 2.15);
            tl.to('#chromatic', { opacity: 1, duration: 0.45, ease: 'sine.inOut', yoyo: true, repeat: 3 }, 1.9);
            window.__timelines['gravitational-lens'] = tl;
        </script>
    </body>
</html>
"""
        (compositions_dir / "gravitational-lens.html").write_text(html, encoding="utf-8")


def _write_yt_lower_third_block(*, project_dir: Path, avatar_relative: str | None) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        avatar_markup = (
                f'<img class="avatar-image" src="{escape(avatar_relative, quote=True)}" alt="Avatar" crossorigin="anonymous" />'
                if avatar_relative is not None
                else '<div class="avatar-image avatar-fallback">SCR</div>'
        )
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            html, body { width: 1920px; height: 1080px; overflow: hidden; background: transparent; font-family: Arial, sans-serif; }
            #root { position: relative; width: 1920px; height: 1080px; overflow: hidden; }
            #shell {
                position: absolute;
                left: 84px;
                bottom: 76px;
                width: 900px;
                display: grid;
                grid-template-columns: 120px 1fr auto;
                gap: 28px;
                align-items: center;
                padding: 22px 28px;
                border-radius: 34px;
                background: rgba(12, 13, 18, 0.78);
                border: 1px solid rgba(255, 255, 255, 0.12);
                box-shadow: 0 22px 70px rgba(0,0,0,0.42);
                backdrop-filter: blur(12px) saturate(1.18);
            }
            .avatar-image {
                width: 120px;
                height: 120px;
                border-radius: 999px;
                object-fit: cover;
                border: 3px solid rgba(255,255,255,0.14);
            }
            .avatar-fallback {
                display: grid;
                place-items: center;
                font-size: 46px;
                font-weight: 800;
                color: white;
                background: linear-gradient(135deg, #ff003c 0%, #ff5a7a 100%);
            }
            .eyebrow { font-size: 22px; letter-spacing: 0.24em; text-transform: uppercase; color: rgba(255,255,255,0.55); }
            .title { margin-top: 10px; font-size: 52px; font-weight: 800; color: #ffffff; }
            .subtitle { margin-top: 6px; font-size: 26px; color: rgba(255,255,255,0.72); }
            .subscribe {
                padding: 18px 26px;
                border-radius: 999px;
                background: linear-gradient(180deg, #ff003c 0%, #d7002f 100%);
                color: white;
                font-weight: 800;
                font-size: 28px;
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"yt-lower-third\" data-width=\"1920\" data-height=\"1080\" data-start=\"0\" data-duration=\"4.5\">
            <div id=\"shell\">
                __AVATAR_MARKUP__
                <div>
                    <div class=\"eyebrow\">YouTube</div>
                    <div class=\"title\">Smart Cut Reel</div>
                    <div class=\"subtitle\">Subscribe for new finishing drops</div>
                </div>
                <div class=\"subscribe\">Subscribe</div>
            </div>
        </div>
        <script>
            window.__timelines = window.__timelines || {};
            var tl = gsap.timeline({ paused: true });
            tl.fromTo('#shell', { x: -340, y: 40, opacity: 0, scale: 0.94 }, { x: 0, y: 0, opacity: 1, scale: 1, duration: 0.7, ease: 'expo.out' }, 0);
            tl.to('#shell', { scale: 1.02, duration: 0.26, yoyo: true, repeat: 1, ease: 'sine.inOut' }, 1.15);
            tl.to('#shell', { x: -240, opacity: 0, duration: 0.55, ease: 'power2.in' }, 3.7);
            window.__timelines['yt-lower-third'] = tl;
        </script>
    </body>
</html>
""".replace("__AVATAR_MARKUP__", avatar_markup)
        (compositions_dir / "yt-lower-third.html").write_text(html, encoding="utf-8")


def _write_ui_3d_reveal_block(*, project_dir: Path, hero_relative: str | None) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        hero_markup = (
                f'<img class="panel-media" src="{escape(hero_relative, quote=True)}" alt="Hero asset" crossorigin="anonymous" />'
                if hero_relative is not None
                else '<div class="panel-media panel-fallback">UI</div>'
        )
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            html, body { width: 1920px; height: 1080px; overflow: hidden; background: linear-gradient(180deg, #090b12 0%, #111827 100%); font-family: Arial, sans-serif; }
            #root { position: relative; width: 1920px; height: 1080px; overflow: hidden; perspective: 1800px; }
            .back-grid {
                position: absolute;
                inset: 0;
                background-image: linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px);
                background-size: 96px 96px;
                opacity: 0.26;
            }
            #panel {
                position: absolute;
                left: 240px;
                top: 122px;
                width: 1440px;
                height: 836px;
                border-radius: 46px;
                overflow: hidden;
                border: 1px solid rgba(255,255,255,0.14);
                background: linear-gradient(160deg, rgba(255,255,255,0.11), rgba(255,255,255,0.03));
                box-shadow: 0 40px 120px rgba(0,0,0,0.45);
                transform-style: preserve-3d;
            }
            .panel-media {
                position: absolute;
                inset: 36px;
                width: calc(100% - 72px);
                height: calc(100% - 72px);
                border-radius: 30px;
                object-fit: contain;
                background: radial-gradient(circle at top, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
            }
            .panel-fallback {
                display: grid;
                place-items: center;
                font-size: 156px;
                font-weight: 900;
                color: rgba(255,255,255,0.85);
            }
            .caption {
                position: absolute;
                left: 280px;
                bottom: 142px;
                padding: 18px 28px;
                border-radius: 999px;
                background: rgba(255,255,255,0.08);
                color: #ffffff;
                letter-spacing: 0.2em;
                text-transform: uppercase;
                font-size: 20px;
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"ui-3d-reveal\" data-width=\"1920\" data-height=\"1080\" data-start=\"0\" data-duration=\"13\">
            <div class=\"back-grid\"></div>
            <div id=\"panel\">__HERO_MARKUP__</div>
            <div id=\"caption\" class=\"caption\">3D UI Reveal</div>
        </div>
        <script>
            window.__timelines = window.__timelines || {};
            var tl = gsap.timeline({ paused: true });
            tl.fromTo('#panel', { opacity: 0, rotateX: 28, rotateY: -28, z: -600, y: 120, scale: 0.72 }, { opacity: 1, rotateX: 0, rotateY: 0, z: 0, y: 0, scale: 1, duration: 1.45, ease: 'expo.out' }, 0);
            tl.fromTo('#caption', { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.5, ease: 'expo.out' }, 0.75);
            tl.to('#panel', { rotateY: 12, x: 28, duration: 1.6, ease: 'sine.inOut', yoyo: true, repeat: 1 }, 2.1);
            tl.to('#panel', { scale: 0.92, y: -14, duration: 0.85, ease: 'power2.inOut' }, 5.8);
            tl.to('#caption', { opacity: 0, y: -26, duration: 0.35, ease: 'power2.in' }, 10.8);
            tl.to('#panel', { opacity: 0, rotateX: -16, rotateY: 22, z: -480, y: -40, duration: 0.8, ease: 'expo.in' }, 11.2);
            window.__timelines['ui-3d-reveal'] = tl;
        </script>
    </body>
</html>
""".replace("__HERO_MARKUP__", hero_markup)
        (compositions_dir / "ui-3d-reveal.html").write_text(html, encoding="utf-8")


def _write_ui_3d_reveal_outro_block(*, project_dir: Path, hero_relative: str | None) -> None:
        compositions_dir = project_dir / "compositions"
        compositions_dir.mkdir(parents=True, exist_ok=True)
        hero_markup = (
            f'<img class="hero-mark" src="{escape(hero_relative, quote=True)}" alt="Brand logo" crossorigin="anonymous" />'
            if hero_relative is not None
            else '<div class="hero-mark hero-mark-fallback">SCR</div>'
        )
        html = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=1920, height=1080\" />
        <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
        <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
        <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@600;700;800&display=block\" rel=\"stylesheet\" />
        <script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            html, body { width: 1920px; height: 1080px; background: #07101c; overflow: hidden; }
            body { font-family: Inter, Arial, sans-serif; }
            [data-composition-id=\"ui-3d-reveal-outro\"] {
                position: relative;
                width: 1920px;
                height: 1080px;
                overflow: hidden;
                background:
                    radial-gradient(circle at 24% 18%, rgba(91, 143, 255, 0.2), transparent 24%),
                    radial-gradient(circle at 74% 72%, rgba(255, 95, 143, 0.18), transparent 24%),
                    linear-gradient(160deg, #07101c 0%, #050a12 100%);
            }
            [data-composition-id=\"ui-3d-reveal-outro\"] .panel {
                position: absolute;
                left: 270px;
                top: 156px;
                width: 1380px;
                height: 768px;
                border-radius: 48px;
                border: 1px solid rgba(255,255,255,0.14);
                background: linear-gradient(180deg, rgba(255,255,255,0.09), rgba(255,255,255,0.03));
                box-shadow: 0 40px 120px rgba(0,0,0,0.45);
                transform: perspective(1800px) rotateY(-14deg) rotateX(7deg);
                opacity: 0;
            }
            [data-composition-id=\"ui-3d-reveal-outro\"] .hero-mark {
                position: absolute;
                left: 50%;
                top: 46%;
                transform: translate(-50%, -50%);
                max-width: 520px;
                max-height: 170px;
                width: auto;
                height: auto;
                object-fit: contain;
                filter: drop-shadow(0 22px 54px rgba(0,0,0,0.4));
                opacity: 0;
            }
            [data-composition-id=\"ui-3d-reveal-outro\"] .hero-mark-fallback {
                display: grid;
                place-items: center;
                width: 200px;
                height: 200px;
                border-radius: 48px;
                font: 900 82px/1 Inter, Arial, sans-serif;
                color: #f8fafc;
                background: rgba(255,255,255,0.08);
            }
            [data-composition-id=\"ui-3d-reveal-outro\"] .footer-copy {
                position: absolute;
                left: 50%;
                bottom: 162px;
                transform: translateX(-50%);
                font-size: 28px;
                letter-spacing: 0.32em;
                text-transform: uppercase;
                color: rgba(255,255,255,0.78);
                opacity: 0;
            }
        </style>
    </head>
    <body>
        <div id=\"root\" data-composition-id=\"ui-3d-reveal-outro\">
            <div class=\"panel\"></div>
            __HERO__
            <div class=\"footer-copy\">Render complete</div>
        </div>
        <script>
            const timeline = gsap.timeline({ paused: true });
            timeline.fromTo('.panel', { x: 120, opacity: 0 }, { x: 0, opacity: 1, duration: 0.9, ease: 'power3.out' }, 0);
            timeline.fromTo('.hero-mark', { y: 30, opacity: 0, scale: 0.9 }, { y: 0, opacity: 1, scale: 1, duration: 0.8, ease: 'power3.out' }, 0.35);
            timeline.fromTo('.footer-copy', { y: 20, opacity: 0 }, { y: 0, opacity: 1, duration: 0.55, ease: 'power2.out' }, 0.9);
            window.__timelines = window.__timelines || {};
            window.__timelines['ui-3d-reveal-outro'] = timeline;
        </script>
    </body>
</html>
""".replace("__HERO__", hero_markup)
        (compositions_dir / "ui-3d-reveal-outro.html").write_text(html, encoding="utf-8")
