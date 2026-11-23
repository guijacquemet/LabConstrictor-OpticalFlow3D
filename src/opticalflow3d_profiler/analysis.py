"""Load and combine the per-FOV feature tables of one or more runs (I/O).

Several runs (experiments) can be combined only when their feature dictionaries agree on
units and speed mode, so that a column means the same thing in every row.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .experiment import METADATA_COLUMNS
from .feature_dictionary import FeatureDef
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
    windows, angular thresholds) and the foreground rule. The calibration values are not
    included: a different pixel size is converted to the same physical unit (units are
    checked separately).

    Raises
    ------
    InputError
        When the run has no manifest with settings.
    """
    path = Path(run) / "run_manifest.json"
    if not path.is_file():
        raise InputError(f"{run} has no run_manifest.json; its settings cannot be checked.")
    settings = json.loads(path.read_text(encoding="utf-8")).get("settings", {})
    foreground = dict(settings.get("foreground", {}))
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


def run_labels(runs: list[Path]) -> dict[Path, str]:
    """Return a label per run: its folder name, made unique with a hash of its full path.

    Two runs with the same folder name in different places (``/batchA/run-1`` and
    ``/batchB/run-1``) get different labels, so their repeats are never merged by accident.
    """
    names = [r.name for r in runs]
    labels = {}
    for run in runs:
        if names.count(run.name) == 1:
            labels[run] = run.name
        else:
            digest = hashlib.sha256(str(run.resolve()).encode("utf-8")).hexdigest()[:8]
            labels[run] = f"{run.name}-{digest}"
    return labels


def _read_table(run: Path, label: str) -> pd.DataFrame:
    """Read one run's per-FOV table with metadata as text."""
    text = {c: str for c in METADATA_COLUMNS}
    table = pd.read_csv(
        run / "features" / "features_per_fov.csv", dtype=text, keep_default_na=False, na_values=[""]
    )
    table.insert(1, "run", label)
    return table


def load_runs(run_dirs: list[Path], shared_repeat_labels: bool = False) -> FeatureSet:
    """Load and combine ``features/features_per_fov.csv`` of several run folders.

    Parameters
    ----------
    run_dirs
        Run folders written by the pipeline.
    shared_repeat_labels
        False (default): with several runs, a biological-repeat label identifies a repeat
        only within its run (``repeat_id = <run label>/<label>``, the run label unique even
        for runs with the same folder name: :func:`run_labels`), so ``r1`` of two runs counts
        as two repeats. True: the same label in different runs is the same biological repeat
        (for example the control and treatment of one experiment day processed as separate
        runs). With one run, ``repeat_id`` is the label itself.

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
    labels = run_labels(runs)
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
        tables.append(_read_table(run, labels[run]))
    combined = pd.concat(tables, ignore_index=True)
    duplicated = combined["fov_uid"][combined["fov_uid"].duplicated()].unique()
    if len(duplicated):
        raise InputError("The same field of view appears in several runs: " + ", ".join(duplicated))
    combined.insert(
        2,
        "repeat_id",
        combined["biological_repeat"]
        if shared_repeat_labels or len(runs) == 1
        else combined["run"] + "/" + combined["biological_repeat"],
    )
    defs = [FeatureDef(**d) for d in dictionary["fov_features"]]
    return FeatureSet(combined, defs, dictionary["units"], [r.as_posix() for r in runs])
