from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.hyperframes_finishing.service import CreateJobInput
from services.hyperframes_finishing.service import HyperframesFinishingService
from services.hyperframes_finishing.service import UploadedAsset


@dataclass(frozen=True)
class PreviewSpec:
    variant: str
    brand_theme: str
    subtitle_theme: str
    poster_time_seconds: float
    include_logo: bool = True


PREVIEW_SPECS: tuple[PreviewSpec, ...] = (
    PreviewSpec(
        variant="gravitational-lens",
        brand_theme="bold",
        subtitle_theme="default",
        poster_time_seconds=1.0,
        include_logo=False,
    ),
    PreviewSpec(
        variant="vfx-text-cursor",
        brand_theme="glassmorphism",
        subtitle_theme="glassmorphism",
        poster_time_seconds=2.6,
    ),
    PreviewSpec(
        variant="yt-lower-third",
        brand_theme="bold",
        subtitle_theme="glassmorphism",
        poster_time_seconds=1.2,
        include_logo=False,
    ),
    PreviewSpec(
        variant="ui-3d-reveal",
        brand_theme="default",
        subtitle_theme="default",
        poster_time_seconds=2.8,
    ),
)


def _resolve_asset(path_value: str, *, label: str) -> Path:
    path = (PROJECT_ROOT / path_value).resolve()
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _read_uploaded_asset(path: Path) -> UploadedAsset:
    return UploadedAsset(
        filename=path.name,
        content=path.read_bytes(),
        content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def _probe_duration_seconds(video_path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    return max(float(completed.stdout.strip() or 0.0), 0.0)


def _render_poster(video_path: Path, poster_path: Path, *, seek_seconds: float) -> None:
    poster_path.parent.mkdir(parents=True, exist_ok=True)
    duration_seconds = _probe_duration_seconds(video_path)
    clamped_seek_seconds = min(seek_seconds, max(duration_seconds - 0.05, 0.0))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{clamped_seek_seconds:.2f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(poster_path),
        ],
        check=True,
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    source_video_path = _resolve_asset(
        os.getenv("SMART_CUT_PREVIEW_SOURCE_VIDEO", "temp_work/horizontal.mp4"),
        label="preview source video",
    )
    logo_path = _resolve_asset(
        os.getenv(
            "SMART_CUT_PREVIEW_LOGO_IMAGE",
            ".hyperframes-finishing-data/projects/hfp_1f242fc6b90a/assets/logo_image.png",
        ),
        label="preview logo image",
    )

    output_dir = PROJECT_ROOT / "frontend" / "public" / "hyperframes-previews"
    output_dir.mkdir(parents=True, exist_ok=True)

    service = HyperframesFinishingService()
    source_asset = _read_uploaded_asset(source_video_path)
    logo_asset = _read_uploaded_asset(logo_path)

    manifest: dict[str, object] = {
        "source_video": str(source_video_path.relative_to(PROJECT_ROOT)),
        "logo_image": str(logo_path.relative_to(PROJECT_ROOT)),
        "generated_previews": [],
    }

    for spec in PREVIEW_SPECS:
        print(f"Rendering preview for {spec.variant}...")
        response = service.create_job(
            CreateJobInput(
                source_video=source_asset,
                template_family="horizontal",
                template_variant=spec.variant,
                brand_theme=spec.brand_theme,
                subtitle_theme=spec.subtitle_theme,
                created_by="hyperframes_catalog_preview_generator",
                logo_image=logo_asset if spec.include_logo else None,
            )
        )
        status = service.run_job(response.job_id)
        if status.status != "completed":
            raise RuntimeError(
                f"preview render failed for {spec.variant}: {status.error_code or 'unknown'} {status.error_message or ''}".strip()
            )

        target_video = output_dir / f"{spec.variant}.mp4"
        target_poster = output_dir / f"{spec.variant}.png"
        shutil.copyfile(
            PROJECT_ROOT / ".hyperframes-finishing-data" / "jobs" / response.job_id / "output" / "final.mp4",
            target_video,
        )
        _render_poster(target_video, target_poster, seek_seconds=spec.poster_time_seconds)

        manifest["generated_previews"].append(
            {
                "variant": spec.variant,
                "job_id": response.job_id,
                "video": f"hyperframes-previews/{target_video.name}",
                "poster": f"hyperframes-previews/{target_poster.name}",
            }
        )

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(PREVIEW_SPECS)} preview videos in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())