"""Nuclear foreground for feature measurement: mask file or fixed threshold (I/O).

The foreground restricts where features are measured; optical flow itself is always
calculated on the original image. A mask must match the source image's Z, Y, X (and T for
a time-dependent mask) exactly; a 2D mask is accepted only with the explicit, recorded
rule ``same_mask_for_every_z``. A threshold is one raw-intensity value, the same for every
field of view; intensities are never normalised.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile

from .config import ForegroundSpec
from .validation import InputError

MASK_AXES = ("TZYX", "ZYX", "YX")


@dataclass(frozen=True)
class MaskInfo:
    """What was checked about a mask file.

    Attributes
    ----------
    path
        Mask file.
    axes
        Confirmed axes.
    kind
        ``"binary"`` (two values) or ``"labels"`` (more values; nonzero is foreground).
    """

    path: Path
    axes: str
    kind: str


def check_mask(spec: ForegroundSpec, dims: dict[str, int]) -> MaskInfo:
    """Check that a mask file matches the source image coordinates.

    Parameters
    ----------
    spec
        Foreground settings with ``mode="mask"``.
    dims
        Source image sizes (``T``, ``Z``, ``Y``, ``X``).

    Returns
    -------
    MaskInfo
        Confirmed axes and value kind.

    Raises
    ------
    InputError
        For unconfirmed axes, a shape mismatch, a 2D mask without the plane rule, or
        a mask that is not integer or boolean.
    """
    if spec.mask_path is None or not Path(spec.mask_path).is_file():
        raise InputError("The foreground mask file was not found.")
    axes = spec.mask_axes.upper()
    if axes not in MASK_AXES:
        raise InputError(f"Confirm the mask axes as one of {', '.join(MASK_AXES)}.")
    if axes == "YX" and spec.mask_plane_rule != "same_mask_for_every_z":
        raise InputError(
            "A 2D mask is used for a 3D image only if you choose 'use the same "
            "mask for every Z slice'; it is never assumed."
        )
    with tifffile.TiffFile(spec.mask_path) as tif:
        series = tif.series[0]
        shape, dtype = tuple(series.shape), series.dtype
        sample = tif.asarray(key=0, series=0)
    expected = tuple(dims[a] for a in axes)
    if shape != expected:
        raise InputError(
            f"The mask has shape {shape} but the image needs {expected} for axes "
            f"{axes}; masks must use the source image coordinates."
        )
    if not (np.issubdtype(dtype, np.integer) or dtype == np.bool_):
        raise InputError(f"The mask has pixel type {dtype}; use an integer or binary mask.")
    kind = "binary" if np.unique(sample).size <= 2 else "labels"
    return MaskInfo(Path(spec.mask_path), axes, kind)


def mask_frame(info: MaskInfo, source_frame: int, dims: dict[str, int]) -> np.ndarray:
    """Return the boolean ZYX foreground of one source time point from a mask file.

    Parameters
    ----------
    info
        Checked mask.
    source_frame
        Source time point the optical-flow output belongs to.
    dims
        Source image sizes.

    Returns
    -------
    numpy.ndarray
        Boolean ZYX array (nonzero mask values are foreground).
    """
    n_z = dims["Z"]
    with tifffile.TiffFile(info.path) as tif:
        if info.axes == "TZYX":
            keys = list(range(source_frame * n_z, (source_frame + 1) * n_z))
            data = tif.asarray(key=keys, series=0).reshape(n_z, dims["Y"], dims["X"])
        else:
            data = tif.asarray(series=0)
    data = data != 0
    if info.axes == "YX":
        data = np.broadcast_to(data, (n_z, dims["Y"], dims["X"]))
    return np.ascontiguousarray(data)


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


def describe(spec: ForegroundSpec, info: MaskInfo | None) -> dict[str, object]:
    """Return a JSON-ready description of the foreground definition for provenance."""
    if spec.mode == "none":
        return {
            "mode": "none",
            "warning": "Whole-image measurement: background and nuclear "
            "occupancy may influence the features.",
        }
    if spec.mode == "threshold":
        return {
            "mode": "threshold",
            "threshold": spec.threshold,
            "rule": "raw intensity > threshold at the optical-flow source time point",
        }
    return {
        "mode": "mask",
        "path": Path(spec.mask_path).as_posix(),
        "axes": info.axes if info else spec.mask_axes,
        "kind": info.kind if info else "unchecked",
        "plane_rule": spec.mask_plane_rule or "none",
    }
