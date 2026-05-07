"""Easing/Smoothing service package.

Phase 1 currently provides the easing function library (P1-G01) only.
Smoothing/limit logic (P1-G02/P1-G03) will be added on top of these primitives.
"""

from .easing import EASING_FUNCTIONS
from .easing import EasingName
from .easing import ease_in_out_cubic
from .easing import ease_in_out_sine
from .easing import ease_out_cubic
from .easing import interpolate
from .easing import linear

__all__ = [
    "EASING_FUNCTIONS",
    "EasingName",
    "ease_in_out_cubic",
    "ease_in_out_sine",
    "ease_out_cubic",
    "interpolate",
    "linear",
]
