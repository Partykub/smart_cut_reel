from __future__ import annotations

from services.hyperframes_finishing.service import HyperframesFinishingService


def process_queued_jobs_once(service: HyperframesFinishingService | None = None) -> list[str]:
    worker_service = service or HyperframesFinishingService()
    processed: list[str] = []
    for job_id in worker_service.list_queued_job_ids():
        worker_service.run_job(job_id)
        processed.append(job_id)
    return processed
