"""The machine-readable dictionary of every feature column (pure).

Each entry says what a column means, how it is computed, its unit, at which level it is
observed, what it needs, whether it is a biological readout, an experimental axial
readout, an orientation descriptor or quality control, and when it is undefined. The
profile analysis selects PCA inputs from these entries, never from column names alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import SpeedMode
from .flow_features import QUANTILES

BIOLOGICAL = "biological"
AXIAL = "experimental_axial"
ORIENTATION = "orientation"
QC = "qc"


@dataclass(frozen=True)
class FeatureDef:
    """Description of one feature column.

    Attributes
    ----------
    name
        Column name.
    family
        ``magnitude``, ``components``, ``collective``, ``spatial``, ``quality`` or
        ``temporal`` (aggregates keep their base family).
    description, formula
        Plain-language meaning and the computation.
    unit
        ``lateral``/``axial`` mean the speed unit of the run (µm/min, px/frame,
        slice/frame); other values are literal.
    level
        ``frame`` or ``fov``.
    requires
        Inputs needed.
    applicability
        ``biological``, ``experimental_axial``, ``orientation`` or ``qc``.
    undefined
        When the value is NaN.
    """

    name: str
    family: str
    description: str
    formula: str
    unit: str
    level: str
    requires: str
    applicability: str
    undefined: str


NO_VOXELS = "no analysed voxel (empty foreground or nothing passes the reliability criterion)"
SPEED_NOTE = (
    " Optical-flow speed: intensity-pattern motion, with the gain bias documented"
    " in docs/validation.md; not a calibrated nuclear displacement."
)


def _magnitude(mode: SpeedMode) -> list[FeatureDef]:
    """Return the magnitude family for the run's speed mode."""
    prefix = "speed_3d" if mode == "xyz" else "speed_xy"
    speed = "sqrt(vx²+vy²+vz²)" if mode == "xyz" else "sqrt(vx²+vy²)"
    applicability = AXIAL if mode == "xyz" else BIOLOGICAL
    stats = {
        "mean": ("Mean speed", "mean(s)"),
        "median": ("Median speed", "median(s)"),
        "sd": ("Standard deviation of speed", "std(s), ddof=0"),
        "cv": ("Coefficient of variation of speed", "std(s)/mean(s)"),
        "rms": ("Root-mean-square speed", "sqrt(mean(s²))"),
        **{f"p{q}": (f"{q}th percentile of speed", f"percentile(s, {q})") for q in QUANTILES},
        "max": ("Maximum speed", "max(s)"),
    }
    return [
        FeatureDef(
            f"{prefix}_{key}",
            "magnitude",
            text + " over analysed voxels." + SPEED_NOTE,
            f"s = {speed} per voxel (scaled per axis); {formula}",
            "1" if key == "cv" else "lateral",
            "frame",
            "vx, vy" + (", vz" if mode == "xyz" else ""),
            applicability,
            NO_VOXELS + ("; cv: mean speed is zero" if key == "cv" else ""),
        )
        for key, (text, formula) in stats.items()
    ]


NONZERO = "fewer than min_direction_vectors analysed vectors with XY speed > min_direction_speed"
FEW_REGIONS = "fewer than 2 full regions with min_region_voxels analysed voxels"
ORIENTED = " Depends on image orientation; not comparable between differently oriented images."

# name, description, formula, unit, requires, applicability, undefined
COMPONENT_ROWS = [
    ("vx_mean", "Mean signed vx." + ORIENTED, "mean(vx)", "lateral", "vx", ORIENTATION),
    ("vy_mean", "Mean signed vy (y down)." + ORIENTED, "mean(vy)", "lateral", "vy", ORIENTATION),
    ("vz_mean", "Mean signed vz." + ORIENTED, "mean(vz)", "axial", "vz", ORIENTATION),
    ("vx_sd", "Standard deviation of vx.", "std(vx)", "lateral", "vx", BIOLOGICAL),
    ("vy_sd", "Standard deviation of vy.", "std(vy)", "lateral", "vy", BIOLOGICAL),
    ("vz_sd", "Standard deviation of vz.", "std(vz)", "axial", "vz", AXIAL),
    ("vx_abs_mean", "Mean absolute vx.", "mean(|vx|)", "lateral", "vx", BIOLOGICAL),
    ("vy_abs_mean", "Mean absolute vy.", "mean(|vy|)", "lateral", "vy", BIOLOGICAL),
    ("vz_abs_mean", "Mean absolute vz.", "mean(|vz|)", "axial", "vz", AXIAL),
]
LATERAL_ROW = (
    "lateral_speed_mean",
    "Mean XY speed (in XY mode this is speed_xy_mean).",
    "mean(sqrt(vx²+vy²))",
    "lateral",
    "vx, vy",
    BIOLOGICAL,
)
RATIO_ROW = (
    "axial_lateral_ratio",
    "Axial versus lateral motion.",
    "mean(|vz|)/mean(sqrt(vx²+vy²))",
    "1",
    "vx, vy, vz in one unit",
    AXIAL,
    NO_VOXELS + "; lateral speed zero; lateral and axial units differ",
)

