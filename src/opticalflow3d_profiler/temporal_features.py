"""Aggregate per-frame features into one profile per field of view (pure).

The optical-flow time points of one field of view are repeated measurements of the same
sample, not replicates: the aggregates describe the sample's temporal behaviour. Which
statistics a feature gets depends on its applicability (feature dictionary): biological
and axial readouts get the temporal mean, SD and slope, a few interpretable ones also
minimum and maximum; signed components only the mean; the dominant direction circular
statistics; QC columns the mean (and the minimum for coverage).
"""

from __future__ import annotations

import numpy as np

from .feature_dictionary import AXIAL, BIOLOGICAL, ORIENTATION, QC, FeatureDef

EXTREMES = ("_median", "_p90", "coherence_xy_global", "coherence_xy_local", "regional_speed_cv")
QC_MINIMUM = ("qc_reliable_fraction", "qc_n_analysed_voxels", "qc_reliability_threshold")
SEPARATOR = "__t"


def _stats_for(definition: FeatureDef) -> tuple[str, ...]:
    """Return the temporal statistics computed for one feature."""
    name = definition.name
    if definition.applicability == ORIENTATION:
        return ("circmean", "circsd") if name.endswith("_deg") else ("mean",)
    if definition.applicability == QC:
        if name in ("qc_reliability_threshold", "qc_brightness_change_per_frame"):
            return ("mean", "min", "max")
        return ("mean", "min") if name in QC_MINIMUM else ("mean",)
    extremes = definition.family == "magnitude" and name.endswith(EXTREMES[:2])
    if extremes or name in EXTREMES[2:]:
        return ("mean", "sd", "min", "max", "slope")
    return ("mean", "sd", "slope")


def fov_dictionary(frame_defs: list[FeatureDef], time_unit: str) -> list[FeatureDef]:
    """Return the definitions of the per-FOV aggregate columns.

    Parameters
    ----------
    frame_defs
        Per-frame definitions.
    time_unit
        ``"min"`` when the frame interval is known, else ``"frame"``.

    Returns
    -------
    list of FeatureDef
        One entry per aggregate column, ``<feature>__t<statistic>``.
    """
    text = {
        "mean": "temporal mean",
        "sd": "temporal standard deviation (ddof=1)",
        "min": "temporal minimum",
        "max": "temporal maximum",
        "slope": f"least-squares slope against time (per {time_unit})",
        "circmean": "circular temporal mean",
        "circsd": "circular standard deviation",
    }
    need = {
        "sd": "fewer than 2 defined frames",
        "slope": "fewer than 3 defined frames",
        "circsd": "fewer than 2 defined frames",
    }
    out = []
    for d in frame_defs:
        for stat in _stats_for(d):
            unit = d.unit if stat != "slope" else f"{d.unit} per {time_unit}"
            out.append(
                FeatureDef(
                    f"{d.name}{SEPARATOR}{stat}",
                    d.family,
                    f"{d.description} ({text[stat]} "
                    "over the optical-flow time points of the field of view)",
                    f"{stat} over frames of: {d.formula}",
                    unit,
                    "fov",
                    d.requires,
                    d.applicability,
                    f"{need.get(stat, 'no defined frame')}; frame: {d.undefined}",
                )
            )
    return out


def _circular(values: np.ndarray) -> tuple[float, float]:
    """Return the circular mean and circular SD (degrees) of angles in degrees."""
    radians = np.deg2rad(values)
    c, s = float(np.mean(np.cos(radians))), float(np.mean(np.sin(radians)))
    resultant = float(np.hypot(c, s))
    if resultant < 1e-12:
        return float("nan"), float("nan")
    return float(np.rad2deg(np.arctan2(s, c))), float(np.rad2deg(np.sqrt(-2 * np.log(resultant))))


def _aggregate(stat: str, times: np.ndarray, values: np.ndarray) -> float:
    """Return one temporal statistic over the defined frames (NaN when undefined)."""
    ok = np.isfinite(values)
    v, t = values[ok], times[ok]
    minimum = {"sd": 2, "slope": 3, "circsd": 2}.get(stat, 1)
    if v.size < minimum:
        return float("nan")
    if stat == "mean":
        return float(np.mean(v))
    if stat == "sd":
        return float(np.std(v, ddof=1))
    if stat == "min":
        return float(np.min(v))
    if stat == "max":
        return float(np.max(v))
    if stat == "slope":
        return float(np.polyfit(t, v, 1)[0])
    mean, sd = _circular(v)
    return mean if stat == "circmean" else sd


def aggregate_fov(
    frames: list[dict[str, float]],
    source_frames: list[int],
    frame_defs: list[FeatureDef],
    frame_interval: float | None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Aggregate the per-frame features of one field of view.

    Parameters
    ----------
    frames
        Feature values of each optical-flow output.
    source_frames
        Source time point of each output (same order).
    frame_defs
        Per-frame definitions.
    frame_interval
        Minutes per frame, or ``None`` (slopes are then per frame).

    Returns
    -------
    tuple
        Aggregate values and the reason of every undefined aggregate.
    """
    times = np.asarray(source_frames, dtype=float) * (frame_interval or 1.0)
    values: dict[str, float] = {}
    undefined: dict[str, str] = {}
    for d in frame_defs:
        series = np.asarray([f.get(d.name, np.nan) for f in frames], dtype=float)
        for stat in _stats_for(d):
            name = f"{d.name}{SEPARATOR}{stat}"
            values[name] = _aggregate(stat, times, series)
            if not np.isfinite(values[name]):
                n = int(np.isfinite(series).sum())
                undefined[name] = f"{n} defined frame(s) of {series.size}"
    values["n_flow_frames"] = float(len(frames))
    return values, undefined


def pca_eligible(definition: FeatureDef, include_axial: bool) -> bool:
    """Return True when a column may be a PCA input under the given choice."""
    if definition.applicability == BIOLOGICAL:
        return True
    return include_axial and definition.applicability == AXIAL
