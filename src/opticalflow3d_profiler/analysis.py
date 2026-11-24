"""Load and combine the per-FOV feature tables of one or more runs (I/O).

Several runs (experiments) can be combined only when their feature dictionaries agree on
units and speed mode, so that a column means the same thing in every row.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .experiment import METADATA_COLUMNS
from .feature_dictionary import FeatureDef
from .naming import feature_key
from .results import definitions_sha256
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
    """Return a label per run: its folder name and a hash of its resolved full path.

    Every label carries the hash, not only colliding ones, so one run's label can never equal
    another run's folder name (``run-1`` and a folder named ``run-1-954d642f``: re-validation
    R4), and the same run gets the same label whatever other runs are loaded. The labels are
    checked to be unique.

    Raises
    ------
    InputError
        When two runs get one label (the same folder listed twice).
    """
    labels: dict[Path, str] = {}
    seen: dict[str, Path] = {}
    for run in runs:  # every entry, so a folder listed twice is refused, not merged
        resolved = str(Path(run).resolve())  # a symbolic link to a run is the same run
        label = f"{Path(run).name}-{hashlib.sha256(resolved.encode('utf-8')).hexdigest()[:16]}"
        for key in (label, resolved):
            if key in seen:
                raise InputError(f"{seen[key]} and {run} are the same run folder; load it once.")
            seen[key] = run
        labels[run] = label
    return labels


def _read_table(run: Path, label: str) -> pd.DataFrame:
    """Read one run's per-FOV table with metadata as text (duplicate headers refused)."""
    path = run / "features" / "features_per_fov.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle), [])
    twice = sorted({c for c in header if header.count(c) > 1})
    if twice:
        raise InputError(f"{path} has repeated column names: {', '.join(twice)}.")
    text = {c: str for c in METADATA_COLUMNS}
    table = pd.read_csv(path, dtype=text, keep_default_na=False, na_values=[""])
    table.insert(1, "run", label)
    return table


def _check_dictionary(run: Path, info: dict, several: bool) -> None:
    """Refuse a feature dictionary that describes a column twice.

    When runs are combined, also refuse one without the identity of its feature definitions
    and code.
    """
    names = [d["name"] for d in info.get("fov_features", [])]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise InputError(f"{run} describes these features twice: {', '.join(twice)}.")
    recorded = info.get("feature_implementation")
    if recorded is not None:
        actual = definitions_sha256(info.get("frame_features", []) + info.get("fov_features", []))
        if recorded.get("definitions_sha256") != actual:
            raise InputError(
                f"{run}: the feature definitions in feature_dictionary.json do not match their "
                "recorded hash (the file was edited after the run); its features cannot be "
                "trusted or combined."
            )
    if several and recorded is None:
        raise InputError(
            f"{run} was extracted before runs recorded the identity of their feature definitions "
            "and code, so it cannot be shown to measure the same thing as the other runs. "
            "Re-extract its features with this version (a new run with reuse_from reuses its "
            "verified optical flow)."
        )


def _check_same_features(run: Path, first: Path, info: dict, reference: dict) -> None:
    """Refuse two runs whose units, feature columns, definitions or feature code differ."""
    if info["units"] != reference["units"]:
        raise InputError(
            f"{run} uses other units ({info['units']}) than {first} "
            f"({reference['units']}); runs cannot be combined."
        )
    names = [d["name"] for d in reference["fov_features"]]
    other = [d["name"] for d in info["fov_features"]]
    if names != other:
        only = sorted(set(names) ^ set(other))[:6]
        raise InputError(
            f"{run} has other feature columns than {first} (for example "
            f"{', '.join(only) or 'the same names in another order'}): another "
            "speed mode or object-set name; runs cannot be combined."
        )
    mine, theirs = info["feature_implementation"], reference["feature_implementation"]
    keys = ("definitions_sha256", "code_sha256", "normalization")
    differ = [k for k in keys if mine.get(k) != theirs.get(k)]
    if differ:
        what = {
            "definitions_sha256": "feature definitions",
            "code_sha256": "feature code",
            "normalization": "normalization code",
        }
        raise InputError(
            f"{run} and {first} were computed with other {' and '.join(what[k] for k in differ)} "
            "(another profiler version): columns with one name may not measure the same thing, "
            "so the runs cannot be combined. Re-extract the features of every run with one "
            "version (new runs with reuse_from reuse their verified optical flow)."
        )


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
        _check_dictionary(run, info, several=len(runs) > 1)
        settings = comparable_settings(run)
        if dictionary is None:
            dictionary, reference = info, settings
        else:
            _check_same_features(run, runs[0], info, dictionary)
            changed = _differences(reference, settings)
            if changed:
                raise InputError(
                    f"{run} was analysed with different settings from {runs[0]} "
                    f"({', '.join(changed)}); its features are not comparable. "
                    "Re-extract the features with the same settings."
                )
        tables.append(_read_table(run, labels[run]))
    combined = pd.concat(tables, ignore_index=True)
    keys = [feature_key(c) for c in combined.columns]
    repeated = sorted({k for k in keys if keys.count(k) > 1})
    if repeated:
        raise InputError(
            "Several columns share a feature key (two object sets in one table): "
            + ", ".join(repeated)
            + ". Combine runs extracted with the same foreground name."
        )
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
