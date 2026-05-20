from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.hyperframes_finishing.api import create_app
from services.hyperframes_finishing.rendering import MockHyperframesRenderExecutor
from services.hyperframes_finishing.service import HyperframesFinishingService
from services.hyperframes_finishing.storage import HyperframesFilesystemStore


class HyperframesFinishingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = HyperframesFilesystemStore(Path(self.temp_dir.name))
        self.service = HyperframesFinishingService(
            store=self.store,
            renderer=MockHyperframesRenderExecutor(),
        )
        self.client = TestClient(create_app(service=self.service))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_create_job_endpoint_returns_job_payload(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        response = self.client.post(
            "/jobs",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
            },
            data={
                "template_family": "auto",
                "start_immediately": "false",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["template_family"], "vertical")

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_run_and_status_endpoints_complete_job(self, mock_detect) -> None:
        mock_detect.return_value = ("horizontal", 1920, 1080, 0)

        created = self.client.post(
            "/jobs",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
            },
            data={
                "template_family": "auto",
                "start_immediately": "false",
            },
        )
        job_id = created.json()["job_id"]

        run_response = self.client.post(f"/jobs/{job_id}/run")
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json()["status"], "completed")

        status_response = self.client.get(f"/jobs/{job_id}/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "completed")

        output_response = self.client.get(f"/jobs/{job_id}/output")
        self.assertEqual(output_response.status_code, 200)
        self.assertEqual(output_response.content, b"video-bytes")

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_artifact_endpoint_returns_normalized_render_spec(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        created = self.client.post(
            "/jobs",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
            },
            data={
                "template_family": "auto",
                "start_immediately": "false",
            },
        )
        job_id = created.json()["job_id"]
        self.client.post(f"/jobs/{job_id}/run")

        artifact_response = self.client.get(
            f"/jobs/{job_id}/artifacts/normalized_render_spec"
        )
        self.assertEqual(artifact_response.status_code, 200)
        self.assertIn("template_family", artifact_response.json())

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_create_job_rejects_invalid_subtitle_payload(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        response = self.client.post(
            "/jobs",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
                "subtitle_file": (
                    "captions.json",
                    b'{"words": [{"text": "bad", "start": 1.0, "end": 0.5}]}',
                    "application/json",
                ),
            },
            data={
                "template_family": "auto",
                "start_immediately": "false",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("end time", response.json()["detail"])

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_create_project_endpoint_returns_project_payload(self, mock_detect) -> None:
        mock_detect.return_value = ("horizontal", 1920, 1080, 0)

        response = self.client.post(
            "/projects",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
                "logo_image": ("logo.png", b"logo-bytes", "image/png"),
            },
            data={
                "project_name": "Bugaboo Promo",
                "template_family": "auto",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Bugaboo Promo")
        self.assertEqual(payload["template_family"], "horizontal")
        self.assertEqual(len(payload["revisions"]), 1)

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_project_detail_and_revisions_endpoints_return_created_project(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        created = self.client.post(
            "/projects",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
            },
            data={
                "project_name": "Vertical Cut",
                "template_family": "auto",
            },
        )
        project_id = created.json()["project_id"]

        detail_response = self.client.get(f"/projects/{project_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["project_id"], project_id)

        revisions_response = self.client.get(f"/projects/{project_id}/revisions")
        self.assertEqual(revisions_response.status_code, 200)
        self.assertEqual(len(revisions_response.json()), 1)

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_render_project_draft_endpoint_creates_project_linked_job(self, mock_detect) -> None:
        mock_detect.return_value = ("horizontal", 1920, 1080, 0)

        created = self.client.post(
            "/projects",
            files={
                "source_video": ("clip.mp4", b"video-bytes", "video/mp4"),
            },
            data={
                "project_name": "Render Draft Project",
                "template_family": "auto",
            },
        )
        project_id = created.json()["project_id"]
        revision_id = created.json()["active_revision_id"]

        response = self.client.post(
            f"/projects/{project_id}/render-draft",
            params={"start_immediately": "false"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project_id"], project_id)
        self.assertEqual(payload["revision_id"], revision_id)

        detail = self.client.get(f"/projects/{project_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["render_jobs"]), 1)