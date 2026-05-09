"""Pydantic request/response models for downstream service HTTP adapters."""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from services.common.runtime import RunMinIO
from services.common.runtime import RunRequest
from services.common.runtime import RunResponse
from services.common.runtime import ServiceWarning


class ApiRunMinIO(BaseModel):
    bucket: str
    prefix: str

    def to_runtime(self) -> RunMinIO:
        return RunMinIO(bucket=self.bucket, prefix=self.prefix)


class ApiRunRequest(BaseModel):
    job_id: str
    step_id: str
    minio: ApiRunMinIO
    inputs: dict[str, str]
    expected_outputs: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)

    def to_runtime(self) -> RunRequest:
        return RunRequest(
            job_id=self.job_id,
            step_id=self.step_id,
            minio=self.minio.to_runtime(),
            inputs=dict(self.inputs),
            expected_outputs=dict(self.expected_outputs),
            config=dict(self.config),
        )


class ApiServiceWarning(BaseModel):
    code: str
    message: str
    step: str | None = None
    created_at: str | None = None

    @classmethod
    def from_runtime(cls, warning: ServiceWarning) -> "ApiServiceWarning":
        return cls(
            code=warning.code,
            message=warning.message,
            step=warning.step,
            created_at=warning.created_at,
        )


class ApiRunResponse(BaseModel):
    service_id: str
    status: Literal["success"] = "success"
    outputs: dict[str, str] = Field(default_factory=dict)
    warnings: list[ApiServiceWarning] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_runtime(cls, response: RunResponse) -> "ApiRunResponse":
        return cls(
            service_id=response.service_id,
            status=response.status,
            outputs=dict(response.outputs),
            warnings=[ApiServiceWarning.from_runtime(warning) for warning in response.warnings],
            metrics=dict(response.metrics),
        )
