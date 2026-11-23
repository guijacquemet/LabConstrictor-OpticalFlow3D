"""Nuclear foreground for feature measurement: a fixed raw-intensity threshold (pure).

The foreground restricts where features are measured; optical flow itself is always
calculated on the original image. The threshold is one raw-intensity value, the same for
every field of view; intensities are never normalised.
"""

from __future__ import annotations

import numpy as np

from .config import ForegroundSpec


def threshold_frame(intensity: np.ndarray, threshold: float) -> np.ndarray:
    """Return voxels whose raw intensity is strictly above ``threshold``.

    Parameters
    ----------
    intensity
        Source ZYX intensities (unchanged).
    threshold
        Raw-intensity threshold, the same for every field of view.

    Returns
    -------
    numpy.ndarray
        Boolean foreground.
    """
    return intensity > threshold


def describe(spec: ForegroundSpec) -> dict[str, object]:
    """Return a JSON-ready description of the foreground definition for provenance."""
    if spec.mode == "threshold":
        return {
            "mode": "threshold",
            "threshold": spec.threshold,
            "rule": "raw intensity > threshold at the optical-flow source time point",
        }
    return {
        "mode": "none",
        "warning": "Whole-image measurement: background and nuclear "
        "occupancy may influence the features.",
    }
