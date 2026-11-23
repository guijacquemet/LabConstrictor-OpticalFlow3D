"""Experimental metadata: conditions, replicates and stable field-of-view identities (pure).

Conditions, biological and technical repeats come only from the metadata table, never
from file names. Each field of view gets a deterministic, collision-safe ``fov_uid``
built from all its identifying columns, so two conditions or repeats may reuse the same
``position_id``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

from .validation import InputError

REQUIRED_COLUMNS = (
    "sample_id",
    "position_id",
    "condition",
    "biological_repeat",
    "technical_repeat",
    "batch",
    "input_path",
)
OPTIONAL_COLUMNS = ("mask_path",)
IDENTITY_COLUMNS = (
    "condition",
    "biological_repeat",
    "technical_repeat",
    "sample_id",
    "position_id",
)
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
    duplicated = table.duplicated(list(IDENTITY_COLUMNS), keep=False)
    if duplicated.any():
        raise InputError(
            "Several rows have the same condition, repeats, sample and position: "
            + ", ".join(table.loc[duplicated, "sample_id"].unique())
        )
    paths = table["input_path"].duplicated(keep=False)
    if paths.any():
        raise InputError(
            "The same input file is listed more than once: "
            + ", ".join(table.loc[paths, "input_path"].unique())
        )
    table.insert(0, "fov_uid", [fov_uid(r) for r in table.to_dict("records")])
    if table["fov_uid"].duplicated().any():  # only possible with a hash collision
        raise InputError("Two fields of view received the same identifier.")
    keep = [c for c in METADATA_COLUMNS if c in table.columns]
    return table[keep].sort_values("fov_uid").reset_index(drop=True)


def read_metadata(path: Path) -> pd.DataFrame:
    """Read and validate a metadata CSV (all values read as text).

    Relative ``input_path`` and ``mask_path`` values are resolved against the CSV's folder.

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
    base = Path(path).resolve().parent
    for column in ("input_path", "mask_path"):
        if column in table.columns:
            table[column] = [
                (base / v).as_posix() if v.strip() and not Path(v).is_absolute() else v
                for v in table[column]
            ]
    return validate_metadata(table)


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
