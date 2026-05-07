"""Unit tests for the Phase 1 easing function library (P1-G01)."""

from __future__ import annotations

import math
import unittest

from services.easing_smoothing.easing import EASING_FUNCTIONS
from services.easing_smoothing.easing import EasingName
from services.easing_smoothing.easing import ease_in_out_cubic
from services.easing_smoothing.easing import ease_in_out_sine
from services.easing_smoothing.easing import ease_out_cubic
from services.easing_smoothing.easing import interpolate
from services.easing_smoothing.easing import linear

NAMES: tuple[EasingName, ...] = (
    "linear",
    "easeOutCubic",
    "easeInOutCubic",
    "easeInOutSine",
)


class EasingBoundaryTests(unittest.TestCase):
    def test_boundary_zero_and_one(self) -> None:
        for name in NAMES:
            with self.subTest(name=name):
                fn = EASING_FUNCTIONS[name]
                self.assertAlmostEqual(fn(0.0), 0.0, places=10)
                self.assertAlmostEqual(fn(1.0), 1.0, places=10)

    def test_clamps_below_zero(self) -> None:
        for name in NAMES:
            with self.subTest(name=name):
                fn = EASING_FUNCTIONS[name]
                self.assertAlmostEqual(fn(-2.0), 0.0, places=10)

    def test_clamps_above_one(self) -> None:
        for name in NAMES:
            with self.subTest(name=name):
                fn = EASING_FUNCTIONS[name]
                self.assertAlmostEqual(fn(5.0), 1.0, places=10)

    def test_handles_nan_as_zero(self) -> None:
        for name in NAMES:
            with self.subTest(name=name):
                fn = EASING_FUNCTIONS[name]
                self.assertAlmostEqual(fn(float("nan")), 0.0, places=10)


class EasingMonotonicTests(unittest.TestCase):
    def test_monotonic_non_decreasing(self) -> None:
        for name in NAMES:
            with self.subTest(name=name):
                fn = EASING_FUNCTIONS[name]
                last = -math.inf
                for i in range(21):
                    value = fn(i / 20.0)
                    self.assertGreaterEqual(value + 1e-9, last)
                    last = value


class EasingShapeTests(unittest.TestCase):
    def test_linear_is_identity(self) -> None:
        for i in range(11):
            t = i / 10.0
            self.assertAlmostEqual(linear(t), t, places=10)

    def test_symmetry_at_midpoint(self) -> None:
        self.assertAlmostEqual(ease_in_out_cubic(0.5), 0.5, places=10)
        self.assertAlmostEqual(ease_in_out_sine(0.5), 0.5, places=10)

    def test_ease_out_cubic_decelerates(self) -> None:
        slope_first_half = (ease_out_cubic(0.5) - ease_out_cubic(0.0)) / 0.5
        slope_second_half = (ease_out_cubic(1.0) - ease_out_cubic(0.5)) / 0.5
        self.assertGreater(slope_first_half, slope_second_half)


class InterpolateTests(unittest.TestCase):
    def test_start_and_end(self) -> None:
        self.assertAlmostEqual(interpolate(100.0, 500.0, 0.0), 100.0, places=10)
        self.assertAlmostEqual(interpolate(100.0, 500.0, 1.0), 500.0, places=10)

    def test_linear_easing_midpoint(self) -> None:
        self.assertAlmostEqual(
            interpolate(0.0, 100.0, 0.5, easing="linear"),
            50.0,
            places=10,
        )

    def test_clamps_t_outside_range(self) -> None:
        self.assertAlmostEqual(
            interpolate(0.0, 100.0, -1.0, easing="linear"),
            0.0,
            places=10,
        )
        self.assertAlmostEqual(
            interpolate(0.0, 100.0, 5.0, easing="linear"),
            100.0,
            places=10,
        )

    def test_unknown_easing_raises(self) -> None:
        with self.assertRaises(ValueError):
            interpolate(0.0, 1.0, 0.5, easing="bouncy")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
