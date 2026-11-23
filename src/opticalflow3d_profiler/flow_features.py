"""Motion features of one optical-flow output (pure).

Every feature is computed over the *analysed voxels*: foreground (if defined) AND
reliable (per :class:`~opticalflow3d_profiler.config.FeatureSettings`) AND finite in all
three velocity components. Velocities are never modified: zeros stay zeros, non-finite
values are excluded and counted, nothing is replaced by zero. A feature that cannot be
computed is ``NaN`` and its reason is returned alongside.
"""

from __future__ import annotations

import functools

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .config import Calibration, FeatureSettings

QUANTILES = (10, 25, 75, 90, 95)
NO_AXIAL = "per-slice 2D optical flow has no axial component"
AXIAL_COLUMNS = ("vz_mean", "vz_sd", "vz_abs_mean", "axial_lateral_ratio", "coherence_3d_global")


@dataclass(frozen=True)
class VelocityScale:
    """Factors from upstream units to feature units.

    Attributes
    ----------
    x, y, z
        Multipliers of vx, vy, vz.
    lateral_unit, axial_unit
        Units after scaling (``"µm/min"``, ``"px/frame"`` or ``"slice/frame"``).
    """

    x: float
    y: float
    z: float
    lateral_unit: str
    axial_unit: str

    @property
    def consistent(self) -> bool:
        """Return True when lateral and axial velocities share one physical unit.

        Pixels and slices are different lengths, so uncalibrated velocities never share a
        unit: 3D speed, 3D coherence and the axial/lateral ratio need X, Y, Z and time.
        """
        return self.lateral_unit == self.axial_unit == "µm/min"


def velocity_scale(calibration: Calibration) -> VelocityScale:
    """Return per-axis velocity factors, using X, Y and Z calibration independently.

    Parameters
    ----------
    calibration
        Physical calibration (may be incomplete).

    Returns
    -------
    VelocityScale
        µm/min where the calibration allows it, upstream units otherwise. Physical
        values carry the optical-flow gain bias (docs/validation.md); scaling converts
        units only, it does not correct the isotropic voxel smoothing of upstream.
    """
    dt = calibration.frame_interval
    if calibration.lateral_known:
        x, y, lateral = calibration.pixel_size_x / dt, calibration.pixel_size_y / dt, "µm/min"
    else:
        x, y, lateral = 1.0, 1.0, "px/frame"
    if dt is not None and calibration.pixel_size_z is not None:
        z, axial = calibration.pixel_size_z / dt, "µm/min"
    else:
        z, axial = 1.0, "slice/frame"
    return VelocityScale(x, y, z, lateral, axial)


@dataclass
class FeatureRow:
    """Feature values of one frame and the reasons for undefined ones."""

    values: dict[str, float]
    undefined: dict[str, str]

    def put(self, name: str, value: float | None, reason: str = "") -> None:
        """Store a value, or NaN with its reason when ``value`` is None or not finite."""
        if value is None or not np.isfinite(value):
            self.values[name] = float("nan")
            self.undefined[name] = reason or "not finite"
        else:
            self.values[name] = float(value)


def reliability_mask(
    rel: np.ndarray, within: np.ndarray, settings: FeatureSettings
) -> tuple[np.ndarray, float | None]:
    """Return the reliable voxels and the threshold actually used.

    Parameters
    ----------
    rel
        Reliability volume.
    within
        Voxels considered (foreground and finite).
    settings
        Reliability mode and value.

    Returns
    -------
    tuple
        Boolean mask and the effective threshold (``None`` for mode ``"none"``).

    Raises
    ------
    ValueError
        When the mode needs a value that is missing.
    """
    if settings.reliability_mode == "none":
        return np.ones(rel.shape, dtype=bool), None
    usable = np.isfinite(rel)
    if settings.reliability_value is None:
        raise ValueError(f"A reliability value is required for mode '{settings.reliability_mode}'.")
    if settings.reliability_mode == "absolute":
        threshold = float(settings.reliability_value)
    else:
        values = rel[within & usable]  # non-finite reliability never sets the threshold
        if values.size == 0:
            return np.zeros(rel.shape, dtype=bool), None
        threshold = float(np.percentile(values, settings.reliability_value))
    return usable & (rel >= threshold), threshold


