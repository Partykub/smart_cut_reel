from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.hyperframes_finishing.rendering import MockHyperframesRenderExecutor
from services.hyperframes_finishing.service import CreateJobInput
from services.hyperframes_finishing.service import HyperframesFinishingService
from services.hyperframes_finishing.service import UploadedAsset
from services.hyperframes_finishing.storage import HyperframesFilesystemStore
from services.hyperframes_finishing.worker import process_queued_jobs_once


class HyperframesWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = HyperframesFilesystemStore(Path(self.temp_dir.name))
        self.service = HyperframesFinishingService(
            store=self.store,
            renderer=MockHyperframesRenderExecutor(),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_process_queued_jobs_once_runs_pending_job(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)
        created = self.service.create_job(
            CreateJobInput(
                source_video=UploadedAsset(
                    filename="clip.mp4",
                    content=b"video-bytes",
                    content_type="video/mp4",
                ),
            )
        )

        processed = process_queued_jobs_once(self.service)

        self.assertEqual(processed, [created.job_id])
        status = self.service.get_job_status(created.job_id)
        self.assertEqual(status.status, "completed")