"""Load per-FOV feature tables from runs, run PCA and comparisons, export results (I/O).

Several runs (experiments) can be combined only when their feature dictionaries agree on
units and speed mode, so that a column means the same thing in every row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .comparison import compare_all
from .config import to_record
from .experiment import METADATA_COLUMNS
from .feature_dictionary import FeatureDef
from .profile_analysis import PcaResult, PcaSettings, correlation_matrix, prepare_matrix, run_pca
from .results import environment, now, write_csv, write_json
from .validation import InputError


@dataclass(frozen=True)
class FeatureSet:
    """Per-FOV features of one or more runs with their shared dictionary."""

    table: pd.DataFrame
    fov_defs: list[FeatureDef]
    units: dict[str, str]
    sources: list[str]


def load_runs(run_dirs: list[Path]) -> FeatureSet:
    """Load and combine ``features/features_per_fov.csv`` of several run folders.

    Parameters
    ----------
    run_dirs
        Run folders written by the pipeline.

    Returns
    -------
    FeatureSet
        Combined table (metadata as text) and the common dictionary.

    Raises
    ------
    InputError
        When a run is missing its tables, units or speed mode differ between runs, or
        a ``fov_uid`` appears twice.
    """
    tables, dictionary, units = [], None, None
    for run in sorted(Path(r) for r in run_dirs):
        table_path = run / "features" / "features_per_fov.csv"
        dict_path = run / "features" / "feature_dictionary.json"
        if not table_path.is_file() or not dict_path.is_file():
            raise InputError(f"{run} has no feature tables; extract features first.")
        info = json.loads(dict_path.read_text(encoding="utf-8"))
        names = [d["name"] for d in info["fov_features"]]
        if dictionary is None:
            dictionary, units = info, info["units"]
        elif info["units"] != units or names != [d["name"] for d in dictionary["fov_features"]]:
            raise InputError(
                f"{run} uses different units or features ({info['units']}) from "
                f"the first run ({units}); runs cannot be combined."
            )
        text = {c: str for c in METADATA_COLUMNS}
        table = pd.read_csv(table_path, dtype=text, keep_default_na=False, na_values=[""])
        table.insert(1, "run", run.name)
        tables.append(table)
    if not tables:
        raise InputError("No run folder was given.")
    combined = pd.concat(tables, ignore_index=True)
    duplicated = combined["fov_uid"][combined["fov_uid"].duplicated()].unique()
    if len(duplicated):
        raise InputError("The same field of view appears in several runs: " + ", ".join(duplicated))
    defs = [FeatureDef(**d) for d in dictionary["fov_features"]]
    return FeatureSet(combined, defs, units, [Path(r).as_posix() for r in run_dirs])


def metadata_columns(table: pd.DataFrame) -> list[str]:
    """Return the identification columns of a combined table (never PCA inputs)."""
    return [c for c in ("run", *METADATA_COLUMNS, "undefined_features") if c in table.columns]


def analyse(features: FeatureSet, settings: PcaSettings) -> PcaResult:
    """Prepare the matrix and run the PCA (see :mod:`profile_analysis`)."""
    prepared = prepare_matrix(
        features.table, metadata_columns(features.table), features.fov_defs, settings
    )
    return run_pca(prepared, settings.n_components)


def export_analysis(
    out_dir: Path,
    features: FeatureSet,
    settings: PcaSettings,
    result: PcaResult,
    comparison: pd.DataFrame | None = None,
) -> None:
    """Write scores, loadings, settings, matrix, exclusions and comparisons.

    Parameters
    ----------
    out_dir
        Analysis folder (created if needed). Existing files of the same name are
        replaced atomically; use a new folder to keep an earlier analysis.
    features
        Combined features.
    settings
        PCA settings.
    result
        PCA result.
    comparison
        Optional output of :func:`~opticalflow3d_profiler.comparison.compare_all`.
    """
    out_dir = Path(out_dir)
    prepared = result.prepared
    write_csv(out_dir / "pca_scores.csv", result.scores)
    write_csv(out_dir / "pca_loadings.csv", result.loadings)
    write_csv(out_dir / "pca_feature_matrix.csv", prepared.matrix.reset_index())
    write_csv(out_dir / "pca_scaling.csv", result.scaling)
    write_csv(
        out_dir / "feature_correlation.csv",
        correlation_matrix(prepared).reset_index(names="feature"),
    )
    if comparison is not None:
        write_csv(out_dir / "condition_comparison.csv", comparison)
    write_json(
        out_dir / "analysis_settings.json",
        {
            "created": now(),
            "environment": environment(),
            "sources": features.sources,
            "units": features.units,
            "pca_settings": to_record(settings),
            "explained_variance_ratio": result.explained_variance_ratio,
            "n_fovs": int(prepared.matrix.shape[0]),
            "n_features": int(prepared.matrix.shape[1]),
            "excluded_features": prepared.excluded_features,
            "excluded_fovs": prepared.excluded_fovs,
            "warnings": prepared.warnings,
            "standardisation": "z-score per feature (scikit-learn StandardScaler, ddof=0)",
        },
    )


def compare_conditions(
    features: FeatureSet, control: str, treatment: str, paired: bool = False
) -> pd.DataFrame:
    """Compare two conditions on the default readouts and confounders."""
    return compare_all(features.table, control, treatment, paired)
