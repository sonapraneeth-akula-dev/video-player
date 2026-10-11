"""Admission checks for synchronized playback."""

import math


def fps_match(a: float | None, b: float | None) -> bool:
    if any(
        isinstance(fps, bool) or not isinstance(fps, (int, float))
        or not math.isfinite(fps) or fps <= 0
        for fps in (a, b)
    ):
        raise ValueError("Frame rate unknown")
    if abs(a - b) >= 0.001:
        raise ValueError(f"Frame rate mismatch: {a:g} fps vs {b:g} fps")
    return True
