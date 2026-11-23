"""Feed the per-FOV features to MorphoCoverage and write its HTML report (I/O).

MorphoCoverage (CellMigrationLab, MIT licence, a pinned dependency) runs the condition
statistics and writes the report. This module only turns the profiler's per-FOV table into
MorphoCoverage's two input tables and its ``Setup``:

- ``objects``: one row per field of view (the observation, ``observation_unit="fov"``),
  with the MorphoBricks identity columns and the feature columns;
- ``fovs``: the same fields of view, with ``repeat_group``. MorphoCoverage pairs biological
  repeats across conditions only by this confirmed column, never by folder labels. The user
  confirms it in the design step. The repeat identity of :func:`~opticalflow3d_profiler.
  analysis.load_runs` (``repeat_id``: scoped to its run unless the labels are declared
  shared) is used as both the biological repeat and its group.

Only biological features (and, when chosen, the experimental axial ones) are declared as
features; ``qc_*`` columns are never phenotype. A feature undefined in every field of view is
left out and listed, never filled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .analysis import FeatureSet
from .naming import find_column
from .progress import Tracker
from .temporal_features import pca_eligible
from .validation import InputError

KEY = ("condition", "biological_repeat", "technical_repeat", "position_id")
REPORT_TITLE = "OpticalFlow3D Profiler: MorphoCoverage report"


@dataclass(frozen=True)
class Design:
    """The experimental design given to MorphoCoverage.

    Attributes
    ----------
    control
        The control condition every other condition is compared with.
    readout
        The main feature column (the report's readout; every feature is tested alike).
    repeats_paired
        The user's confirmation that a biological-repeat label means the same biological
        repeat in every condition (MorphoCoverage's ``repeat_group``). Required.
    include_axial
        Also declare the experimental axial (Z-dependent) features.
    random_state
        Seed of every MorphoCoverage resampling.
    """

    control: str
    readout: str
    repeats_paired: bool
    include_axial: bool = False
    random_state: int = 0


@dataclass
class CoverageInput:
    """MorphoCoverage's input tables and the declared features."""

    objects: pd.DataFrame
    fovs: pd.DataFrame
    features: list[str]
    notes: list[str] = field(default_factory=list)


def default_readout(features: FeatureSet) -> str:
    """Return the median speed column of the table (3D when present, else XY)."""
    columns = list(features.table.columns)
    found = find_column(columns, "speed_3d_median") or find_column(columns, "speed_xy_median")
    if found is None:
        raise InputError("The table has no median speed column; choose a readout.")
    return found


def feature_columns(features: FeatureSet, include_axial: bool) -> tuple[list[str], list[str]]:
    """Return the declared feature columns and those left out as undefined everywhere."""
    table = features.table
    chosen = [
        d.name for d in features.fov_defs if pca_eligible(d, include_axial) and d.name in table
    ]
    defined = [c for c in chosen if pd.to_numeric(table[c], errors="coerce").notna().any()]
    return defined, [c for c in chosen if c not in defined]


def coverage_input(features: FeatureSet, design: Design) -> CoverageInput:
    """Return MorphoCoverage's ``objects`` and ``fovs`` tables for a design.

    Raises
    ------
    InputError
        When the repeats are not confirmed as paired, the control or readout is unknown, or
        only one condition is present.
    """
    if not design.repeats_paired:
        raise InputError(
            "Confirm that each biological-repeat label is the same biological repeat in every "
            "condition (MorphoCoverage pairs repeats only by this confirmed repeat group)."
        )
    table = features.table
    conditions = sorted(table["condition"].unique())
    if design.control not in conditions:
        raise InputError(f"The control '{design.control}' is not one of {conditions}.")
    if len(conditions) < 2:
        raise InputError("Only one condition: nothing to compare with the control.")
    declared, undefined = feature_columns(features, design.include_axial)
    if design.readout not in declared:
        raise InputError(f"The readout '{design.readout}' is not a declared feature.")
    repeat = "repeat_id" if "repeat_id" in table.columns else "biological_repeat"
    keys = table[list(KEY)].astype(str).copy()
    keys["biological_repeat"] = table[repeat].astype(str)
    objects = pd.concat(
        [keys, table[declared].apply(pd.to_numeric, errors="coerce")], axis=1
    ).reset_index(drop=True)
    fovs = keys.reset_index(drop=True)
    fovs["repeat_group"] = fovs["biological_repeat"]
    notes = [f"Undefined in every field of view, not declared: {', '.join(undefined)}."] * bool(
        undefined
    )
    return CoverageInput(objects, fovs, declared, notes)


def run_report(
    features: FeatureSet, design: Design, out_dir: Path, tracker: Tracker | None = None
) -> tuple[Path, Any, CoverageInput]:
    """Run MorphoCoverage's report and write its full HTML page into a new folder.

    Parameters
    ----------
    features
        The combined per-FOV features (:func:`~opticalflow3d_profiler.analysis.load_runs`).
    design
        The confirmed design.
    out_dir
        New folder for ``report.html``, its figures and data (never overwritten).
    tracker
        Optional progress display: the design scan, the statistics, the HTML page.

    Returns
    -------
    tuple
        The page's path, MorphoCoverage's ``Report`` and the input tables.

    Raises
    ------
    InputError
        When ``out_dir`` exists or the design is not usable.
    """
    from morphocoverage.workflows import report, scan_design
    from morphocoverage.workflows.html_report import html_report

    out_dir = Path(out_dir)
    if out_dir.exists():
        raise InputError(f"{out_dir} exists; reports are never overwritten.")
    data = coverage_input(features, design)
    stage = (tracker or Tracker()).stage("MorphoCoverage", 3)
    scan = scan_design(data.objects, data.fovs)
    stage.update("design scanned")
    setup = scan.setup(
        readout=design.readout,
        control={"condition": design.control},
        observation_unit="fov",
        features=tuple(data.features),
        random_state=design.random_state,
    )
    result = report(scan.objects, scan.fovs, setup)
    stage.update("statistics done")
    out_dir.mkdir(parents=True)
    data.objects.to_csv(out_dir / "morphocoverage_objects.csv", index=False)
    data.fovs.to_csv(out_dir / "morphocoverage_fovs.csv", index=False)
    path = html_report(result, scan.objects, scan.fovs, out_dir, title=REPORT_TITLE)
    stage.update("report written")
    stage.close()
    return path, result, data
