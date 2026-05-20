from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.hyperframes_finishing.rendering import MockHyperframesRenderExecutor
from services.hyperframes_finishing.service import CreateJobInput
from services.hyperframes_finishing.service import CreateProjectInput
from services.hyperframes_finishing.service import HyperframesFinishingService
from services.hyperframes_finishing.service import UploadedAsset
from services.hyperframes_finishing.storage import HyperframesFilesystemStore


class HyperframesFinishingServiceTests(unittest.TestCase):
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
    def test_create_job_persists_assets_and_returns_queued_status(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        response = self.service.create_job(
            CreateJobInput(
                source_video=UploadedAsset(
                    filename="clip.mp4",
                    content=b"video-bytes",
                    content_type="video/mp4",
                ),
                logo_image=UploadedAsset(
                    filename="logo.png",
                    content=b"logo-bytes",
                    content_type="image/png",
                ),
            )
        )

        self.assertEqual(response.status, "queued")
        self.assertEqual(response.template_family, "vertical")
        paths = self.store.job_paths(response.job_id)
        request_payload = self.store.read_json(paths.request_json)
        self.assertEqual(request_payload["template_family"], "vertical")
        self.assertTrue(self.store.exists(request_payload["assets"]["source_video"]))
        self.assertTrue(self.store.exists(request_payload["assets"]["logo_image"]))

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_run_job_writes_output_and_artifacts(self, mock_detect) -> None:
        mock_detect.return_value = ("horizontal", 1920, 1080, 0)

        response = self.service.create_job(
            CreateJobInput(
                source_video=UploadedAsset(
                    filename="clip.mp4",
                    content=b"video-bytes",
                    content_type="video/mp4",
                ),
            )
        )

        status = self.service.run_job(response.job_id)
        self.assertEqual(status.status, "completed")
        self.assertIn("normalized_render_spec", status.artifacts)
        self.assertIn("output_video", status.artifacts)
        output_bytes = self.service.read_output(response.job_id)
        self.assertEqual(output_bytes, b"video-bytes")

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_auto_template_rejects_ambiguous_input(self, mock_detect) -> None:
        mock_detect.return_value = ("manual_required", 1000, 1000, 0)

        with self.assertRaises(ValueError):
            self.service.create_job(
                CreateJobInput(
                    source_video=UploadedAsset(
                        filename="square.mp4",
                        content=b"video-bytes",
                        content_type="video/mp4",
                    ),
                )
            )

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_create_job_rejects_invalid_subtitle_payload_early(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        with self.assertRaises(ValueError):
            self.service.create_job(
                CreateJobInput(
                    source_video=UploadedAsset(
                        filename="clip.mp4",
                        content=b"video-bytes",
                        content_type="video/mp4",
                    ),
                    subtitle_file=UploadedAsset(
                        filename="captions.json",
                        content=b'{"words": [{"text": "bad", "start": 1.0, "end": 0.5}]}',
                        content_type="application/json",
                    ),
                )
            )

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_create_project_scaffolds_initial_revision_and_workspace(self, mock_detect) -> None:
        mock_detect.return_value = ("horizontal", 1920, 1080, 0)

        project = self.service.create_project(
            CreateProjectInput(
                project_name="Bugaboo Promo",
                source_video=UploadedAsset(
                    filename="clip.mp4",
                    content=b"video-bytes",
                    content_type="video/mp4",
                ),
                template_variant="gravitational-lens",
                logo_image=UploadedAsset(
                    filename="logo.png",
                    content=b"logo-bytes",
                    content_type="image/png",
                ),
            )
        )

        self.assertEqual(project.name, "Bugaboo Promo")
        self.assertEqual(project.template_family, "horizontal")
        self.assertEqual(project.template_variant, "gravitational-lens")
        self.assertEqual(len(project.revisions), 1)
        revision = project.revisions[0]
        self.assertEqual(revision.template_variant, "gravitational-lens")
        manifest_key = f"{revision.workspace_root}/project.manifest.json"
        self.assertTrue(self.store.exists(manifest_key))
        manifest = self.store.read_json(manifest_key)
        self.assertEqual(manifest["template_variant"], "gravitational-lens")
        self.assertTrue(self.store.exists(f"{revision.workspace_root}/hyperframes.json"))

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_list_projects_returns_created_project(self, mock_detect) -> None:
        mock_detect.return_value = ("vertical", 1080, 1920, 0)

        project = self.service.create_project(
            CreateProjectInput(
                project_name="Vertical Cut",
                source_video=UploadedAsset(
                    filename="clip.mp4",
                    content=b"video-bytes",
                    content_type="video/mp4",
                ),
            )
        )

        projects = self.service.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].project_id, project.project_id)

    @patch("services.hyperframes_finishing.service.detect_orientation")
    def test_create_draft_render_links_job_back_to_project_and_revision(self, mock_detect) -> None:
        mock_detect.return_value = ("horizontal", 1920, 1080, 0)

        project = self.service.create_project(
            CreateProjectInput(
                project_name="Renderable Project",
                source_video=UploadedAsset(
                    filename="clip.mp4",
                    content=b"video-bytes",
                    content_type="video/mp4",
                ),
            )
        )

        response = self.service.create_draft_render(project.project_id)
        status = self.service.get_job_status(response.job_id)
        detail = self.service.get_project(project.project_id)

        self.assertEqual(response.project_id, project.project_id)
        self.assertEqual(response.revision_id, project.active_revision_id)
        self.assertEqual(status.project_id, project.project_id)
        self.assertEqual(status.revision_id, project.active_revision_id)
        self.assertEqual(len(detail.render_jobs), 1)
        self.assertEqual(detail.render_jobs[0].job_id, response.job_id)
