from __future__ import annotations

from typing import Literal

from services.common.media import aspect_ratio_label
from services.common.media import find_video_stream
from services.common.media import normalized_dimensions
from services.common.media import probe_video_bytes

from services.hyperframes_finishing.models import DetectedOrientation
from services.hyperframes_finishing.models import TemplateFamily


def detect_orientation(video_bytes: bytes, *, suffix: str = ".mp4") -> tuple[DetectedOrientation, int, int, int]:
    probe_document = probe_video_bytes(video_bytes, suffix=suffix)
    stream = find_video_stream(probe_document)
    width, height, rotation = normalized_dimensions(stream)
    ratio = aspect_ratio_label(width, height)
    if ratio == "9:16":
        return "vertical", width, height, rotation
    if ratio == "16:9":
        return "horizontal", width, height, rotation
    return "manual_required", width, height, rotation


def resolve_template_family(
    *,
    requested: TemplateFamily,
    detected: DetectedOrientation,
) -> Literal["vertical", "horizontal"]:
    if requested in {"vertical", "horizontal"}:
        return requested
    if detected == "manual_required":
        raise ValueError("template_family=auto is not allowed for square or ambiguous video input")
    return detected
