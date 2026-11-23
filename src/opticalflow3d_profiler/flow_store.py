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


def _completeness(manifest: dict[str, Any]) -> list[str]:
    """List what is missing for every planned output to be present with all its components."""
    identity = manifest.get("identity", {})
    planned = identity.get("frame_map")
    outputs = manifest.get("outputs", [])
    found = [o.get("source_frame") for o in outputs]
    problems = []
    if planned is not None and found != list(planned):
        problems.append(f"The outputs cover source frames {found}, not the planned {planned}.")
    per_slice = identity.get("parameters", {}).get("mode") == "xy_per_slice"
    wanted = {"vx", "vy", "rel"} | (set() if per_slice else {"vz"})
    for output in outputs:
        if set(output.get("files", {})) != wanted:
            problems.append(
                f"Output {output.get('source_frame')} has the components "
                f"{sorted(output.get('files', {}))}, not {sorted(wanted)}."
            )
    return problems


def identity_changes(recorded: object, expected: object, path: str = "") -> list[str]:
    """Name every value that differs between two identities, as ``path: recorded → wanted``.

    Nested values are compared key by key, so a changed ``parameters.w_sig`` is named
    rather than ``parameters`` (re-validation M6); long values are not printed.
    """
    if isinstance(recorded, dict) and isinstance(expected, dict):
        return [
            change
            for key in sorted(set(recorded) | set(expected), key=str)
            for change in identity_changes(
                recorded.get(key, "absent"), expected.get(key, "absent"),
                f"{path}.{key}" if path else str(key),
            )
        ]  # fmt: skip
    if recorded == expected:
        return []
    shown = [repr(v) if len(repr(v)) <= 40 else "(long value)" for v in (recorded, expected)]
    return [f"{path or 'identity'}: {shown[0]} → {shown[1]}"]


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
        Empty when the manifest is consistent, every planned output (the identity's frame
        map, in order) is listed with all its components, every file exists with its
        recorded SHA-256 and, if given, the identity matches exactly.
    """
    try:
        manifest = read_manifest(folder)
    except (InputError, json.JSONDecodeError) as error:
        return [str(error)]
    problems = []
    if manifest.get("identity_key") != identity_key(manifest.get("identity", {})):
        problems.append("The manifest identity does not match its key.")
    if expected_identity is not None and manifest.get("identity") != expected_identity:
        changed = identity_changes(manifest.get("identity", {}), expected_identity)
        problems.append(f"Different inputs or settings: {'; '.join(changed)}.")
    problems += _completeness(manifest)
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
