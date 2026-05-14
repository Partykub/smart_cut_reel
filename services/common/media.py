"""Media probing helpers shared by Phase 1 services."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
from typing import Mapping


def run_ffprobe(file_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(file_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "ffprobe failed"
        raise ValueError(detail)

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid JSON") from exc


def probe_video_bytes(data: bytes, suffix: str = ".mp4") -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / f"input{suffix}"
        src.write_bytes(data)
        return run_ffprobe(src)


def build_proxy_video_bytes(data: bytes, *, proxy_height: int, suffix: str = ".mp4") -> bytes:
    if proxy_height <= 0:
        raise ValueError("proxy_height must be greater than zero")

    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / f"input{suffix}"
        dst = Path(tmp_dir) / "proxy.mp4"
        src.write_bytes(data)

        completed = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-vf",
                f"scale=-2:{proxy_height}",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(dst),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed"
            raise ValueError(detail)

        return dst.read_bytes()


def find_video_stream(document: Mapping[str, Any]) -> dict[str, Any]:
    streams = document.get("streams", [])
    if not isinstance(streams, list):
        raise ValueError("ffprobe output is missing a valid streams list")

    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            return stream
    raise ValueError("ffprobe output does not contain a video stream")


def parse_fraction(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return 0.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            numerator_value = float(numerator)
            denominator_value = float(denominator)
        except ValueError:
            return 0.0
        if denominator_value == 0:
            return 0.0
        return numerator_value / denominator_value
    try:
        return float(value)
    except ValueError:
        return 0.0


def extract_rotation_degrees(stream: Mapping[str, Any]) -> int:
    tags = stream.get("tags")
    if isinstance(tags, dict):
        rotate_value = tags.get("rotate")
        if rotate_value is not None:
            try:
                return int(float(rotate_value)) % 360
            except (TypeError, ValueError):
                pass

    side_data_list = stream.get("side_data_list")
    if isinstance(side_data_list, list):
        for item in side_data_list:
            if not isinstance(item, dict):
                continue
            rotation_value = item.get("rotation")
            if rotation_value is None:
                continue
            try:
                return int(float(rotation_value)) % 360
            except (TypeError, ValueError):
                continue
    return 0


def normalized_dimensions(stream: Mapping[str, Any]) -> tuple[int, int, int]:
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("video stream is missing width or height")

    rotation = extract_rotation_degrees(stream)
    if rotation in {90, 270}:
        return height, width, rotation
    return width, height, rotation


def aspect_ratio_label(width: int, height: int) -> str:
    if height == 0:
        raise ValueError("height must be greater than zero")
    ratio = width / height
    if abs(ratio - (16.0 / 9.0)) <= 0.05:
        return "16:9"
    if abs(ratio - (9.0 / 16.0)) <= 0.05:
        return "9:16"
    return f"{width}:{height}"


def even_scaled_width(*, width: int, height: int, target_height: int) -> int:
    if width <= 0 or height <= 0 or target_height <= 0:
        raise ValueError("width, height, and target_height must be greater than zero")
    scaled_width = width * (target_height / height)
    even_width = int(round(scaled_width / 2.0) * 2)
    return max(2, even_width)


def build_sampled_frames_payload(
    *,
    job_id: str,
    duration_seconds: float,
    sample_fps: float,
    source_width: int,
    source_height: int,
    proxy_width: int,
    proxy_height: int,
) -> dict[str, Any]:
    if sample_fps <= 0:
        raise ValueError("sample_fps must be greater than zero")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")

    frame_interval = 1.0 / sample_fps
    frames: list[dict[str, Any]] = []
    index = 0
    timestamp = 0.0
    limit = duration_seconds + (frame_interval * 0.25)
    while timestamp <= limit:
        frames.append(
            {
                "index": index,
                "t": round(min(timestamp, duration_seconds), 6),
            }
        )
        index += 1
        timestamp = index * frame_interval

    return {
        "job_id": job_id,
        "sample_fps": sample_fps,
        "frame_interval_seconds": round(frame_interval, 6),
        "source_resolution": {"width": source_width, "height": source_height},
        "proxy_resolution": {"width": proxy_width, "height": proxy_height},
        "frames": frames,
    }
