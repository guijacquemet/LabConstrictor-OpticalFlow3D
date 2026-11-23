"""Global brightness change across an optical-flow time window (adapter).

Optical flow assumes that intensity patterns keep their brightness. A global brightness
change (illumination warm-up, focus settling, bleaching, expression changes) is partly read
as motion: on real organoid data a 2.8x brightening inflated XY speeds 1.2-2.3x and produced
an axial velocity of up to +1.3 slices/frame (docs/validation.md).

The measurement and the corrections are morphobricks-normalization's ``time_series``
(contract §3.7, plan N72; a dependency pinned to a commit). This module only applies them to
an optical-flow window with its **central frame as the reference**:

- :func:`brightness_change` measures the change for every output (always, as QC);
- :func:`equalise_window` (mean equalisation) and :func:`match_histograms_window` (histogram
  matching) are the opt-in corrections, applied only to the input of the optical flow and
  only when ``FlowParameters.brightness_equalisation`` asks for one; the factors are recorded.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from morphobricks_normalization import (
    TimeSeriesError,
    brightness_trend,
    equalise_brightness,
    frame_means,
    match_histograms,
)

from .results import distribution_identity


def implementation_identity() -> dict[str, str | None]:
    """Return the identity of the correction code (part of the flow identity when correcting).

    The morphobricks-normalization version and the SHA-256 of the code that changes the
    numbers: its ``time_series`` module and this adapter, which chooses the reference frame
    and applies the correction (re-validation M2). The commit is not part of it: a wheel
    install records none, and identical code must keep one identity; it is recorded in the
    run manifest's environment instead.
    """
    from morphobricks_normalization import time_series

    def sha256(module_file: str) -> str:
        return hashlib.sha256(Path(module_file).read_bytes()).hexdigest()

    return {
        "version": distribution_identity("morphobricks-normalization")["version"],
        "time_series_sha256": sha256(time_series.__file__),
        "adapter_sha256": sha256(__file__),
    }


WARNING_CHANGE_PER_FRAME = 0.02
"""Relative brightness change per frame above which a field of view gets a warning."""


def window_means(window: np.ndarray) -> np.ndarray:
    """Return the mean raw intensity of every frame of a TZYX window (float64)."""
    return frame_means(window)


def brightness_change(means: np.ndarray) -> float:
    """Return the relative brightness change per frame, against the central frame.

    The least-squares slope of the means against the frame index divided by the central
    frame's mean (0.05 = brightening by 5 % of the central brightness per frame); NaN when
    the central mean is not positive.
    """
    return brightness_trend(means, len(means) // 2)


def equalise_window(window: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Scale each frame so that its mean equals the central frame's mean.

    Parameters
    ----------
    window
        TZYX window in the file's pixel type (not modified).

    Returns
    -------
    tuple
        The scaled window as float64 and the factor applied to each frame.

    Raises
    ------
    ValueError
        When a frame has a non-positive mean (it cannot be scaled).
    """
    try:
        scaled, factors = equalise_brightness(window, window.shape[0] // 2)
    except TimeSeriesError as error:
        raise ValueError(str(error)) from error
    return scaled, [float(f) for f in factors]


def match_histograms_window(window: np.ndarray) -> np.ndarray:
    """Map each frame's intensity histogram onto the central frame's (float64 result).

    Fiji Bleach Correction's "Histogram Matching", per Z-stack over all voxels; monotonic but
    non-linear, so it is applied only to the optical-flow input.
    """
    return match_histograms(window, window.shape[0] // 2)
