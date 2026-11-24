"""Describe an example image and check every image header of an experiment (I/O).

Headers only: no pixel is read here (as in MorphoBricks preprocessing's header scan). The
example image is drawn at random from the experiment, with the seed recorded, so the user
sees a typical field of view rather than always the first one.
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

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


def check_headers(metadata: pd.DataFrame, axes: str) -> pd.DataFrame:
    """Check every image of the experiment against the confirmed axes (headers only).

    Returns
    -------
    pandas.DataFrame
        One row per field of view: ``position``, ``shape``, ``pixel type``, the header
        calibration and ``problem`` (empty when the image can be processed).
    """
    rows = []
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
            validate_image(ImageSpec(header.path, axes), header)
            cal = header.calibration_suggestion
            row.update(
                shape=" × ".join(str(n) for n in header.shape),
                **{"pixel type": header.dtype},
                **{"header calibration": f"X {cal.pixel_size_x}, Y {cal.pixel_size_y}, "
                   f"Z {cal.pixel_size_z} µm; {cal.frame_interval} min"},
            )  # fmt: skip
        except InputError as error:
            row["problem"] = str(error)
        rows.append(row)
    return pd.DataFrame(rows)


def header_problems(table: pd.DataFrame) -> list[str]:
    """Return the experiment-wide problems of :func:`check_headers` (empty when none).

    Unreadable or invalid images and mixed pixel types are problems (MorphoBricks refuses
    mixed types); different image sizes or header calibrations are reported as notes.
    """
    problems = [f"{r.image}: {r.problem}" for r in table.itertuples() if r.problem]
    readable = table[table["problem"] == ""]
    if readable["pixel type"].nunique() > 1:
        problems.append(
            "Images have different pixel types: " + ", ".join(readable["pixel type"].unique())
        )
    return problems


def header_notes(table: pd.DataFrame) -> list[str]:
    """Return differences worth a look: image sizes and header calibrations."""
    readable = table[table["problem"] == ""]
    notes = []
    if readable["shape"].nunique() > 1:
        notes.append(f"{readable['shape'].nunique()} different image sizes.")
    if readable["header calibration"].nunique() > 1:
        notes.append(
            "Header calibrations differ between images; one confirmed calibration is used for "
            "the whole run (process different acquisition settings as separate runs)."
        )
    return notes
