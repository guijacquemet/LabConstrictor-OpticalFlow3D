"""Average per-frame features over time into one row per field of view (pure).

The run keeps two tables: ``features_per_frame.csv`` stores every value (one row per field
of view and optical-flow time point ``t``), and ``features_per_fov.csv`` stores, under the
same column names, each feature averaged over the time points of its field of view. The
time points are repeated measurements of one sample, never replicates. Nothing is averaged
per biological repeat in the tables.

The average is the arithmetic mean over the defined time points (undefined frames are
left out and counted, never read as 0); orientation angles in degrees get the circular
mean. A field of view whose feature is undefined in every frame keeps NaN, with the reason.
"""

from __future__ import annotations

import numpy as np

from .feature_dictionary import ORIENTATION, FeatureDef


def _is_angle(definition: FeatureDef) -> bool:
    """Return whether a feature is an angle in degrees (circular mean)."""
    return definition.applicability == ORIENTATION and definition.name.endswith("_deg")


def fov_dictionary(frame_defs: list[FeatureDef]) -> list[FeatureDef]:
    """Return the definitions of the per-FOV columns (same names as the per-frame ones).

    Parameters
    ----------
    frame_defs
        Per-frame definitions.

    Returns
    -------
    list of FeatureDef
        One entry per column, ``level`` ``fov``.
    """
    out = []
    for d in frame_defs:
        how = "circular mean" if _is_angle(d) else "mean"
        out.append(
            FeatureDef(
                d.name,
                d.family,
                f"{d.description} ({how} over the optical-flow time points of the field of "
                "view; undefined time points left out)",
                f"{how} over frames of: {d.formula}",
                d.unit,
                "fov",
                d.requires,
                d.applicability,
                "no defined frame (or, for angles, a mean resultant below 1e-12); frame: "
                f"{d.undefined}",
            )
        )
    return out


def circular_mean(values: np.ndarray) -> float:
    """Return the circular mean (degrees) of angles in degrees; NaN without a resultant."""
    radians = np.deg2rad(values)
    c, s = float(np.mean(np.cos(radians))), float(np.mean(np.sin(radians)))
    if float(np.hypot(c, s)) < 1e-12:
        return float("nan")
    return float(np.rad2deg(np.arctan2(s, c)))


def aggregate_fov(
    frames: list[dict[str, float]], frame_defs: list[FeatureDef]
) -> tuple[dict[str, float], dict[str, str]]:
    """Average the per-frame features of one field of view over time.

    Parameters
    ----------
    frames
        Feature values of each optical-flow output.
    frame_defs
        Per-frame definitions.

    Returns
    -------
    tuple
        Averages (plus ``n_flow_frames``) and the reason of every undefined average. The
        frames left out of a defined average stay visible in the per-frame table.
    """
    values: dict[str, float] = {}
    undefined: dict[str, str] = {}
    for d in frame_defs:
        series = np.asarray([f.get(d.name, np.nan) for f in frames], dtype=float)
        defined = series[np.isfinite(series)]
        if defined.size == 0:
            values[d.name] = float("nan")
        elif _is_angle(d):
            values[d.name] = circular_mean(defined)
        else:
            values[d.name] = float(np.mean(defined))
        if not np.isfinite(values[d.name]):
            undefined[d.name] = f"{defined.size} defined frame(s) of {series.size}"
    values["n_flow_frames"] = float(len(frames))
    return values, undefined
