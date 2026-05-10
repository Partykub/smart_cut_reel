"""Pipeline runner abstraction for P1-A03 and beyond."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from typing import Any
from typing import Protocol

from .artifact_helper import ArtifactHelper
from .contracts import ARTIFACT_PRODUCERS
from .contracts import REFRAME_ONLY_STEP_IDS
from .manifest_manager import ManifestManager
from .manifest_manager import utc_now
from .path_resolver import artifact_path
from .path_resolver import input_path
from .path_resolver import job_prefix
from .path_resolver import manifest_path
from .path_resolver import validate_artifact_key


def artifact_keys_for_step(step_id: str) -> tuple[str, ...]:
    return tuple(
        artifact_key
        for artifact_key, produced_by in ARTIFACT_PRODUCERS.items()
        if produced_by == step_id
    )


class PipelineExecutionError(RuntimeError):
    """Raised when a pipeline step cannot complete successfully."""


class PipelineRunner(Protocol):
    def run(
        self,
        *,
        job_id: str,
        manifest_manager: ManifestManager,
        artifact_helper: ArtifactHelper,
    ) -> dict[str, Any]:
        raise NotImplementedError


class HttpPipelineRunner:
    """Sequential HTTP runner for calling each service `/run` endpoint."""

    def __init__(
        self,
        *,
        service_endpoints: Mapping[str, str],
        minio_bucket: str,
        request_timeout_seconds: float = 600.0,
        step_timeouts_seconds: Mapping[str, float] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.service_endpoints = dict(service_endpoints)
        self.minio_bucket = minio_bucket
        self.request_timeout_seconds = request_timeout_seconds
        self.step_timeouts_seconds = dict(step_timeouts_seconds or {})
        self.client_factory = client_factory

    def run(
        self,
        *,
        job_id: str,
        manifest_manager: ManifestManager,
        artifact_helper: ArtifactHelper,
    ) -> dict[str, Any]:
        del artifact_helper

        job_manifest = manifest_manager.read_job_manifest(job_id)
        pipeline_steps = tuple(job_manifest["pipeline"]["steps"])

        with self._create_client() as client:
            for index, step_id in enumerate(pipeline_steps):
                started_at = utc_now()
                manifest_manager.set_step_state(
                    job_id,
                    step_id,
                    step_status="running",
                    started_at=started_at,
                    overall_status="running",
                    current_step=step_id,
                )

                try:
                    response_document = self._invoke_step(
                        client=client,
                        job_id=job_id,
                        step_id=step_id,
                        job_manifest=job_manifest,
                    )
                    self._register_outputs(
                        job_id=job_id,
                        step_id=step_id,
                        response_document=response_document,
                        manifest_manager=manifest_manager,
                    )
                    self._append_warnings(
                        job_id=job_id,
                        step_id=step_id,
                        response_document=response_document,
                        manifest_manager=manifest_manager,
                    )
                except PipelineExecutionError as exc:
                    manifest_manager.set_step_state(
                        job_id,
                        step_id,
                        step_status="failed",
                        finished_at=utc_now(),
                        overall_status="failed",
                        current_step=None,
                    )
                    manifest_manager.append_error(job_id, f"{step_id}: {exc}")
                    return manifest_manager.read_service_status(job_id)

                next_step = pipeline_steps[index + 1] if index + 1 < len(pipeline_steps) else None
                manifest_manager.set_step_state(
                    job_id,
                    step_id,
                    step_status="success",
                    finished_at=utc_now(),
                    overall_status="running" if next_step is not None else "success",
                    current_step=next_step,
                )

        return manifest_manager.read_service_status(job_id)

    def _create_client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()

        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "The 'httpx' package is required to use HttpPipelineRunner."
            ) from exc

        return httpx.Client(timeout=self.request_timeout_seconds)

    def _invoke_step(
        self,
        *,
        client: Any,
        job_id: str,
        step_id: str,
        job_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        request_payload = self._build_request_payload(
            job_id=job_id,
            step_id=step_id,
            job_manifest=job_manifest,
        )
        request_url = self._run_url(step_id)
        step_timeout = self.step_timeouts_seconds.get(step_id)

        try:
            if step_timeout is not None:
                response = client.post(request_url, json=request_payload, timeout=step_timeout)
            else:
                response = client.post(request_url, json=request_payload)
        except Exception as exc:
            raise PipelineExecutionError(f"request to {request_url} failed: {exc}") from exc

        if response.status_code >= 400:
            raise PipelineExecutionError(
                f"service returned HTTP {response.status_code}: {response.text.strip() or 'no response body'}"
            )

        try:
            response_document = response.json()
        except ValueError as exc:
            raise PipelineExecutionError("service returned invalid JSON") from exc

        if response_document.get("service_id") not in {None, step_id}:
            raise PipelineExecutionError(
                f"service_id mismatch: expected '{step_id}', got '{response_document.get('service_id')}'."
            )

        if response_document.get("status") != "success":
            detail = response_document.get("error") or response_document.get("message")
            if not detail:
                detail = f"service returned status '{response_document.get('status')}'."
            raise PipelineExecutionError(str(detail))

        return response_document

    def _build_request_payload(
        self,
        *,
        job_id: str,
        step_id: str,
        job_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "step_id": step_id,
            "minio": {
                "bucket": self.minio_bucket,
                "prefix": job_prefix(job_id),
            },
            "inputs": {
                "source_video": input_path(job_id),
                "job_manifest": manifest_path(job_id, "job_manifest"),
                "artifact_manifest": manifest_path(job_id, "artifact_manifest"),
                "service_status": manifest_path(job_id, "service_status"),
            },
            "expected_outputs": {
                artifact_key: artifact_path(job_id, artifact_key)
                for artifact_key in artifact_keys_for_step(step_id)
            },
            "config": job_manifest.get("service_config", {}).get(step_id, {}),
        }

    def _run_url(self, step_id: str) -> str:
        endpoint = self.service_endpoints.get(step_id)
        if not endpoint:
            raise PipelineExecutionError(f"no service endpoint configured for step '{step_id}'.")

        normalized = endpoint.rstrip("/")
        if normalized.endswith("/run"):
            return normalized
        return f"{normalized}/run"

    def _register_outputs(
        self,
        *,
        job_id: str,
        step_id: str,
        response_document: dict[str, Any],
        manifest_manager: ManifestManager,
    ) -> None:
        outputs = response_document.get("outputs", {})
        if not isinstance(outputs, dict):
            raise PipelineExecutionError("service response field 'outputs' must be an object.")

        expected_artifacts = artifact_keys_for_step(step_id)
        for artifact_key, object_key in outputs.items():
            try:
                validate_artifact_key(artifact_key)
            except KeyError as exc:
                raise PipelineExecutionError(str(exc)) from exc

            if ARTIFACT_PRODUCERS[artifact_key] != step_id:
                raise PipelineExecutionError(
                    f"artifact '{artifact_key}' is owned by '{ARTIFACT_PRODUCERS[artifact_key]}', not '{step_id}'."
                )

            expected_object_key = artifact_path(job_id, artifact_key)
            if object_key != expected_object_key:
                raise PipelineExecutionError(
                    f"artifact '{artifact_key}' must be written to '{expected_object_key}', got '{object_key}'."
                )

        missing_artifacts = [artifact_key for artifact_key in expected_artifacts if artifact_key not in outputs]
        if missing_artifacts:
            raise PipelineExecutionError(
                "service did not return required outputs: " + ", ".join(missing_artifacts)
            )

        for artifact_key in expected_artifacts:
            manifest_manager.register_artifact(job_id, artifact_key, produced_by=step_id)

    def _append_warnings(
        self,
        *,
        job_id: str,
        step_id: str,
        response_document: dict[str, Any],
        manifest_manager: ManifestManager,
    ) -> None:
        warnings = response_document.get("warnings", [])
        if not isinstance(warnings, list):
            raise PipelineExecutionError("service response field 'warnings' must be an array.")

        for warning in warnings:
            if not isinstance(warning, dict):
                raise PipelineExecutionError("each warning must be an object with at least code and message.")

            code = warning.get("code")
            message = warning.get("message")
            if not isinstance(code, str) or not isinstance(message, str):
                raise PipelineExecutionError("each warning must include string fields 'code' and 'message'.")

            manifest_manager.append_warning(
                job_id,
                code=code,
                message=message,
                step=warning.get("step") if isinstance(warning.get("step"), str) else step_id,
                created_at=warning.get("created_at") if isinstance(warning.get("created_at"), str) else utc_now(),
            )


class MockPipelineRunner:
    """Local fallback runner that walks the job's pipeline without calling services."""

    def run(
        self,
        *,
        job_id: str,
        manifest_manager: ManifestManager,
        artifact_helper: ArtifactHelper,
    ) -> dict[str, Any]:
        del artifact_helper

        steps = manifest_manager.pipeline_steps(job_id) or REFRAME_ONLY_STEP_IDS

        for index, step_id in enumerate(steps):
            started_at = utc_now()
            manifest_manager.set_step_state(
                job_id,
                step_id,
                step_status="running",
                started_at=started_at,
                overall_status="running",
                current_step=step_id,
            )

            next_step = steps[index + 1] if index + 1 < len(steps) else None
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
            step=steps[0],
        )
        return manifest_manager.read_service_status(job_id)