def _put_stats(row: FeatureRow, prefix: str, values: np.ndarray) -> None:
    """Store the magnitude statistics of ``values`` under ``prefix``."""
    names = ["mean", "median", "sd", "cv", "rms", *[f"p{q}" for q in QUANTILES], "max"]
    if values.size == 0:
        for name in names:
            row.put(f"{prefix}_{name}", None, "no analysed voxels")
        return
    mean, sd = float(np.mean(values)), float(np.std(values))
    row.put(f"{prefix}_mean", mean)
    row.put(f"{prefix}_median", float(np.median(values)))
    row.put(f"{prefix}_sd", sd)
    row.put(f"{prefix}_cv", sd / mean if mean > 0 else None, "mean speed is zero")
    row.put(f"{prefix}_rms", float(np.sqrt(np.mean(values**2))))
    for q, value in zip(QUANTILES, np.percentile(values, QUANTILES), strict=True):
        row.put(f"{prefix}_p{q}", float(value))
    row.put(f"{prefix}_max", float(np.max(values)))


def _put_components(
    row: FeatureRow, v: dict[str, np.ndarray], scale: VelocityScale, lateral_column: bool
) -> None:
    """Store the velocity-component features (family B)."""
    empty = v["x"].size == 0
    for axis in "xyz":
        values = v[axis]
        row.put(f"v{axis}_mean", None if empty else float(np.mean(values)), "no analysed voxels")
        row.put(f"v{axis}_sd", None if empty else float(np.std(values)), "no analysed voxels")
        row.put(
            f"v{axis}_abs_mean",
            None if empty else float(np.mean(np.abs(values))),
            "no analysed voxels",
        )
    speed_xy = np.hypot(v["x"], v["y"])
    if lateral_column:  # in XY mode this is speed_xy_mean already
        row.put(
            "lateral_speed_mean", None if empty else float(np.mean(speed_xy)), "no analysed voxels"
        )
    if empty:
        row.put("axial_lateral_ratio", None, "no analysed voxels")
    elif not scale.consistent:
        row.put(
            "axial_lateral_ratio",
            None,
            "lateral and axial velocities are not in one physical unit (complete the calibration)",
        )
    else:
        lateral = float(np.mean(speed_xy))
        row.put(
            "axial_lateral_ratio",
            float(np.mean(np.abs(v["z"]))) / lateral if lateral > 0 else None,
            "lateral speed is zero",
        )


def _coherence(components: list[np.ndarray]) -> float | None:
    """Return |sum of vectors| / sum of |vectors|, or None when all vectors are zero."""
    total = float(np.sum(np.sqrt(sum(c**2 for c in components))))
    if total == 0:
        return None
    return float(np.sqrt(sum(float(np.sum(c)) ** 2 for c in components))) / total


def _put_angles(row: FeatureRow, vx: np.ndarray, vy: np.ndarray, settings: FeatureSettings) -> None:
    """Store the angular features of vectors with a defined direction.

    A direction is defined for vectors whose XY speed exceeds ``min_direction_speed``
    (zero vectors never have one); with fewer than ``min_direction_vectors`` such vectors
    the angular features are undefined. Speeds are not changed by this selection.
    """
    names = (
        "xy_angular_entropy",
        "xy_angular_dispersion",
        "xy_aligned_fraction",
        "xy_dominant_direction_deg",
    )
    directed = np.hypot(vx, vy) > max(settings.min_direction_speed, 0.0)
    if int(directed.sum()) < max(settings.min_direction_vectors, 1):
        reason = (
            f"fewer than {settings.min_direction_vectors} analysed vectors with XY speed "
            f"> {settings.min_direction_speed:g}"
        )
        for name in names:
            row.put(name, None, reason)
        return
    theta = np.arctan2(vy[directed], vx[directed])
    mean_cos, mean_sin = float(np.mean(np.cos(theta))), float(np.mean(np.sin(theta)))
    resultant = float(np.hypot(mean_cos, mean_sin))
    dominant = float(np.arctan2(mean_sin, mean_cos)) if resultant >= 1e-12 else None
    row.put("xy_angular_entropy", angular_entropy(theta, settings.angle_bins))
    row.put("xy_angular_dispersion", 1.0 - resultant)
    if dominant is None:
        row.put("xy_aligned_fraction", None, "no dominant direction (mean resultant is zero)")
        row.put("xy_dominant_direction_deg", None, "no dominant direction")
        return
    aligned = np.cos(theta - dominant) >= np.cos(np.deg2rad(settings.aligned_angle_deg))
    row.put("xy_aligned_fraction", float(np.mean(aligned)))
    row.put("xy_dominant_direction_deg", float(np.rad2deg(dominant)))


ENTROPY_GRID = 2**16
"""Points of the circle the direction density is evaluated on (spacing about 0.0055°)."""


