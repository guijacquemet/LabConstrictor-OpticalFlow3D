"""Typed settings of one profiler run (pure).

Every setting that changes a number is a field of a frozen dataclass here, so that a run
manifest can record it with :func:`to_record` and a cached result can be compared with it.
Nothing in this module reads files or guesses values: missing calibration stays ``None``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

SpeedMode = Literal["xy", "xyz"]
ReliabilityMode = Literal["absolute", "percentile", "none"]
ForegroundMode = Literal["mask", "threshold", "none"]
OutputDtype = Literal["float64", "float32"]
MaskPlaneRule = Literal["", "same_mask_for_every_z"]

CANONICAL_AXES = "TZYX"
"""Axis order the upstream ``calc_flow3D`` expects (time, z, y, x)."""


@dataclass(frozen=True)
class Calibration:
    """Physical calibration; ``None`` means unknown, never a default.

    Attributes
    ----------
    pixel_size_x, pixel_size_y, pixel_size_z
        Voxel size in micrometres along each axis.
    frame_interval
        Time between consecutive frames in minutes.
    source
        Where the values come from, for example ``"user"`` or ``"header (OME)"``.
    """

    pixel_size_x: float | None = None
    pixel_size_y: float | None = None
    pixel_size_z: float | None = None
    frame_interval: float | None = None
    source: str = "none"

    @property
    def lateral_known(self) -> bool:
        """Return True when X, Y and the frame interval are known."""
        values = (self.pixel_size_x, self.pixel_size_y, self.frame_interval)
        return all(v is not None for v in values)

    @property
    def complete(self) -> bool:
        """Return True when X, Y, Z and the frame interval are all known."""
        return self.lateral_known and self.pixel_size_z is not None


@dataclass(frozen=True)
class FlowParameters:
    """Parameters passed to the upstream ``calc_flow3D`` (upstream defaults).

    Attributes
    ----------
    xyz_sig
        Spatial smoothing sigma in voxels (upstream ``xyzSig``).
    t_sig
        Temporal smoothing sigma in frames (upstream ``tSig``).
    w_sig
        Lucas-Kanade neighbourhood sigma in voxels (upstream ``wSig``).
    output_dtype
        Precision of the saved velocity files. ``float64`` is what upstream returns and
        writes; ``float32`` halves the disk use and is recorded as a deliberate choice.
    """

    xyz_sig: float = 3.0
    t_sig: float = 1.0
    w_sig: float = 4.0
    output_dtype: OutputDtype = "float64"

    @property
    def window_length(self) -> int:
        """Return the number of frames in one upstream time window.

        Upstream ``process_flow`` uses ``6*tSig + 1`` frames, made odd; the central frame
        is the analysed one.
        """
        length = math.ceil(6 * self.t_sig) + 1
        return length if length % 2 else length + 1

    @property
    def half_window(self) -> int:
        """Return the number of frames lost at each end of the movie."""
        return self.window_length // 2


@dataclass(frozen=True)
class ImageSpec:
    """One field of view: a TIFF file and its confirmed interpretation.

    Attributes
    ----------
    path
        The TIFF or OME-TIFF file. It is only ever read.
    axes
        Confirmed axis letters of the file's first series, in file order, using only
        ``T``, ``Z``, ``C``, ``Y`` and ``X`` (for example ``"TZCYX"``).
    channel
        Index along ``C`` to analyse; required when the file has a ``C`` axis.
    calibration
        Physical calibration (may be incomplete).
    """

    path: Path
    axes: str
    channel: int | None = None
    calibration: Calibration = field(default_factory=Calibration)


@dataclass(frozen=True)
class ForegroundSpec:
    """Where features are measured (separate from reliability filtering).

    Attributes
    ----------
    mode
        ``"mask"`` (binary mask file), ``"threshold"`` (raw-intensity threshold on the
        analysed channel at the flow time point) or ``"none"`` (whole image, exploratory).
    threshold
        Raw-intensity threshold; voxels with intensity strictly above it are foreground.
        The same value is used for every field of view.
    mask_path
        Binary mask TIFF (nonzero = foreground).
    mask_axes
        Confirmed axes of the mask file: ``"TZYX"``, ``"ZYX"`` or ``"YX"``.
    mask_plane_rule
        Required for a ``"YX"`` mask: ``"same_mask_for_every_z"`` records that the 2D mask
        is applied to every Z slice. Without it a 2D mask is refused.
    """

    mode: ForegroundMode = "none"
    threshold: float | None = None
    mask_path: Path | None = None
    mask_axes: str = ""
    mask_plane_rule: MaskPlaneRule = ""


@dataclass(frozen=True)
class FeatureSettings:
    """Settings of the feature extractor.

    Attributes
    ----------
    speed_mode
        ``"xy"`` measures speed from (vx, vy); ``"xyz"`` also uses vz. XY is the default
        because the axial validation is experimental (see README).
    reliability_mode
        ``"absolute"``: keep voxels with reliability >= ``reliability_value`` (one value
        for every field of view). ``"percentile"``: per-frame percentile of the
        foreground reliability (upstream example behaviour; the threshold differs between
        frames and is recorded). ``"none"``: no reliability filtering.
    reliability_value
        Threshold (absolute mode) or percentile 0-100 (percentile mode).
    region_size_px
        Side, in XY pixels, of the fixed square regions of the spatial features.
    local_window_px
        Side, in XY pixels, of the window of the local directional coherence.
    min_region_voxels
        A region with fewer analysed voxels has no regional value.
    motion_threshold
        Speed (in feature units) above which a region counts as moving; ``None`` leaves
        the fraction of moving regions undefined.
    angle_bins
        Number of bins of the XY angular entropy.
    aligned_angle_deg
        Vectors within this angle of the dominant direction count as aligned.
    """

    speed_mode: SpeedMode = "xy"
    reliability_mode: ReliabilityMode = "absolute"
    reliability_value: float | None = None
    region_size_px: int = 128
    local_window_px: int = 15
    min_region_voxels: int = 100
    motion_threshold: float | None = None
    angle_bins: int = 36
    aligned_angle_deg: float = 45.0


def to_record(value: object) -> object:
    """Return a JSON-ready copy of a settings dataclass (paths as POSIX strings).

    Parameters
    ----------
    value
        A dataclass instance, mapping, sequence, path or plain value.

    Returns
    -------
    object
        Nested dictionaries, lists and plain values.
    """
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_record(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_record(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_record(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value
