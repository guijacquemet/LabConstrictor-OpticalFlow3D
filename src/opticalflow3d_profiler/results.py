"""Run folders, atomic file writing and provenance (I/O).

Layout of one run::

    <run>/run_manifest.json  experiments.csv  fovs.csv
    <run>/flow/<fov_uid>/    upstream-format velocity files + flow_manifest.json
    <run>/features/          features_per_frame.csv  features_per_fov.csv
                             feature_dictionary.json
    <run>/analysis/          MorphoCoverage reports (written by the analysis step)
    <run>/logs/run.log

A run folder is never reused for a different run: :func:`create_run` refuses an existing,
non-empty folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
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
    "matplotlib",
    "ipywidgets",
    "natsort",
    "tqdm",
    "morphocoverage",
    "morphobricks-normalization",
    "umap-learn",
    "scikit-learn",
)


def distribution_identity(name: str) -> dict[str, str | None]:
    """Return an installed distribution's version and, from a git install, its commit."""
    try:
        dist = importlib_metadata.distribution(name)
    except importlib_metadata.PackageNotFoundError:
        return {"version": None, "commit": None}
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    return {"version": dist.version, "commit": direct.get("vcs_info", {}).get("commit_id")}


def contained(parent: Path, name: str, what: str) -> Path:
    """Return ``parent / name`` after checking that ``name`` is one plain folder name.

    A run or report name is a single path component: no separator, no ``..``, no absolute path,
    no leading or trailing space, and the resolved destination lies inside ``parent`` (also
    through a symbolic link), so an output folder can never be created elsewhere, for example
    inside the experiment folder (round-4 audit).

    Raises
    ------
    InputError
        For a name that is not one plain folder name or resolves outside ``parent``.
    """
    bad = (
        not name
        or name != name.strip()
        or name in (".", "..")
        or any(sep in name for sep in ("/", "\\", "\0"))
        or Path(name).is_absolute()
        or Path(name).drive != ""
    )
    if bad:
        raise InputError(
            f"The {what} {name!r} must be one plain folder name (no '/', '\\', '..' or outer "
            "spaces); outputs are only ever written inside their results folder."
        )
    target = Path(parent) / name
    if not target.resolve().is_relative_to(Path(parent).resolve()):
        raise InputError(f"The {what} {name!r} leads outside {parent}; choose another name.")
    return target


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
        When the name is not one plain folder name (:func:`contained`) or the folder already
        exists and is not empty.
    """
    name = name or datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")
    run = contained(Path(parent), name, "run name")
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


def write_json_new(path: Path, data: object) -> None:
    """Write JSON without ever replacing an existing file (round 4).

    The text goes to a unique temporary file that is then hard-linked to ``path``: atomic,
    and the link fails when ``path`` exists, so a file another writer published in the
    meantime (a run manifest, for example) is never replaced. On storage without hard links
    (some SMB, exFAT or FAT shares) the file is created exclusively instead
    (``O_CREAT | O_EXCL``): still never replacing a file, but written in place.

    Raises
    ------
    InputError
        When ``path`` already exists.
    """
    path = Path(path)
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=True) + "\n"
    handle, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
        try:
            os.link(tmp, path)
        except FileExistsError as error:
            raise InputError(
                f"{path} appeared while this run was writing; it is not replaced."
            ) from error
        except (OSError, AttributeError):  # no hard links on this storage
            _write_exclusive(path, text)
    finally:
        os.unlink(tmp)


def _write_exclusive(path: Path, text: str) -> None:
    """Create ``path`` exclusively and write ``text``; remove it if writing fails."""
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise InputError(
            f"{path} appeared while this run was writing; it is not replaced."
        ) from error
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)  # our own, just created, incomplete file
        raise


def write_csv(path: Path, table: pd.DataFrame) -> None:
    """Write a CSV atomically, without the index; NaN is written as an empty cell."""
    write_text_atomic(path, table.to_csv(index=False, lineterminator="\n"))


def environment() -> dict[str, str]:
    """Return the application, Python, platform and dependency versions (with git commits)."""
    versions = {
        "opticalflow3d_profiler": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    for name in DEPENDENCIES:
        found = distribution_identity(name)
        versions[name] = found["version"] or "not installed"
        if found["commit"]:  # a git install: the commit identifies the code exactly
            versions[name] += f" (git {found['commit']})"
    return versions


RUN_CLAIM = "run_started.json"


def claim_run(run_dir: Path) -> None:
    """Claim a run folder for one run, atomically, before anything is written in it.

    ``run_started.json`` is created exclusively (``O_CREAT | O_EXCL``), so two processes
    cannot both start a run in one folder, and a folder whose run was interrupted (claim but
    no manifest) or finished is never entered again (re-validation C3).

    Raises
    ------
    InputError
        When the folder has been claimed or holds a run manifest.
    """
    claim = Path(run_dir) / RUN_CLAIM
    manifest = Path(run_dir) / "run_manifest.json"
    handle = None
    if not manifest.exists():  # a finished run (also one older than the claim) is never touched
        try:
            handle = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            handle = None
    if handle is not None and manifest.exists():  # a manifest appeared meanwhile: undo our claim
        os.close(handle)
        claim.unlink()
        handle = None
    if handle is None:
        raise InputError(
            f"{run_dir} already holds a run, finished, running or interrupted ({RUN_CLAIM} or "
            "run_manifest.json); a run is never run twice or overwritten. Create a new run, "
            "with reuse_from to reuse its verified optical flow."
        )
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump({"started": now(), "pid": os.getpid(), "host": platform.node()}, out)


def implementation_identity() -> dict[str, object]:
    """Return the profiler version and a SHA-256 of every one of its Python modules.

    Recorded in every run manifest so that two numerical implementations never share an
    identity, even without a version bump (re-validation): ``source_sha256`` covers the
    modules' paths and bytes in sorted order.
    """
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    files = sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts)
    for path in files:
        digest.update(path.relative_to(package).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return {"version": __version__, "modules": len(files), "source_sha256": digest.hexdigest()}


FEATURE_MODULES = (
    "flow_features.py",
    "temporal_features.py",
    "foreground.py",
    "brightness.py",
    "feature_dictionary.py",
    "pipeline.py",
    "flow_backend.py",
    "image_io.py",
    "config.py",
    "naming.py",
    "_upstream/calc_flow.py",
    "_upstream/__init__.py",
)
"""The modules whose code decides feature values: the velocity generation (the vendored
OpticalFlow3D code, its adapter and the image reading), masks, per-frame features, time
averages, brightness QC, definitions, settings and column names (round 4: the velocity path
was missing)."""


def feature_implementation(records: list[dict[str, str]]) -> dict[str, str]:
    """Return the identity of a run's features: their definitions and the code computing them.

    ``definitions_sha256`` covers every definition written to ``feature_dictionary.json``
    (name, formula, unit, use, undefined condition); ``code_sha256`` covers
    :data:`FEATURE_MODULES`. Runs are combined only when both are equal (round 3 of the audit:
    the old binned and the new kernel entropy shared one column name and unit).
    """
    package = Path(__file__).resolve().parent
    code = hashlib.sha256()
    for name in FEATURE_MODULES:
        code.update(name.encode("utf-8") + b"\0" + (package / name).read_bytes() + b"\0")
    from .brightness import implementation_identity as normalization_identity

    return {
        "definitions_sha256": definitions_sha256(records),
        "code_sha256": code.hexdigest(),
        "normalization": json.dumps(normalization_identity(), sort_keys=True),
    }


def definitions_sha256(records: list[dict[str, str]]) -> str:
    """Return the SHA-256 of feature definitions, independent of key order."""
    text = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now() -> str:
    """Return the current UTC time in ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def relative(path: Path, start: Path) -> str:
    """Return ``path`` relative to ``start`` with ``/`` when possible, else absolute."""
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError:  # different drives on Windows
        return Path(path).as_posix()
