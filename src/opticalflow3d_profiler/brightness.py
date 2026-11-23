"""Global brightness change across an optical-flow time window (pure).

Optical flow assumes that intensity patterns keep their brightness. A global brightness
change (illumination warm-up, focus settling, bleaching, expression changes) is partly read
as motion: on real organoid data a 2.8x brightening inflated XY speeds 1.2-2.3x and produced
an axial velocity of up to +1.3 slices/frame (docs/validation.md).

:func:`brightness_change` measures the change for every output (always, as QC).
:func:`equalise_window` and :func:`match_histograms_window` are the opt-in corrections. The
first multiplies each frame of the window so
that its mean equals the central frame's mean. It is applied only to the input of the
optical flow, only when ``FlowParameters.brightness_equalisation`` asks for it, and its
factors are recorded. A constant camera offset is scaled too, so the correction is
approximate when the background offset is a large part of the mean.
"""

from __future__ import annotations

import numpy as np

WARNING_CHANGE_PER_FRAME = 0.02
"""Relative brightness change per frame above which a field of view gets a warning."""


def window_means(window: np.ndarray) -> np.ndarray:
    """Return the mean raw intensity of every frame of a TZYX window."""
    return window.reshape(window.shape[0], -1).mean(axis=1, dtype=np.float64)


def brightness_change(means: np.ndarray) -> float:
    """Return the relative brightness change per frame across a window.

    Parameters
    ----------
    means
        Mean intensity of each frame of the window, in time order.

    Returns
    -------
    float
        Least-squares slope of the means against frame index, divided by the mean of the
        central frame (for example 0.05 = brightening by 5 % of the central brightness per
        frame). NaN when the central mean is not positive.
    """
    centre = means[len(means) // 2]
    if not centre > 0:
        return float("nan")
    slope = np.polyfit(np.arange(len(means), dtype=np.float64), means, 1)[0]
    return float(slope / centre)


def equalise_window(window: np.ndarray, means: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Scale each frame so that its mean equals the central frame's mean.

    Parameters
    ----------
    window
        TZYX window in the file's pixel type (not modified).
    means
        :func:`window_means` of the window.

    Returns
    -------
    tuple
        The scaled window as float64 (upstream computes in float64 anyway) and the factor
        applied to each frame.

    Raises
    ------
    ValueError
        When a frame has a non-positive mean (it cannot be scaled).
    """
    if np.any(means <= 0):
        raise ValueError("A frame has a non-positive mean intensity; it cannot be equalised.")
    factors = means[len(means) // 2] / means
    scaled = window.astype(np.float64) * factors[:, None, None, None]
    return scaled, [float(f) for f in factors]


def match_histograms_window(window: np.ndarray) -> np.ndarray:
    """Map each frame's intensity histogram onto the central frame's histogram.

    The mapping is the classical CDF matching used by Fiji's Bleach Correction
    ("Histogram Matching"): ``p' = CDF_ref^-1(CDF_frame(p))``, computed per Z-stack over all
    voxels, with linear interpolation between reference quantiles. It is monotonic but
    non-linear: unlike :func:`equalise_window` it changes relative intensities, which the
    Fiji author recommends for segmentation rather than intensity quantification. Here it is
    applied only to the optical-flow input.

    Parameters
    ----------
    window
        TZYX window (not modified).

    Returns
    -------
    numpy.ndarray
        The matched window as float64; the central frame is unchanged.
    """
    centre = window.shape[0] // 2
    ref_values, ref_counts = np.unique(window[centre], return_counts=True)
    ref_cdf = np.cumsum(ref_counts, dtype=np.float64) / window[centre].size
    out = np.empty(window.shape, dtype=np.float64)
    for t in range(window.shape[0]):
        if t == centre:
            out[t] = window[t]
            continue
        _, inverse, counts = np.unique(window[t], return_inverse=True, return_counts=True)
        cdf = np.cumsum(counts, dtype=np.float64) / window[t].size
        out[t] = np.interp(cdf, ref_cdf, ref_values.astype(np.float64))[inverse].reshape(
            window[t].shape
        )
    return out
