"""Phase 1 proxy/frame sampling service implementation."""

from __future__ import annotations

from services.common.media import build_proxy_video_bytes
from services.common.media import build_sampled_frames_payload
from services.common.media import even_scaled_width
from services.common.media import find_video_stream
from services.common.media import normalized_dimensions
from services.common.media import parse_fraction
from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


class ProxyFrameSamplingService:
    service_id = "proxy_frame_sampling"

    def run(self, context: ServiceContext) -> RunResponse:
        job_manifest = context.read_json(context.input_key("job_manifest"))
        source_bytes = context.read_bytes(context.input_key("source_video"))

        config = job_manifest.get("service_config", {}).get(self.service_id, {})
        sample_fps = float(context.request.config.get("sample_fps", config.get("sample_fps", 5)))
        proxy_height = int(context.request.config.get("proxy_height", config.get("proxy_height", 540)))

        width, height, duration_seconds = self._source_metadata(context, source_bytes)
        proxy_width = even_scaled_width(width=width, height=height, target_height=proxy_height)
        proxy_bytes = build_proxy_video_bytes(source_bytes, proxy_height=proxy_height)
        sampled_frames_payload = build_sampled_frames_payload(
            job_id=context.job_id,
            duration_seconds=duration_seconds,
            sample_fps=sample_fps,
            source_width=width,
            source_height=height,
            proxy_width=proxy_width,
            proxy_height=proxy_height,
        )

        proxy_key = context.expected_output_key("proxy")
        sampled_frames_key = context.expected_output_key("sampled_frames")
        context.write_bytes(proxy_key, proxy_bytes, content_type="video/mp4")
        context.write_json(sampled_frames_key, sampled_frames_payload)

        return RunResponse(
            service_id=self.service_id,
            outputs={
                "proxy": proxy_key,
                "sampled_frames": sampled_frames_key,
            },
        )

    def _source_metadata(self, context: ServiceContext, source_bytes: bytes) -> tuple[int, int, float]:
        artifact_manifest_key = context.request.inputs.get("artifact_manifest")
        if artifact_manifest_key and context.exists(artifact_manifest_key):
            artifact_manifest = context.read_json(artifact_manifest_key)
            metadata_entry = artifact_manifest.get("artifacts", {}).get("metadata", {})
            metadata_object_key = metadata_entry.get("object_key")
            if isinstance(metadata_object_key, str) and context.exists(metadata_object_key):
                metadata = context.read_json(metadata_object_key)
                width = int(metadata.get("width") or 0)
                height = int(metadata.get("height") or 0)
                duration = float(metadata.get("duration") or 0.0)
                if width > 0 and height > 0 and duration > 0:
                    return width, height, duration

        probe_document = probe_video_bytes(source_bytes)
        stream = find_video_stream(probe_document)
        width, height, _rotation = normalized_dimensions(stream)
        duration = parse_fraction(probe_document.get("format", {}).get("duration"))
        if duration <= 0:
            raise ValueError("source video duration must be greater than zero")
        return width, height, duration
