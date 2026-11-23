"""Experimental metadata: conditions, replicates and stable field-of-view identities.

A field of view is identified as in every MorphoBricks table by ``condition``,
``biological_repeat``, ``technical_repeat`` and ``position_id``. The table comes either from
a MorphoBricks experiment folder (:func:`~opticalflow3d_profiler.discovery.discover_experiment`,
labels from the folder names) or from a metadata CSV with the same columns and
``image_path``; labels are never parsed from file names. Each field of view also gets a
deterministic, collision-safe ``fov_uid`` (its folder name in the run).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

from .discovery import FOV_KEY, check_identity_text, discover_experiment
from .validation import InputError

IDENTITY_COLUMNS = FOV_KEY
REQUIRED_COLUMNS = (*FOV_KEY, "image_path")
OPTIONAL_COLUMNS = ("source_relative_path",)
METADATA_COLUMNS = ("fov_uid", *REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)


def fov_uid(record: dict[str, str]) -> str:
    """Return the deterministic identifier of one field of view.

    Parameters
    ----------
    record
        Values of :data:`IDENTITY_COLUMNS`.

    Returns
    -------
    str
        ``<readable slug>-<8 hex digits>``; the hash covers the exact values, so two
        records that differ only in characters removed from the slug still differ.
    """
    values = [str(record[c]).strip() for c in IDENTITY_COLUMNS]
    slug = "_".join(re.sub(r"[^A-Za-z0-9.-]+", "-", v).strip("-") for v in values)[:80]
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def validate_metadata(table: pd.DataFrame) -> pd.DataFrame:
    """Validate an experimental metadata table and add ``fov_uid``.

    Parameters
    ----------
    table
        One row per field of view with :data:`REQUIRED_COLUMNS` (strings).

    Returns
    -------
    pandas.DataFrame
        A copy with ``fov_uid`` first, sorted by ``fov_uid`` (deterministic order).

    Raises
    ------
    InputError
        For missing columns, empty values, duplicate identities or duplicate inputs.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in table.columns]
    if missing:
        raise InputError(f"The metadata table lacks the columns: {', '.join(missing)}.")
    table = table.copy()
    for column in REQUIRED_COLUMNS:
        table[column] = table[column].astype("string").str.strip()
        empty = table[column].isna() | (table[column] == "")
        if empty.any():
            rows = ", ".join(str(i + 2) for i in table.index[empty])
            raise InputError(f"Column '{column}' is empty in line(s) {rows} of the table.")
    for column in IDENTITY_COLUMNS:
        for value in table[column]:
            check_identity_text(str(value), column, "metadata table")
    duplicated = table.duplicated(list(IDENTITY_COLUMNS), keep=False)
    if duplicated.any():
        raise InputError(
            "Several rows have the same condition, repeats and position: "
            + ", ".join(table.loc[duplicated, "position_id"].unique())
        )
    paths = table["image_path"].duplicated(keep=False)
    if paths.any():
        raise InputError(
            "The same image file is listed more than once: "
            + ", ".join(table.loc[paths, "image_path"].unique())
        )
    table.insert(0, "fov_uid", [fov_uid(r) for r in table.to_dict("records")])
    if table["fov_uid"].duplicated().any():  # only possible with a hash collision
        raise InputError("Two fields of view received the same identifier.")
    keep = [c for c in METADATA_COLUMNS if c in table.columns]
    return table[keep].sort_values("fov_uid").reset_index(drop=True)


def read_metadata(path: Path) -> pd.DataFrame:
    """Read and validate a metadata CSV (all values read as text).

    Relative ``image_path`` values are resolved against the CSV's folder.

    Parameters
    ----------
    path
        CSV file with the :data:`REQUIRED_COLUMNS`.

    Returns
    -------
    pandas.DataFrame
        Validated table (see :func:`validate_metadata`).
    """
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "input_path" in table.columns and "image_path" not in table.columns:
        raise InputError("Rename the column 'input_path' to 'image_path' (MorphoBricks name).")
    base = Path(path).resolve().parent
    if "mask_path" in table.columns:
        raise InputError("Masks are not used; remove the 'mask_path' column.")
    for column in ("image_path",):
        if column in table.columns:
            table[column] = [
                (base / v).as_posix() if v.strip() and not Path(v).is_absolute() else v
                for v in table[column]
            ]
    return validate_metadata(table)


def read_experiment_folder(root: Path) -> pd.DataFrame:
    """Discover a MorphoBricks experiment folder and validate it as a metadata table.

    See :func:`~opticalflow3d_profiler.discovery.discover_experiment` for the layout rules.
    """
    return validate_metadata(discover_experiment(root))


def replicate_counts(table: pd.DataFrame) -> pd.DataFrame:
    """Return, per condition, the number of biological repeats and fields of view."""
    grouped = table.groupby("condition", sort=True)
    return pd.DataFrame(
        {
            "biological_repeats": grouped[
                "repeat_id" if "repeat_id" in table.columns else "biological_repeat"
            ].nunique(),
            "fields_of_view": grouped["fov_uid"].nunique(),
        }
    ).reset_index()


def repeat_column(table: pd.DataFrame) -> str:
    """Return the column identifying biological repeats (``repeat_id`` when present).

    ``repeat_id`` (written by :func:`~opticalflow3d_profiler.analysis.load_runs`, scoped to
    its run unless the labels are declared shared) takes precedence over the raw label.
    """
    return "repeat_id" if "repeat_id" in table.columns else "biological_repeat"
