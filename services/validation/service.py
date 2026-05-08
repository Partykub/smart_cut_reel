"""Phase 1 validation service implementation."""

from __future__ import annotations

from typing import Any

from services.common.media import aspect_ratio_label
from services.common.media import find_video_stream
from services.common.media import normalized_dimensions
from services.common.media import parse_fraction
from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext
from services.common.runtime import ServiceWarning


class ValidationService:
    service_id = "validation"

    def run(self, context: ServiceContext) -> RunResponse:
        job_manifest = context.read_json(context.input_key("job_manifest"))
        source_key = context.input_key("source_video")
        source_bytes = context.read_bytes(source_key)

        source_input = job_manifest.get("input", {}).get("source_video", {})
        if source_input.get("object_key") != source_key:
            raise ValueError("job_manifest source_video object_key does not match request inputs")

        target_output = job_manifest.get("target_output", {})
        if target_output.get("aspect_ratio") != "9:16":
            raise ValueError("target_output.aspect_ratio must be '9:16'")

        probe_document = probe_video_bytes(source_bytes)
        stream = find_video_stream(probe_document)
        width, height, _rotation = normalized_dimensions(stream)

        if aspect_ratio_label(width, height) != "16:9":
            raise ValueError(f"source video must be close to 16:9, got {width}x{height}")

        duration = parse_fraction(probe_document.get("format", {}).get("duration"))
        if duration <= 0:
            raise ValueError("source video duration must be greater than zero")

        warnings: list[ServiceWarning] = []
        requested_resolution = target_output.get("resolution") or {}
        if requested_resolution.get("width") != 1080 or requested_resolution.get("height") != 1920:
            warnings.append(
                ServiceWarning(
                    code="VALIDATION_TARGET_RESOLUTION_UNVERIFIED",
                    message="Validation currently assumes the canonical Phase 1 1080x1920 output.",
                    step=self.service_id,
                )
            )

        return RunResponse(service_id=self.service_id, warnings=warnings)
