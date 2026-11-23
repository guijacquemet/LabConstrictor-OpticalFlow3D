"""Describe an example image and check every image header of an experiment (I/O).

Headers only: no pixel is read here (as in MorphoBricks preprocessing's header scan). The
example image is drawn at random from the experiment, with the seed recorded, so the user
sees a typical field of view rather than always the first one.
"""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pandas as pd
from morphobricks_preprocessing import check_metadata

from .config import ImageSpec
from .image_io import ImageHeader, inspect_tiff, validate_image
from .validation import InputError


def pick_example(metadata: pd.DataFrame, seed: int | None = None) -> tuple[pd.Series, int]:
    """Return one random field of view of the metadata and the seed used."""
    seed = random.SystemRandom().randrange(2**31) if seed is None else seed
    index = random.Random(seed).randrange(len(metadata))
    return metadata.iloc[index], seed


def header_summary(header: ImageHeader, row: pd.Series | None = None) -> pd.DataFrame:
    """Return the header of one image as a two-column table (field, value)."""
    cal = header.calibration_suggestion

    def size(value: float | None, unit: str) -> str:
        return "not in the header" if value is None else f"{value:g} {unit}"

    rows = [
        ("file", header.path.name),
        ("format", header.format),
        ("shape", " × ".join(str(n) for n in header.shape)),
        (
            "axes (header)",
            header.header_axes + (" (not named: confirm)" if header.axes_ambiguous else ""),
        ),
        ("pixel type", header.dtype),
        ("image series", str(header.n_series)),
        ("file size", f"{header.file_size / 1e9:.2f} GB"),
        ("X pixel size", size(cal.pixel_size_x, "µm")),
        ("Y pixel size", size(cal.pixel_size_y, "µm")),
        ("Z spacing", size(cal.pixel_size_z, "µm")),
        ("frame interval", size(cal.frame_interval, "min")),
        ("calibration source", cal.source),
    ]
    if row is not None:
        labels = ("condition", "biological_repeat", "technical_repeat", "position_id")
        rows = [(k, str(row[k])) for k in labels] + rows
    rows += [("note", note) for note in header.notes]
    return pd.DataFrame(rows, columns=["field", "value"])


def check_headers(metadata: pd.DataFrame, axes: str) -> tuple[pd.DataFrame, list]:
    """Check every image of the experiment against the confirmed axes (headers only).

    Each image is checked with :func:`~opticalflow3d_profiler.image_io.validate_image`, and
    all readable headers together with MorphoBricks preprocessing's experiment-wide header
    checks, Z allowed (``check_metadata(files, allow_z=True)``, contract §20): unreadable
    files, several series, pixel types, axis arrangement and channel counts are errors;
    different sizes, plane counts and pixel sizes are warnings.

    Returns
    -------
    tuple
        One row per field of view (``image``, ``shape``, ``pixel type``, the header
        calibration and ``problem``, empty when the image can be processed), and the list of
        preprocessing's ``ValidationIssue`` objects.
    """
    rows, headers = [], []
    for record in metadata.to_dict("records"):
        where = str(record.get("source_relative_path") or Path(record["image_path"]).name)
        row = {
            "image": where,
            "shape": "",
            "pixel type": "",
            "header calibration": "",
            "problem": "",
        }
        try:
            header = inspect_tiff(Path(record["image_path"]))
            headers.append(replace(header.metadata, relative_path=where))
            validate_image(ImageSpec(header.path, axes), header)
            cal = header.calibration_suggestion
            row.update(
                shape=" × ".join(str(n) for n in header.shape),
                **{"pixel type": header.dtype},
                **{"header calibration": f"{cal.pixel_size_x}, {cal.pixel_size_z} µm; "
                   f"{cal.frame_interval} min"},
            )  # fmt: skip
        except InputError as error:
            row["problem"] = str(error)
        rows.append(row)
    return pd.DataFrame(rows), check_metadata(headers, allow_z=True)


def header_problems(table: pd.DataFrame, issues: list) -> list[str]:
    """Return the experiment-wide problems: invalid images and preprocessing's errors."""
    problems = [f"{r.image}: {r.problem}" for r in table.itertuples() if r.problem]
    return problems + [f"{i.code}: {i.message} {i.action}".strip() for i in issues if i.is_error]


def header_notes(table: pd.DataFrame, issues: list) -> list[str]:
    """Return differences worth a look: preprocessing's warnings and header calibrations."""
    readable = table[table["problem"] == ""]
    notes = [f"{i.code}: {i.message}" for i in issues if not i.is_error]
    if readable["header calibration"].nunique() > 1:
        notes.append(
            "Header calibrations differ between images; one confirmed calibration is used for "
            "the whole run (process different acquisition settings as separate runs)."
        )
    return notes
