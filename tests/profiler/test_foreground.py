import numpy as np
from opticalflow3d_profiler.config import ForegroundSpec
from opticalflow3d_profiler.foreground import describe, threshold_frame


def test_threshold_uses_raw_values():
    intensity = np.array([[[99, 100, 101]]], np.uint16)
    assert threshold_frame(intensity, 100).tolist() == [[[False, False, True]]]


def test_foreground_is_a_threshold_or_none():
    assert describe(ForegroundSpec("threshold", 5.0))["threshold"] == 5.0
    assert describe(ForegroundSpec())["mode"] == "none"
