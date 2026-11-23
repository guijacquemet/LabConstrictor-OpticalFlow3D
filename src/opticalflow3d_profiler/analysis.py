"""Load per-FOV feature tables from runs, run PCA and comparisons, export results (I/O).

Several runs (experiments) can be combined only when their feature dictionaries agree on
units and speed mode, so that a column means the same thing in every row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .comparison import ComparisonSettings
from .comparison import compare_conditions as compare_tables
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


def comparable_settings(run: Path) -> dict[str, object]:
    """Return the settings of a run that change feature values, for compatibility checks.

    Optical-flow parameters, every feature setting (reliability, speed mode, regions,
    windows, angular thresholds) and the foreground rule. The per-FOV mask files and the
    calibration values are not included: masks belong to each field of view, and a different
    pixel size is converted to the same physical unit (units are checked separately).

    Raises
    ------
    InputError
        When the run has no manifest with settings.
    """
    path = Path(run) / "run_manifest.json"
    if not path.is_file():
        raise InputError(f"{run} has no run_manifest.json; its settings cannot be checked.")
    settings = json.loads(path.read_text(encoding="utf-8")).get("settings", {})
    foreground = {k: v for k, v in settings.get("foreground", {}).items() if k != "mask_path"}
    return {
        "flow": settings.get("flow"),
        "features": settings.get("features"),
        "foreground": foreground,
    }


def _differences(first: dict[str, object], other: dict[str, object]) -> list[str]:
    """List the settings (section.name) whose values differ between two runs."""
    found = []
    for section in first:
        a, b = first[section] or {}, other[section] or {}
        found += [f"{section}.{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    return found


def _read_table(run: Path) -> pd.DataFrame:
    """Read one run's per-FOV table with metadata as text."""
    text = {c: str for c in METADATA_COLUMNS}
    table = pd.read_csv(
        run / "features" / "features_per_fov.csv", dtype=text, keep_default_na=False, na_values=[""]
    )
    table.insert(1, "run", run.name)
    return table


def load_runs(run_dirs: list[Path], shared_repeat_labels: bool = False) -> FeatureSet:
    """Load and combine ``features/features_per_fov.csv`` of several run folders.

    Parameters
    ----------
    run_dirs
        Run folders written by the pipeline.
    shared_repeat_labels
        False (default): a biological-repeat label identifies a repeat only within its run
        (``repeat_id = <run>/<label>``), so ``r1`` of two runs counts as two repeats. True:
        the same label in different runs is the same biological repeat (for example the
        control and treatment of one experiment day processed as separate runs).

    Returns
    -------
    FeatureSet
        Combined table (metadata as text, plus ``repeat_id``) and the common dictionary.

    Raises
    ------
    InputError
        When a run lacks its tables or manifest, units, features or result-affecting
        settings differ between runs, or a ``fov_uid`` appears twice.
    """
    runs = sorted(Path(r) for r in run_dirs)
    if not runs:
        raise InputError("No run folder was given.")
    tables, dictionary, reference = [], None, None
    for run in runs:
        dict_path = run / "features" / "feature_dictionary.json"
        if not (run / "features" / "features_per_fov.csv").is_file() or not dict_path.is_file():
            raise InputError(f"{run} has no feature tables; extract features first.")
        info = json.loads(dict_path.read_text(encoding="utf-8"))
        settings = comparable_settings(run)
        if dictionary is None:
            dictionary, reference = info, settings
        else:
            names = [d["name"] for d in dictionary["fov_features"]]
            if info["units"] != dictionary["units"] or names != [
                d["name"] for d in info["fov_features"]
            ]:
                raise InputError(
                    f"{run} uses different units or features ({info['units']}) "
                    f"from {runs[0]} ({dictionary['units']}); runs cannot be "
                    "combined."
                )
            changed = _differences(reference, settings)
            if changed:
                raise InputError(
                    f"{run} was analysed with different settings from {runs[0]} "
                    f"({', '.join(changed)}); its features are not comparable. "
                    "Re-extract the features with the same settings."
                )
        tables.append(_read_table(run))
    combined = pd.concat(tables, ignore_index=True)
    duplicated = combined["fov_uid"][combined["fov_uid"].duplicated()].unique()
    if len(duplicated):
        raise InputError("The same field of view appears in several runs: " + ", ".join(duplicated))
    combined.insert(
        2,
        "repeat_id",
        combined["biological_repeat"]
        if shared_repeat_labels
        else combined["run"] + "/" + combined["biological_repeat"],
    )
    defs = [FeatureDef(**d) for d in dictionary["fov_features"]]
    return FeatureSet(combined, defs, dictionary["units"], [r.as_posix() for r in runs])


def metadata_columns(table: pd.DataFrame) -> list[str]:
    """Return the identification columns of a combined table (never PCA inputs)."""
    columns = ("run", "repeat_id", *METADATA_COLUMNS, "undefined_features")
    return [c for c in columns if c in table.columns]


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
    comparison: tuple[pd.DataFrame, pd.DataFrame] | None = None,
    comparison_settings: ComparisonSettings | None = None,
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
        Optional ``(tests, per_repeat)`` from :func:`compare_conditions`.
    comparison_settings
        The settings of that comparison (recorded).
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
        write_csv(out_dir / "condition_tests.csv", comparison[0])
        write_csv(out_dir / "condition_tests_per_repeat.csv", comparison[1])
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
            "comparison_settings": to_record(comparison_settings) if comparison_settings else None,
            "comparison_rules": "MorphoCoverage (docs/morphobricks.md): FOV as observation",
        },
    )


def compare_conditions(
    features: FeatureSet, settings: ComparisonSettings
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare every condition with the control (MorphoCoverage rules, FOV as observation)."""
    return compare_tables(features.table, features.fov_defs, settings)
