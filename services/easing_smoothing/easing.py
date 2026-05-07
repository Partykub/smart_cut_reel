"""Easing function library shared with the frontend TS port.

Phase 1 — P1-G01.

The function names registered in :data:`EASING_FUNCTIONS` match the contract
enum used in the ``easing_smoothing`` service config
(``linear | easeOutCubic | easeInOutCubic | easeInOutSine``). Snake-case Python
helpers exist for ergonomics, while the lookup map keeps the canonical names so
callers can pass the same string the job manifest carries.
"""

from __future__ import annotations

import math
from typing import Callable
from typing import Final
from typing import Literal


EasingName = Literal[
    "linear",
    "easeOutCubic",
    "easeInOutCubic",
    "easeInOutSine",
]


def _clamp01(value: float) -> float:
    if value != value:  # NaN check without importing math.isnan to keep it cheap
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def linear(t: float) -> float:
    return _clamp01(t)


def ease_out_cubic(t: float) -> float:
    x = _clamp01(t)
    inv = 1.0 - x
    return 1.0 - inv * inv * inv


def ease_in_out_cubic(t: float) -> float:
    x = _clamp01(t)
    if x < 0.5:
        return 4.0 * x * x * x
    inv = -2.0 * x + 2.0
    return 1.0 - (inv * inv * inv) / 2.0


def ease_in_out_sine(t: float) -> float:
    x = _clamp01(t)
    return -(math.cos(math.pi * x) - 1.0) / 2.0


EASING_FUNCTIONS: Final[dict[EasingName, Callable[[float], float]]] = {
    "linear": linear,
    "easeOutCubic": ease_out_cubic,
    "easeInOutCubic": ease_in_out_cubic,
    "easeInOutSine": ease_in_out_sine,
}


def interpolate(
    start: float,
    end: float,
    t: float,
    easing: EasingName = "easeInOutCubic",
) -> float:
    """Interpolate between ``start`` and ``end`` using one of the canonical easings.

    ``t`` is clamped to ``[0, 1]`` before easing, matching the TypeScript port
    used by the debug frontend.
    """

    if easing not in EASING_FUNCTIONS:
        raise ValueError(
            f"Unknown easing '{easing}'. Expected one of {sorted(EASING_FUNCTIONS)}."
        )
    eased = EASING_FUNCTIONS[easing](t)
    return start + (end - start) * eased