COLLECTIVE_ROWS = [
    (
        "coherence_xy_global",
        "Global XY directional coherence (1 = all vectors parallel, "
        "0 = no net direction), speed weighted.",
        "|Σ(vx,vy)| / Σ|(vx,vy)|",
        "1",
        "vx, vy",
        BIOLOGICAL,
        NO_VOXELS + "; all analysed vectors are zero",
    ),
    (
        "coherence_3d_global",
        "Global 3D directional coherence.",
        "|Σ(vx,vy,vz)| / Σ|(vx,vy,vz)|",
        "1",
        "vx, vy, vz in one unit",
        AXIAL,
        NO_VOXELS + "; all analysed vectors are zero; units differ",
    ),
    (
        "coherence_xy_local",
        "Mean local XY coherence in a square XY window (local_window_px) of the same slice; "
        "windows with fewer than min_local_vectors analysed nonzero vectors are left out.",
        "mean over analysed voxels of |Σ_window v| / Σ_window |v|",
        "1",
        "vx, vy",
        BIOLOGICAL,
        NO_VOXELS + "; no window with min_local_vectors analysed nonzero vectors",
    ),
    (
        "xy_angular_entropy",
        "Normalised Shannon entropy of XY directions (1 = uniform, 0 = one direction). One "
        "bin is centred on the dominant direction, so rotating the image does not change it.",
        "-Σ p log p / log(angle_bins), angle_bins bins with one centred on θ_dom",
        "1",
        "vx, vy",
        BIOLOGICAL,
        NONZERO,
    ),
    (
        "xy_angular_dispersion",
        "Circular variance of XY directions, unweighted (0 = aligned, 1 = no mean direction).",
        "1 - |mean(exp(iθ))|",
        "1",
        "vx, vy",
        BIOLOGICAL,
        NONZERO,
    ),
    (
        "xy_aligned_fraction",
        "Fraction of directed XY vectors within aligned_angle_deg of the dominant direction.",
        "mean(cos(θ-θ_dom) >= cos(aligned_angle_deg))",
        "1",
        "vx, vy",
        BIOLOGICAL,
        NONZERO + "; mean resultant zero",
    ),
    (
        "xy_dominant_direction_deg",
        "Dominant XY direction (image coordinates, y down)." + ORIENTED + " Not a PCA input.",
        "atan2(mean sinθ, mean cosθ)",
        "degree",
        "vx, vy",
        ORIENTATION,
        NONZERO + "; mean resultant zero",
    ),
]

SPATIAL_ROWS = [
    (
        "regional_speed_cv",
        "Variation of mean speed between fixed square XY regions (region_size_px, all Z).",
        "std(R)/mean(R), R = region mean speeds",
        "1",
        "speed",
        BIOLOGICAL,
        FEW_REGIONS,
    ),
    (
        "regional_speed_spread",
        "Regional speed heterogeneity.",
        "(P90(R)-P10(R))/median(R)",
        "1",
        "speed",
        BIOLOGICAL,
        FEW_REGIONS,
    ),
    (
        "regional_coherence_sd",
        "Variation of directional coherence between regions.",
        "std of region |Σv|/Σ|v| (XY)",
        "1",
        "vx, vy",
        BIOLOGICAL,
        FEW_REGIONS,
    ),
    (
        "regional_moving_fraction",
        "Fraction of regions whose mean speed exceeds motion_threshold.",
        "mean(R > motion_threshold)",
        "1",
        "speed, motion_threshold",
        BIOLOGICAL,
        "motion_threshold not set; no region",
    ),
]

