from __future__ import annotations

from datetime import datetime
import json
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


JobStatus = Literal["created", "queued", "rendering", "completed", "failed"]
TemplateFamily = Literal["auto", "vertical", "horizontal"]
DetectedOrientation = Literal["vertical", "horizontal", "manual_required"]
RevisionType = Literal["draft", "named", "final_candidate"]
RenderMode = Literal["draft", "final"]


class ArtifactEntry(BaseModel):
    artifact_key: str
    object_key: str
    content_type: str
    size_bytes: int | None = None
    created_at: datetime


class RenderJobRecord(BaseModel):
    job_id: str
    project_id: str | None = None
    revision_id: str | None = None
    render_mode: RenderMode = "draft"
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    template_family: TemplateFamily
    template_variant: str = "default"
    orientation_detected: DetectedOrientation
    progress_percent: int = Field(default=0, ge=0, le=100)
    output_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_by: str | None = None
    artifacts: dict[str, ArtifactEntry] = Field(default_factory=dict)


class JobCreateResponse(BaseModel):
    job_id: str
    project_id: str | None = None
    revision_id: str | None = None
    render_mode: RenderMode = "draft"
    status: JobStatus
    template_family: TemplateFamily
    orientation_detected: DetectedOrientation
    progress_percent: int


class JobStatusResponse(BaseModel):
    job_id: str
    project_id: str | None
    revision_id: str | None
    render_mode: RenderMode
    status: JobStatus
    template_family: TemplateFamily
    template_variant: str
    orientation_detected: DetectedOrientation
    progress_percent: int
    output_url: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    artifacts: dict[str, ArtifactEntry]


class RevisionRecord(BaseModel):
    revision_id: str
    project_id: str
    revision_name: str
    revision_type: RevisionType = "draft"
    template_family: Literal["vertical", "horizontal"]
    template_variant: str = "default"
    orientation_detected: DetectedOrientation
    workspace_root: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    notes: str | None = None


class ProjectRecord(BaseModel):
    project_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    template_family: Literal["vertical", "horizontal"]
    template_variant: str = "default"
    orientation_detected: DetectedOrientation
    brand_theme: str = "default"
    subtitle_theme: str = "glassmorphism"
    created_by: str | None = None
    active_revision_id: str
    assets: NormalizedAssets


class RevisionSummaryResponse(BaseModel):
    revision_id: str
    revision_name: str
    revision_type: RevisionType
    template_family: Literal["vertical", "horizontal"]
    template_variant: str
    orientation_detected: DetectedOrientation
    workspace_root: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    notes: str | None = None


class RenderJobSummaryResponse(BaseModel):
    job_id: str
    project_id: str | None = None
    revision_id: str | None = None
    render_mode: RenderMode = "draft"
    status: JobStatus
    template_family: TemplateFamily
    template_variant: str
    orientation_detected: DetectedOrientation
    progress_percent: int
    output_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectSummaryResponse(BaseModel):
    project_id: str
    name: str
    created_at: datetime
    updated_at: datetime
    template_family: Literal["vertical", "horizontal"]
    template_variant: str
    orientation_detected: DetectedOrientation
    brand_theme: str
    subtitle_theme: str
    active_revision_id: str


class ProjectDetailResponse(ProjectSummaryResponse):
    created_by: str | None = None
    assets: NormalizedAssets
    revisions: list[RevisionSummaryResponse] = Field(default_factory=list)
    render_jobs: list[RenderJobSummaryResponse] = Field(default_factory=list)


class NormalizedAssets(BaseModel):
    source_video: str
    intro_video: str | None = None
    outro_video: str | None = None
    logo_image: str | None = None
    subtitle_file: str | None = None


class CompositionConfig(BaseModel):
    brand_theme: str = "default"
    subtitle_theme: str = "glassmorphism"
    safe_zone_profile: str


class NormalizedRenderSpec(BaseModel):
    job_id: str
    template_family: Literal["vertical", "horizontal"]
    template_variant: str = "default"
    orientation_detected: DetectedOrientation
    assets: NormalizedAssets
    composition: CompositionConfig


class SubtitleWord(BaseModel):
    text: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "SubtitleWord":
        if self.end <= self.start:
            raise ValueError("subtitle cue end time must be greater than start time")
        return self


class SubtitleSegment(BaseModel):
    text: str | None = None
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    words: list[SubtitleWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_segment(self) -> "SubtitleSegment":
        if self.words:
            if self.start is not None and self.words[0].start < self.start:
                raise ValueError("subtitle words must start inside their segment range")
            if self.end is not None and self.words[-1].end > self.end:
                raise ValueError("subtitle words must end inside their segment range")
            return self

        text = (self.text or "").strip()
        if not text:
            raise ValueError("subtitle segment text is required when no words are provided")
        if self.start is None or self.end is None:
            raise ValueError("subtitle segments without words require start and end timestamps")
        if self.end <= self.start:
            raise ValueError("subtitle cue end time must be greater than start time")
        return self


class SubtitleDocument(BaseModel):
    words: list[SubtitleWord] = Field(default_factory=list)
    segments: list[SubtitleSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_document(self) -> "SubtitleDocument":
        if not self.words and not self.segments:
            raise ValueError("subtitle payload must contain at least one word or segment")
        return self


def parse_subtitle_document(filename: str, content: bytes) -> SubtitleDocument:
    suffix = _file_suffix(filename)
    if suffix == ".srt":
        return SubtitleDocument(segments=_parse_srt_segments(content.decode("utf-8")))

    try:
        payload = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("subtitle file must be valid JSON or SRT") from exc

    if isinstance(payload, dict):
        return SubtitleDocument(
            words=[SubtitleWord.model_validate(item) for item in _as_list(payload.get("words"))],
            segments=[SubtitleSegment.model_validate(item) for item in _as_list(payload.get("segments"))],
        )
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "word" in payload[0]:
            return SubtitleDocument(words=[SubtitleWord.model_validate(item) for item in payload])
        return SubtitleDocument(segments=[SubtitleSegment.model_validate(item) for item in payload])
    raise ValueError("subtitle JSON must be an object or list")


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("subtitle JSON fields 'words' and 'segments' must be arrays")
    return value


def _file_suffix(filename: str) -> str:
    parts = filename.rsplit(".", 1)
    if len(parts) != 2:
        return ""
    return f".{parts[1].lower()}"


def _parse_srt_segments(content: str) -> list[SubtitleSegment]:
    blocks = [block.strip() for block in content.replace("\r\n", "\n").split("\n\n") if block.strip()]
    segments: list[SubtitleSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing_line = lines[1] if "-->" in lines[1] else lines[0]
        if "-->" not in timing_line:
            raise ValueError("invalid SRT timing line")
        start_raw, end_raw = [part.strip() for part in timing_line.split("-->", 1)]
        text_lines = lines[2:] if timing_line == lines[1] else lines[1:]
        segments.append(
            SubtitleSegment(
                text=" ".join(text_lines).strip(),
                start=_parse_srt_timestamp(start_raw),
                end=_parse_srt_timestamp(end_raw),
            )
        )
    return segments


def _parse_srt_timestamp(value: str) -> float:
    time_part, millis_part = value.split(",", 1)
    hours_str, minutes_str, seconds_str = time_part.split(":", 2)
    hours = int(hours_str)
    minutes = int(minutes_str)
    seconds = int(seconds_str)
    millis = int(millis_part)
    return (hours * 3600) + (minutes * 60) + seconds + (millis / 1000.0)
