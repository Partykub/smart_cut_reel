from __future__ import annotations

import unittest

from services.hyperframes_finishing.template_router import resolve_template_family


class TemplateRouterTests(unittest.TestCase):
    def test_auto_vertical_maps_to_vertical(self) -> None:
        self.assertEqual(
            resolve_template_family(requested="auto", detected="vertical"),
            "vertical",
        )

    def test_auto_horizontal_maps_to_horizontal(self) -> None:
        self.assertEqual(
            resolve_template_family(requested="auto", detected="horizontal"),
            "horizontal",
        )

    def test_manual_vertical_override_wins(self) -> None:
        self.assertEqual(
            resolve_template_family(requested="vertical", detected="horizontal"),
            "vertical",
        )

    def test_auto_manual_required_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_template_family(requested="auto", detected="manual_required")