def angular_entropy(theta: np.ndarray, resolution_bins: int) -> float:
    """Return the normalised entropy of a smooth density of directions (0 to 1).

    The density is a wrapped-normal kernel density of the directions with a standard
    deviation of one ``360° / resolution_bins``: a mixture of kernels centred on the
    directions. Its differential entropy ``H = -∫ p log p dθ`` lies between the entropy of
    one kernel ``H_k`` (every vector in one direction) and ``log 2π`` (uniform), since
    entropy is concave, and is reported as ``(H - H_k) / (log 2π - H_k)``. Rotating every
    vector shifts the density without changing ``H``, and moving one vector a little moves
    the value a little: no bins, edges or anchor (re-validation R1). Computed on
    :data:`ENTROPY_GRID` points: the directions are spread linearly between their two
    nearest points, the kernel is applied by FFT, and ``H`` is the trapezoid sum, whose
    error for a smooth periodic density is far below the grid spacing.
    """
    h = _density_entropy(_grid_mass(theta), resolution_bins)
    h_kernel = _kernel_entropy(resolution_bins)
    top = np.log(2 * np.pi)
    return float(np.clip((h - h_kernel) / (top - h_kernel), 0.0, 1.0))


@functools.lru_cache(maxsize=8)
def _kernel_entropy(resolution_bins: int) -> float:
    """Return the entropy of one kernel: every direction at one grid point."""
    return _density_entropy(_grid_mass(np.zeros(1)), resolution_bins)


def _grid_mass(theta: np.ndarray) -> np.ndarray:
    """Return the share of directions at each grid point (linear spreading, sum 1)."""
    position = np.mod(np.asarray(theta, dtype=np.float64), 2 * np.pi) * (
        ENTROPY_GRID / (2 * np.pi)
    )
    low = np.floor(position)
    upper = position - low
    low = low.astype(np.int64) % ENTROPY_GRID
    mass = np.bincount(low, weights=1.0 - upper, minlength=ENTROPY_GRID)
    mass += np.bincount((low + 1) % ENTROPY_GRID, weights=upper, minlength=ENTROPY_GRID)
    return mass / mass.sum()


