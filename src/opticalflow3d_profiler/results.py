"""Run folders, atomic file writing and provenance (I/O).

Layout of one run::

    <run>/run_manifest.json  experiments.csv  fovs.csv
    <run>/flow/<fov_uid>/    upstream-format velocity files + flow_manifest.json
    <run>/features/          features_per_frame.csv  features_per_fov.csv
                             feature_dictionary.json
    <run>/analysis/          PCA, comparisons and figures (written by the analysis step)
    <run>/logs/run.log

A run folder is never reused for a different run: :func:`create_run` refuses an existing,
non-empty folder.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

import pandas as pd

from . import __version__
from .validation import InputError

DEPENDENCIES = (
    "numpy",
    "scipy",
    "tifffile",
    "pandas",
    "scikit-learn",
    "matplotlib",
    "ipywidgets",
    "natsort",
)


def create_run(parent: Path, name: str | None = None) -> Path:
    """Create a new, empty run folder.

    Parameters
    ----------
    parent
        Folder that holds runs.
    name
        Run name; default is the UTC time ``run-YYYYmmdd-HHMMSS``.

    Returns
    -------
    pathlib.Path
        The created folder with ``flow``, ``features``, ``analysis`` and ``logs``.

    Raises
    ------
    InputError
        When the folder already exists and is not empty.
    """
    name = name or datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")
    run = Path(parent) / name
    if run.exists() and any(run.iterdir()):
        raise InputError(
            f"{run} already exists and is not empty; choose another run name. "
            "Existing results are never overwritten."
        )
    for sub in ("flow", "features", "analysis/figures", "logs"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    return run


def write_text_atomic(path: Path, text: str) -> None:
    """Write UTF-8 text through a temporary file and an atomic rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_json(path: Path, data: object) -> None:
    """Write JSON atomically (sorted keys are not imposed; floats at full precision)."""
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=True) + "\n")


def write_csv(path: Path, table: pd.DataFrame) -> None:
    """Write a CSV atomically, without the index; NaN is written as an empty cell."""
    write_text_atomic(path, table.to_csv(index=False, lineterminator="\n"))


def environment() -> dict[str, str]:
    """Return the application, Python, platform and dependency versions."""
    versions = {
        "opticalflow3d_profiler": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    for name in DEPENDENCIES:
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def now() -> str:
    """Return the current UTC time in ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def relative(path: Path, start: Path) -> str:
    """Return ``path`` relative to ``start`` with ``/`` when possible, else absolute."""
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError:  # different drives on Windows
        return Path(path).as_posix()
