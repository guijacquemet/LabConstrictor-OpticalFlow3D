"""Read saved optical-flow results and decide whether they may be reused (I/O).

Folders written by :func:`~opticalflow3d_profiler.flow_backend.run_flow` are read, after
their ``flow_manifest.json`` identity and file hashes are verified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from .flow_backend import MANIFEST_NAME, identity_key
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
        The flow manifest.
    """

    folder: Path
    name: str
    frames: tuple[FlowFrame, ...]
    manifest: dict[str, Any]


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
    return FlowResult(folder, manifest["name"], frames, manifest)