def _density_entropy(mass: np.ndarray, resolution_bins: int) -> float:
    """Return ``-∫ p log p dθ`` of the wrapped-normal kernel density of grid masses."""
    sigma = 2 * np.pi / resolution_bins
    order = np.arange(ENTROPY_GRID // 2 + 1)
    spectrum = np.fft.rfft(mass) * np.exp(-0.5 * (order * sigma) ** 2)
    step = 2 * np.pi / ENTROPY_GRID
    density = np.fft.irfft(spectrum, ENTROPY_GRID) / step
    positive = density[density > 0]
    return float(-np.sum(positive * np.log(positive)) * step)


def local_coherence_map(
    vx: np.ndarray, vy: np.ndarray, mask: np.ndarray, window: int, min_vectors: int = 1
) -> np.ndarray:
    """Return the local XY coherence at every voxel (NaN where undefined).

    The coherence is |sum of analysed vectors| / sum of their lengths inside a
    ``window`` x ``window`` XY neighbourhood of the same Z slice.

    Parameters
    ----------
    vx, vy
        Scaled lateral velocities (ZYX).
    mask
        Analysed voxels.
    window
        Neighbourhood side in pixels.
    min_vectors
        Minimum number of analysed nonzero vectors in the window; sparser windows (for
        example at borders or thin foreground) are undefined, because one or two vectors
        always look coherent.

    Returns
    -------
    numpy.ndarray
        Coherence in [0, 1], NaN outside the mask or where the window has too few vectors.
    """
    size = (1, window, window)
    sum_x = ndimage.uniform_filter(np.where(mask, vx, 0.0), size, mode="constant")
    sum_y = ndimage.uniform_filter(np.where(mask, vy, 0.0), size, mode="constant")
    sum_len = ndimage.uniform_filter(np.where(mask, np.hypot(vx, vy), 0.0), size, mode="constant")
    moving = (mask & (np.hypot(vx, vy) > 0)).astype(np.float64)
    support = ndimage.uniform_filter(moving, size, mode="constant") * window * window
    out = np.full(vx.shape, np.nan)
    ok = mask & (sum_len > 0) & (support >= max(min_vectors, 1) - 0.5)
    out[ok] = np.hypot(sum_x[ok], sum_y[ok]) / sum_len[ok]
    return out


def _region_values(
    speed: np.ndarray, vx: np.ndarray, vy: np.ndarray, mask: np.ndarray, settings: FeatureSettings
) -> tuple[list[float], list[float], int]:
    """Return mean speed and coherence of every full square XY region with enough voxels."""
    size = settings.region_size_px
    n_y, n_x = mask.shape[1] // size, mask.shape[2] // size
    speeds, coherences = [], []
    for iy in range(n_y):
        for ix in range(n_x):
            block = (
                slice(None),
                slice(iy * size, (iy + 1) * size),
                slice(ix * size, (ix + 1) * size),
            )
            inside = mask[block]
            if int(inside.sum()) < settings.min_region_voxels:
                continue
            speeds.append(float(np.mean(speed[block][inside])))
            coherence = _coherence([vx[block][inside], vy[block][inside]])
            if coherence is not None:
                coherences.append(coherence)
    return speeds, coherences, n_y * n_x


def _put_regions(
    row: FeatureRow,
    speed: np.ndarray,
    vx: np.ndarray,
    vy: np.ndarray,
    mask: np.ndarray,
    settings: FeatureSettings,
    speed_reason: str = "",
) -> None:
    """Store the spatial-heterogeneity features (family D).

    ``speed_reason`` (non-empty when the speed itself is undefined, for example 3D speed in
    mixed units) makes every speed-dependent regional feature undefined with that reason.
    """
    speeds, coherences, n_regions = _region_values(speed, vx, vy, mask, settings)
    size = settings.region_size_px
    row.put("qc_n_regions", float(n_regions))
    row.put("qc_n_regions_analysed", float(len(speeds)))
    row.put("qc_region_grid_coverage", n_regions * size * size / (mask.shape[1] * mask.shape[2]))
    few = f"fewer than 2 regions with >= {settings.min_region_voxels} analysed voxels"
    row.put(
        "regional_coherence_sd", float(np.std(coherences)) if len(coherences) >= 2 else None, few
    )
    if speed_reason:
        for name in ("regional_speed_cv", "regional_speed_spread", "regional_moving_fraction"):
            row.put(name, None, speed_reason)
        return
    s = np.asarray(speeds)
    s = s[np.isfinite(s)]
    mean = float(np.mean(s)) if s.size else 0.0
    row.put(
        "regional_speed_cv",
        float(np.std(s)) / mean if s.size >= 2 and mean > 0 else None,
        few if s.size < 2 else "mean regional speed is zero",
    )
    median = float(np.median(s)) if s.size else 0.0
    spread = float(np.percentile(s, 90) - np.percentile(s, 10)) if s.size >= 2 else 0.0
    row.put(
        "regional_speed_spread",
        spread / median if s.size >= 2 and median > 0 else None,
        few if s.size < 2 else "median regional speed is zero",
    )
    if settings.motion_threshold is None:
        row.put("regional_moving_fraction", None, "no motion threshold was set")
    else:
        row.put(
            "regional_moving_fraction",
            float(np.mean(s > settings.motion_threshold)) if s.size else None,
            "no region has enough analysed voxels",
        )


def _put_quality(
    row: FeatureRow,
    rel: np.ndarray,
    considered: np.ndarray,
    finite: np.ndarray,
    analysed: np.ndarray,
    foreground: np.ndarray | None,
) -> None:
    """Store reliability and coverage QC (family E)."""
    within = considered & finite
    rel_ok = np.isfinite(rel)
    values = rel[within & rel_ok]
    row.put(
        "qc_invalid_reliability_fraction",
        int((within & ~rel_ok).sum()) / int(within.sum()) if within.any() else None,
        "no finite foreground voxel",
    )
    row.put(
        "qc_reliability_median",
        float(np.median(values)) if values.size else None,
        "no foreground voxel",
    )
    for q in (10, 90):
        row.put(
            f"qc_reliability_p{q}",
            float(np.percentile(values, q)) if values.size else None,
            "no foreground voxel",
        )
    n_considered = int(considered.sum())
    row.put(
        "qc_reliable_fraction",
        int(analysed.sum()) / int(within.sum()) if within.any() else None,
        "no finite foreground voxel",
    )
    row.put(
        "qc_invalid_velocity_fraction",
        int((considered & ~finite).sum()) / n_considered if n_considered else None,
        "no foreground voxel",
    )
    row.put(
        "qc_foreground_fraction",
        None if foreground is None else float(foreground.mean()),
        "no foreground was defined",
    )
    row.put("qc_n_analysed_voxels", float(analysed.sum()))


def _put_foreground_shape(
    row: FeatureRow,
    foreground: np.ndarray | None,
    intensity: np.ndarray | None,
    with_intensity: bool,
) -> None:
    """Store foreground-object size QC and, if asked, intensity QC (confounders of the gain)."""
    if not with_intensity:
        pass
    elif intensity is None:
        row.put("qc_foreground_intensity_mean", None, "source intensities were not supplied")
    elif foreground is None:
        row.put("qc_foreground_intensity_mean", None, "no foreground was defined")
    else:
        row.put(
            "qc_foreground_intensity_mean",
            float(np.mean(intensity[foreground])) if foreground.any() else None,
            "empty foreground",
        )
    names = ("qc_object_mean_voxels", "qc_object_mean_z_extent", "qc_n_objects")
    if foreground is None or not foreground.any():
        for name in names:
            row.put(
                name,
                None,
                "no foreground was defined" if foreground is None else "empty foreground",
            )
        return
    labels, n = ndimage.label(foreground)
    sizes = np.bincount(labels.ravel())[1:]
    extents = [s[0].stop - s[0].start for s in ndimage.find_objects(labels)]
    row.put("qc_object_mean_voxels", float(np.mean(sizes)))
    row.put("qc_object_mean_z_extent", float(np.mean(extents)))
    row.put("qc_n_objects", float(n))


def frame_features(
    flow: dict[str, np.ndarray],
    foreground: np.ndarray | None,
    intensity: np.ndarray | None,
    calibration: Calibration,
    settings: FeatureSettings,
) -> FeatureRow:
    """Compute every feature of one optical-flow output.

    Parameters
    ----------
    flow
        ``vx``, ``vy``, ``vz`` (upstream units) and ``rel`` volumes (ZYX).
    foreground
        Boolean ZYX foreground, or ``None`` for whole-image measurement.
    intensity
        Source intensities of the analysed time point (ZYX), for intensity QC only.
    calibration
        Calibration used to convert units.
    settings
        Feature settings.

    Returns
    -------
    FeatureRow
        Values (NaN when undefined) and the reason of every undefined value.
    """
    row = FeatureRow({}, {})
    scale = velocity_scale(calibration)
    vx, vy = flow["vx"] * scale.x, flow["vy"] * scale.y
    has_vz = "vz" in flow  # per-slice 2D flow has no axial component
    vz = flow["vz"] * scale.z if has_vz else np.full(vx.shape, np.nan)
    finite = np.isfinite(vx) & np.isfinite(vy) & (np.isfinite(vz) if has_vz else True)
    considered = foreground if foreground is not None else np.ones(vx.shape, dtype=bool)
    reliable, threshold = reliability_mask(flow["rel"], considered & finite, settings)
    analysed = considered & finite & reliable
    row.put("qc_reliability_threshold", threshold, "no reliability filtering")
    v = {"x": vx[analysed], "y": vy[analysed], "z": vz[analysed]}
    speed_reason = ""
    if settings.speed_mode == "xyz" and not (scale.consistent and has_vz):
        speed_reason = (
            "3D speed needs X, Y, Z and time calibration (one physical unit)"
            if has_vz
            else NO_AXIAL
        )
        speed_all = np.full(vx.shape, np.nan)
        _put_stats(row, "speed_3d", np.array([]))
        for key in [k for k in row.undefined if k.startswith("speed_3d")]:
            row.undefined[key] = speed_reason
    else:
        speed_all = np.hypot(vx, vy)
        if settings.speed_mode == "xyz":
            speed_all = np.hypot(speed_all, vz)
        _put_stats(
            row, "speed_3d" if settings.speed_mode == "xyz" else "speed_xy", speed_all[analysed]
        )
    _put_components(row, v, scale, settings.speed_mode == "xyz")
    row.put("coherence_xy_global", _coherence([v["x"], v["y"]]), "all analysed vectors are zero")
    row.put(
        "coherence_3d_global",
        _coherence([v["x"], v["y"], v["z"]]) if scale.consistent else None,
        "all analysed vectors are zero"
        if scale.consistent
        else "lateral and axial velocities are not in one physical unit",
    )
    local = local_coherence_map(
        vx, vy, analysed, settings.local_window_px, settings.min_local_vectors
    )
    defined = local[np.isfinite(local)]
    row.put(
        "coherence_xy_local",
        float(np.mean(defined)) if defined.size else None,
        f"no window with >= {settings.min_local_vectors} analysed nonzero vectors",
    )
    _put_angles(row, v["x"], v["y"], settings)
    _put_regions(
        row, np.where(analysed, speed_all, np.nan), vx, vy, analysed, settings, speed_reason
    )
    _put_quality(row, flow["rel"], considered, finite, analysed, foreground)
    _put_foreground_shape(row, foreground, intensity, settings.intensity_features)
    if not has_vz:
        for name in AXIAL_COLUMNS:
            row.put(name, None, NO_AXIAL)
    return row
