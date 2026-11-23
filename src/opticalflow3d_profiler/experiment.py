"""Experimental metadata: conditions, replicates and stable field-of-view identities.

A field of view is identified as in every MorphoBricks table by ``condition``,
``biological_repeat``, ``technical_repeat`` and ``position_id``. The table comes from a
MorphoBricks experiment folder (:func:`~opticalflow3d_profiler.discovery.discover_experiment`:
labels from the folder names, ``position_id`` from the image name). Each field of view also
gets a deterministic, collision-safe ``fov_uid`` (its folder name in the run).
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
    for column in IDENTITY_COLUMNS:  # checked as given: outer spaces are refused, never trimmed
        for value in table[column]:
            if isinstance(value, str) and value.strip():
                check_identity_text(value, column, "metadata table")
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