QC_ROWS = [
    (
        "qc_reliability_threshold",
        "Reliability threshold applied in this frame.",
        "absolute value, or percentile of foreground reliability",
        "reliability",
    ),
    (
        "qc_reliability_median",
        "Median reliability in the foreground (before filtering).",
        "median(rel)",
        "reliability",
    ),
    (
        "qc_reliability_p10",
        "10th percentile of foreground reliability.",
        "percentile",
        "reliability",
    ),
    (
        "qc_reliability_p90",
        "90th percentile of foreground reliability.",
        "percentile",
        "reliability",
    ),
    (
        "qc_reliable_fraction",
        "Fraction of finite foreground voxels passing the reliability criterion.",
        "n(reliable)/n(finite foreground)",
        "1",
    ),
    (
        "qc_invalid_velocity_fraction",
        "Fraction of foreground voxels with a non-finite velocity component.",
        "n(non-finite)/n(foreground)",
        "1",
    ),
    (
        "qc_foreground_fraction",
        "Fraction of the volume in the foreground (occupancy).",
        "mean(foreground)",
        "1",
    ),
    ("qc_n_analysed_voxels", "Number of analysed voxels.", "count", "voxel"),
    ("qc_n_regions", "Number of full regions of the grid.", "count", "region"),
    ("qc_n_regions_analysed", "Regions with enough analysed voxels.", "count", "region"),
    (
        "qc_region_grid_coverage",
        "Fraction of the XY image covered by full regions (partial edge regions are left out).",
        "n_regions·region_size² / (Y·X)",
        "1",
    ),
    (
        "qc_brightness_change_per_frame",
        "Global brightness change across the optical-flow time window (illumination, focus, "
        "bleaching or expression). Optical flow reads part of a brightness change as motion; "
        "values above 0.02 are flagged.",
        "least-squares slope of the window frames' mean raw intensity / central frame's mean",
        "1/frame",
    ),
    (
        "qc_invalid_reliability_fraction",
        "Fraction of finite-velocity foreground voxels with non-finite reliability (never "
        "reliable, never used to set a threshold).",
        "n(non-finite rel)/n(finite foreground)",
        "1",
    ),
    (
        "qc_foreground_intensity_mean",
        "Mean raw intensity in the foreground (confounder; undefined without a foreground).",
        "mean(I)",
        "raw intensity",
    ),
    (
        "qc_object_mean_voxels",
        "Mean size of connected foreground objects (confounder of the optical-flow gain).",
        "mean voxel count of 3D connected components",
        "voxel",
    ),
    (
        "qc_object_mean_z_extent",
        "Mean Z extent of foreground objects (confounder of the axial gain).",
        "mean slice span of components",
        "slice",
    ),
    ("qc_n_objects", "Number of connected foreground objects.", "count", "object"),
]


def _rows(family: str, rows: list[tuple], undefined: str = NO_VOXELS) -> list[FeatureDef]:
    """Build definitions from rows of name, description, formula, unit, requires, applicability.

    An optional seventh item overrides ``undefined``.
    """
    out = []
    for row in rows:
        name, description, formula, unit, requires, applicability = row[:6]
        reason = row[6] if len(row) > 6 else undefined
        out.append(
            FeatureDef(
                name, family, description, formula, unit, "frame", requires, applicability, reason
            )
        )
    return out


def _components(mode: SpeedMode) -> list[FeatureDef]:
    """Return the velocity-component family."""
    rows = COMPONENT_ROWS + ([LATERAL_ROW] if mode == "xyz" else []) + [RATIO_ROW]
    return _rows("components", rows)


def _quality() -> list[FeatureDef]:
    """Return the quality-control family (never a PCA input by default)."""
    rows = [(n, d, f, u, "rel, foreground", QC) for n, d, f, u in QC_ROWS]
    return _rows("quality", rows, "no foreground voxel, or input not supplied")


def frame_dictionary(mode: SpeedMode) -> list[FeatureDef]:
    """Return the definitions of every per-frame feature column for a speed mode.

    Parameters
    ----------
    mode
        ``"xy"`` or ``"xyz"``.

    Returns
    -------
    list of FeatureDef
        In the column order of ``features_per_frame.csv``.
    """
    return [
        *_magnitude(mode),
        *_components(mode),
        *_rows("collective", COLLECTIVE_ROWS),
        *_rows("spatial", SPATIAL_ROWS),
        *_quality(),
    ]


def dictionary_records(definitions: list[FeatureDef]) -> list[dict[str, str]]:
    """Return the definitions as JSON-ready dictionaries."""
    return [asdict(d) for d in definitions]
