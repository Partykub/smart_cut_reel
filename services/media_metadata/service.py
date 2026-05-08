"""Phase 1 media metadata service implementation."""

from __future__ import annotations

from typing import Any

from services.common.media import aspect_ratio_label
from services.common.media import find_video_stream
from services.common.media import normalized_dimensions
from services.common.media import parse_fraction
from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


class MediaMetadataService:
    service_id = "media_metadata"

    def run(self, context: ServiceContext) -> RunResponse:
        job_manifest = context.read_json(context.input_key("job_manifest"))
        source_bytes = context.read_bytes(context.input_key("source_video"))
        probe_document = probe_video_bytes(source_bytes)
        stream = find_video_stream(probe_document)
        width, height, rotation = normalized_dimensions(stream)

        metadata_payload = {
            "job_id": context.job_id,
            "width": width,
            "height": height,
            "fps": round(parse_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate")), 6),
            "duration": round(parse_fraction(probe_document.get("format", {}).get("duration")), 6),
            "codec": stream.get("codec_name") or "unknown",
            "rotation_degrees": rotation,
            "source_aspect_ratio": aspect_ratio_label(width, height),
            "target_aspect_ratio": job_manifest.get("target_output", {}).get("aspect_ratio", "9:16"),
            "target_resolution": job_manifest.get("target_output", {}).get(
                "resolution",
                {"width": 1080, "height": 1920},
            ),
            "target_crop": _target_crop(width=width, height=height),
        }

        output_key = context.expected_output_key("metadata")
        context.write_json(output_key, metadata_payload)
        return RunResponse(service_id=self.service_id, outputs={"metadata": output_key})


def _target_crop(*, width: int, height: int) -> dict[str, int]:
    crop_height = height
    crop_width = int(round((crop_height * 9.0 / 16.0) / 2.0) * 2)
    crop_width = max(2, min(crop_width, width))
    return {"width": crop_width, "height": crop_height}
