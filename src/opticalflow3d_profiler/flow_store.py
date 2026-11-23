"""Read saved optical-flow results and decide whether they may be reused (I/O).

Two kinds of folders are read:

- folders written by :func:`~opticalflow3d_profiler.flow_backend.run_flow`, with a
  ``flow_manifest.json`` whose identity and file hashes can be verified;
- folders written by upstream ``process_flow`` (``<name>_parameters.csv`` and
  ``<name>_vx_tNNNN.tiff`` ...). Their inputs cannot be verified, so they are marked
  ``"external"`` everywhere they are used.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from .flow_backend import COMPONENTS, MANIFEST_NAME, identity_key
from .validation import InputError


@dataclass(frozen=True)
class FlowFrame:
    """One saved optical-flow output.

    Attributes
    ----------
    source_frame
        Source time point (0-based) of this output.
    paths
        File of each component (``vx``, ``vy``, ``vz``, ``rel``).
    """

    source_frame: int
    paths: dict[str, Path]

    def load(self) -> dict[str, np.ndarray]:
        """Read the four volumes, unchanged."""
        return {c: tifffile.imread(p) for c, p in self.paths.items()}


@dataclass(frozen=True)
class FlowResult:
    """A folder of optical-flow outputs.

    Attributes
    ----------
    folder
        The folder.
    name
        File-name prefix.
    frames
        Outputs in source-time order.
    manifest
        The flow manifest (or a description of an external upstream result).
    verified
        True only for profiler results whose identity and hashes were checked.
    """

    folder: Path
    name: str
    frames: tuple[FlowFrame, ...]
    manifest: dict[str, Any]
    verified: bool


def read_manifest(folder: Path) -> dict[str, Any]:
    """Return the flow manifest of a profiler result folder.

    Raises
    ------
    InputError
        When the folder has no manifest.
    """
    path = Path(folder) / MANIFEST_NAME
    if not path.is_file():
        raise InputError(f"{folder} has no {MANIFEST_NAME}; it is not a profiler result.")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_result(folder: Path, expected_identity: dict[str, Any] | None = None) -> list[str]:
    """List the reasons why a saved result cannot be trusted or reused.

    Parameters
    ----------
    folder
        Profiler result folder.
    expected_identity
        Identity the result must have (from
        :func:`~opticalflow3d_profiler.flow_backend.flow_identity`); ``None`` checks
        only the files against the manifest.

    Returns
    -------
    list of str
        Empty when the manifest is consistent, every file exists with its recorded
        SHA-256 and, if given, the identity matches exactly.
    """
    try:
        manifest = read_manifest(folder)
    except (InputError, json.JSONDecodeError) as error:
        return [str(error)]
    problems = []
    if manifest.get("identity_key") != identity_key(manifest.get("identity", {})):
        problems.append("The manifest identity does not match its key.")
    if expected_identity is not None and manifest.get("identity") != expected_identity:
        changed = sorted(
            k
            for k in set(expected_identity) | set(manifest.get("identity", {}))
            if expected_identity.get(k) != manifest["identity"].get(k)
        )
        problems.append(f"Different inputs or settings: {', '.join(changed)}.")
    for output in manifest.get("outputs", []):
        for info in output["files"].values():
            path = Path(folder) / info["name"]
            if not path.is_file():
                problems.append(f"Missing file {info['name']}.")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
                problems.append(f"{info['name']} has changed since it was written.")
    return problems


def open_result(folder: Path) -> FlowResult:
    """Open a profiler result folder after verifying its files.

    Raises
    ------
    InputError
        When verification fails.
    """
    folder = Path(folder)
    problems = verify_result(folder)
    if problems:
        raise InputError(f"{folder} cannot be used: " + " ".join(problems))
    manifest = read_manifest(folder)
    frames = tuple(
        FlowFrame(o["source_frame"], {c: folder / f["name"] for c, f in o["files"].items()})
        for o in manifest["outputs"]
    )
    return FlowResult(folder, manifest["name"], frames, manifest, verified=True)


def open_upstream_result(folder: Path, name: str) -> FlowResult:
    """Open a folder written by upstream ``process_flow`` (3D).

    Parameters
    ----------
    folder
        Folder holding ``<name>_parameters.csv`` and the ``_vx/_vy/_vz/_rel`` files.
    name
        The upstream ``imNameSave`` prefix.

    Returns
    -------
    FlowResult
        Marked ``verified=False``; the manifest records the upstream parameters and
        that the source image identity is unknown.

    Raises
    ------
    InputError
        When parameters or any component of a time point are missing.
    """
    folder = Path(folder)
    params_path = folder / f"{name}_parameters.csv"
    if not params_path.is_file():
        raise InputError(f"{params_path.name} was not found in {folder}.")
    with params_path.open(newline="", encoding="utf-8") as handle:
        params = next(csv.DictReader(handle))
    pattern = re.compile(re.escape(name) + r"_(vx|vy|vz|rel)_t(\d{4})\.tiff")
    found: dict[int, dict[str, Path]] = {}
    for path in sorted(folder.iterdir()):
        match = pattern.fullmatch(path.name)
        if match:
            found.setdefault(int(match.group(2)), {})[match.group(1)] = path
    incomplete = sorted(t for t, parts in found.items() if set(parts) != set(COMPONENTS))
    if not found or incomplete:
        raise InputError(
            f"Upstream result {name} is empty or incomplete (time points "
            f"{incomplete}); 3D results need vx, vy, vz and rel files."
        )
    frames = tuple(FlowFrame(t, found[t]) for t in sorted(found))
    manifest = {
        "kind": "upstream.process_flow",
        "name": name,
        "upstream_parameters": params,
        "source_identity": "unknown (external result, not verified)",
        "outputs": [{"source_frame": f.source_frame} for f in frames],
    }
    return FlowResult(folder, name, frames, manifest, verified=False)
