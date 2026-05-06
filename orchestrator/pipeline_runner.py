"""Pipeline runner abstraction for P1-A03 and beyond."""

from __future__ import annotations

from typing import Any
from typing import Protocol

from .contracts import PIPELINE_STEP_IDS
from .artifact_helper import ArtifactHelper
from .manifest_manager import ManifestManager
from .manifest_manager import utc_now


class PipelineRunner(Protocol):
    def run(
        self,
        *,
        job_id: str,
        manifest_manager: ManifestManager,
        artifact_helper: ArtifactHelper,
    ) -> dict[str, Any]:
        raise NotImplementedError


class MockPipelineRunner:
    """Temporary runner used until P1-A04 implements real service orchestration."""

    def run(
        self,
        *,
        job_id: str,
        manifest_manager: ManifestManager,
        artifact_helper: ArtifactHelper,
    ) -> dict[str, Any]:
        del artifact_helper

        for index, step_id in enumerate(PIPELINE_STEP_IDS):
            started_at = utc_now()
            manifest_manager.set_step_state(
                job_id,
                step_id,
                step_status="running",
                started_at=started_at,
                overall_status="running",
                current_step=step_id,
            )

            next_step = PIPELINE_STEP_IDS[index + 1] if index + 1 < len(PIPELINE_STEP_IDS) else None
            manifest_manager.set_step_state(
                job_id,
                step_id,
                step_status="success",
                finished_at=utc_now(),
                overall_status="running" if next_step is not None else "success",
                current_step=next_step,
            )

        manifest_manager.append_warning(
            job_id,
            code="PIPELINE_RUNNER_MOCK",
            message="Mock pipeline runner completed without calling external services.",
            step=PIPELINE_STEP_IDS[0],
        )
        return manifest_manager.read_service_status(job_id)
