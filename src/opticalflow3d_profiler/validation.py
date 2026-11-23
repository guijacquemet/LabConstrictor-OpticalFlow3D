"""Checks of axes, the single channel, calibration and time-series length (pure).

Problems the user can fix are returned as :class:`Issue` objects with a plain-language
message and a suggested action; :func:`raise_for_errors` turns error-level issues into one
:class:`InputError` before anything is computed. Nothing here guesses an axis, a channel or
a calibration value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from .config import (
    AUTO_PER_SLICE_ANISOTROPY,
    Calibration,
    FeatureSettings,
    FlowParameters,
    ForegroundSpec,
)

Severity = Literal["error", "warning"]

ALLOWED_AXES = frozenset("TZCYX")
LENGTH_TO_MICROMETRE = {"nm": 1e-3, "um": 1.0, "µm": 1.0, "micron": 1.0, "mm": 1e3}
TIME_TO_MINUTE = {"ms": 1 / 60000, "s": 1 / 60, "sec": 1 / 60, "min": 1.0, "h": 60.0}


class InputError(ValueError):
    """Raised when an input cannot be analysed as configured."""


@dataclass(frozen=True)
class Issue:
    """One validation finding.

    Attributes
    ----------
    severity
        ``"error"`` stops processing; ``"warning"`` is recorded and shown.
    code
        Stable identifier, for example ``"axes_unconfirmed"``.
    message
        What is wrong, in plain language.
    action
        What the user can do about it.
    """

    severity: Severity
    code: str
    message: str
    action: str = ""


def raise_for_errors(issues: list[Issue]) -> None:
    """Raise :class:`InputError` listing every error-level issue.

    Parameters
    ----------
    issues
        Findings from the checks of this module.

    Raises
    ------
    InputError
        When at least one issue has severity ``"error"``.
    """
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        lines = [f"- {i.message} {i.action}".rstrip() for i in errors]
        raise InputError("The input cannot be processed:\n" + "\n".join(lines))


def check_axes(confirmed_axes: str, shape: tuple[int, ...]) -> list[Issue]:
    """Check a user-confirmed axis string against a file's shape.

    Parameters
    ----------
    confirmed_axes
        Axis letters in file order, from ``T``, ``Z``, ``C``, ``Y``, ``X``.
    shape
        Shape of the file's first series.

    Returns
    -------
    list of Issue
        Errors for unknown, repeated or missing letters and length mismatches.
    """
    axes = confirmed_axes.strip().upper()
    issues: list[Issue] = []
    if not axes:
        return [
            Issue(
                "error",
                "axes_unconfirmed",
                "The axes have not been confirmed.",
                "Type the axis letters of the file, for example TZYX.",
            )
        ]
    unknown = sorted(set(axes) - ALLOWED_AXES)
    if unknown:
        issues.append(
            Issue(
                "error",
                "axes_unknown",
                f"Unknown axis letters: {''.join(unknown)}.",
                "Use only T, Z, C, Y and X.",
            )
        )
    if len(set(axes)) != len(axes):
        issues.append(
            Issue(
                "error",
                "axes_repeated",
                f"An axis letter is repeated in {axes}.",
                "Name each axis once.",
            )
        )
    if len(axes) != len(shape):
        issues.append(
            Issue(
                "error",
                "axes_length",
                f"{len(axes)} axis letters were given for an image with {len(shape)} dimensions "
                f"{tuple(shape)}.",
                "Give one letter per dimension.",
            )
        )
    for needed in "TZYX":
        if needed not in axes:
            issues.append(
                Issue(
                    "error",
                    f"axes_missing_{needed.lower()}",
                    f"The image has no {needed} axis.",
                    "3D optical flow needs a time-lapse of Z-stacks (TZYX).",
                )
            )
    if not issues and axes[-2:] != "YX":
        issues.append(
            Issue(
                "warning",
                "axes_yx_not_last",
                f"Y and X are not the last two axes ({axes}).",
                "Check that the confirmed order is really the file's order.",
            )
        )
    return issues


def check_channel(axes: str, shape: tuple[int, ...]) -> list[Issue]:
    """Check that the video has a single channel.

    The profiler analyses single-channel videos: a ``C`` axis is accepted only with length 1.
    No channel is ever chosen from a multi-channel file.

    Parameters
    ----------
    axes
        Confirmed axes in file order.
    shape
        Shape of the file's first series.

    Returns
    -------
    list of Issue
        An error for a multi-channel file.
    """
    axes = axes.upper()
    n_channels = shape[axes.index("C")] if "C" in axes and len(axes) == len(shape) else 1
    if n_channels > 1:
        return [
            Issue(
                "error",
                "multi_channel_not_supported",
                f"The image has {n_channels} channels; this tool analyses single-channel videos.",
                "Save the nuclear channel alone as a TIFF (for example with Fiji) and use that.",
            )
        ]
    return []


def check_time_and_depth(n_t: int, n_z: int, params: FlowParameters) -> list[Issue]:
    """Check that the movie is long enough for the upstream time window.

    Parameters
    ----------
    n_t, n_z
        Number of time points and Z slices.
    params
        Upstream parameters (``window_length`` frames per output).

    Returns
    -------
    list of Issue
        An error when fewer than ``window_length`` frames exist or Z has one slice; a
        warning when the Z stack is shorter than the spatial smoothing kernel.
    """
    issues: list[Issue] = []
    if n_t < params.window_length:
        issues.append(
            Issue(
                "error",
                "too_few_frames",
                f"The movie has {n_t} time points; tSig={params.t_sig} needs at least "
                f"{params.window_length}.",
                "Use a longer movie or a smaller tSig.",
            )
        )
    if params.mode == "xy_per_slice":
        return issues
    if n_z < 2:
        issues.append(
            Issue(
                "error",
                "single_z",
                "The image has a single Z slice.",
                "3D optical flow needs Z-stacks.",
            )
        )
    kernel = 2 * math.ceil(3 * params.xyz_sig) + 1
    if 2 <= n_z < kernel:
        issues.append(
            Issue(
                "warning",
                "shallow_z",
                f"The Z stack ({n_z} slices) is shorter than the spatial derivative kernel "
                f"({kernel} slices for xyzSig={params.xyz_sig}); upstream pads with the edge "
                "slices, so axial velocities are experimental, especially near the top and "
                "bottom slices.",
                "",
            )
        )
    return issues


def resolve_flow_mode(params: FlowParameters, calibration: Calibration) -> FlowParameters:
    """Return the parameters with a concrete flow mode (``auto`` resolved from anisotropy).

    Raises
    ------
    InputError
        When ``auto`` cannot decide because the XY or Z voxel size is unknown.
    """
    if params.mode != "auto":
        return params
    xy, z = calibration.pixel_size_x, calibration.pixel_size_z
    if xy is None or z is None:
        raise InputError(
            "The flow mode 'auto' needs the XY pixel size and the Z spacing; enter "
            "them, or choose 'xyz' (3D) or 'xy_per_slice' (2D per slice)."
        )
    mode = "xy_per_slice" if z / xy > AUTO_PER_SLICE_ANISOTROPY else "xyz"
    return replace(params, mode=mode)


def output_frame_map(n_t: int, params: FlowParameters) -> list[int]:
    """Return the source time point of every optical-flow output, in order.

    Parameters
    ----------
    n_t
        Number of time points in the movie.
    params
        Upstream parameters.

    Returns
    -------
    list of int
        Source frame indices (0-based); upstream analyses the central frame of each
        window, so the first ``half_window`` and last ``half_window`` frames have no output.
    """
    half = params.half_window
    return list(range(half, n_t - half)) if n_t >= params.window_length else []


def to_micrometres(value: float | None, unit: str) -> float | None:
    """Convert a length to micrometres; ``None`` stays ``None``.

    Parameters
    ----------
    value
        Length, or ``None`` when unknown.
    unit
        One of ``nm``, ``um``, ``µm``, ``micron``, ``mm``.

    Returns
    -------
    float or None
        The length in micrometres.

    Raises
    ------
    InputError
        For an unknown unit or a non-positive value.
    """
    return _convert(value, unit, LENGTH_TO_MICROMETRE, "length")


def to_minutes(value: float | None, unit: str) -> float | None:
    """Convert a time interval to minutes; ``None`` stays ``None``.

    Parameters
    ----------
    value
        Interval, or ``None`` when unknown.
    unit
        One of ``ms``, ``s``, ``sec``, ``min``, ``h``.

    Returns
    -------
    float or None
        The interval in minutes.

    Raises
    ------
    InputError
        For an unknown unit or a non-positive value.
    """
    return _convert(value, unit, TIME_TO_MINUTE, "time")


def _convert(value: float | None, unit: str, table: dict[str, float], kind: str) -> float | None:
    if value is None:
        return None
    key = unit.strip()
    if key not in table:
        raise InputError(f"Unknown {kind} unit '{unit}'. Use one of: {', '.join(table)}.")
    if not value > 0:
        raise InputError(f"A {kind} calibration must be positive, not {value}.")
    return float(value) * table[key]


def check_calibration(calibration: Calibration) -> list[Issue]:
    """Report which physical units are unavailable.

    Parameters
    ----------
    calibration
        The calibration to describe.

    Returns
    -------
    list of Issue
        Warnings only: missing calibration never stops the flow calculation, it keeps
        the results in voxels per frame.
    """
    issues: list[Issue] = []
    if not calibration.lateral_known:
        issues.append(
            Issue(
                "warning",
                "calibration_lateral_missing",
                "XY pixel size or frame interval is unknown: velocities stay in pixels/frame and "
                "physical speeds are unavailable.",
                "Enter the calibration to get µm/min.",
            )
        )
    if calibration.pixel_size_z is None:
        issues.append(
            Issue(
                "warning",
                "calibration_z_missing",
                "Z spacing is unknown: axial velocities stay in slices/frame and 3D speeds "
                "cannot be expressed physically.",
                "Enter the Z spacing.",
            )
        )
    return issues


def check_feature_settings(features: FeatureSettings, foreground: ForegroundSpec) -> list[Issue]:
    """Check feature and foreground settings before anything is computed.

    Parameters
    ----------
    features
        Feature settings.
    foreground
        Foreground definition.

    Returns
    -------
    list of Issue
        Errors for missing or impossible values.
    """
    issues: list[Issue] = []
    mode, value = features.reliability_mode, features.reliability_value
    if mode != "none" and value is None:
        issues.append(
            Issue(
                "error",
                "reliability_value_missing",
                f"Reliability mode '{mode}' needs a value.",
                "Enter a threshold (absolute) or a percentile, or choose 'none'.",
            )
        )
    if mode == "percentile" and value is not None and not 0 <= value <= 100:
        issues.append(
            Issue(
                "error",
                "reliability_percentile_range",
                f"A reliability percentile must be 0-100, not {value}.",
                "",
            )
        )
    for name, minimum in (
        ("region_size_px", 2),
        ("local_window_px", 3),
        ("angle_bins", 2),
        ("min_region_voxels", 1),
        ("min_direction_vectors", 1),
        ("min_local_vectors", 1),
    ):
        if getattr(features, name) < minimum:
            issues.append(
                Issue("error", f"{name}_too_small", f"{name} must be at least {minimum}.", "")
            )
    if features.min_direction_speed < 0:
        issues.append(
            Issue(
                "error",
                "min_direction_speed_negative",
                "min_direction_speed cannot be negative.",
                "",
            )
        )
    return issues + _check_foreground(foreground)


def _check_foreground(foreground: ForegroundSpec) -> list[Issue]:
    """Check the foreground definition (threshold value; warn without a foreground)."""
    issues: list[Issue] = []
    if foreground.mode == "threshold" and foreground.threshold is None:
        issues.append(
            Issue(
                "error",
                "foreground_threshold_missing",
                "The intensity-threshold foreground needs a threshold value.",
                "",
            )
        )
    if foreground.mode == "none":
        issues.append(
            Issue(
                "warning",
                "no_foreground",
                "No foreground: background and nuclear occupancy may influence the "
                "features (exploratory whole-image measurement).",
                "",
            )
        )
    return issues
