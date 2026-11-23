"""Run the unchanged upstream ``calc_flow3D`` over a movie, one time window at a time.

The output folder of one field of view holds the upstream file layout
(``<name>_vx_t0003.tiff`` ...; the number is the source time point) and a
``flow_manifest.json`` with the identity of the inputs, the parameters, the upstream
commit and the SHA-256 of every output file. Results are written into a temporary folder
and published with one rename, so an interrupted run leaves no half-written result.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from . import __version__
from ._upstream import UPSTREAM_COMMIT, UPSTREAM_FILE_SHA256, UPSTREAM_REPOSITORY
from .brightness import (
    brightness_change,
    equalise_window,
    match_histograms_window,
    window_means,
)
from .config import FlowParameters, ImageSpec, to_record
from .image_io import ImageHeader, dimensions, file_identity, read_frames, validate_image
from .progress import Tracker
from .validation import (
    InputError,
    check_time_and_depth,
    output_frame_map,
    raise_for_errors,
    resolve_flow_mode,
)

COMPONENTS = ("vx", "vy", "vz", "rel")
MANIFEST_NAME = "flow_manifest.json"
BYTES_PER_VOXEL_PEAK = 288
"""Peak working memory of upstream ``calc_flow3D`` per voxel of one Z-stack.

Measured with ``tracemalloc`` on 11x128x128 and 11x256x256 stacks with the default
parameters (both 288 bytes per voxel); the input window comes on top.
"""
SECONDS_PER_VOXEL = 2.3e-6
"""Rough time per voxel and output frame.

Measured: 83.5 s for one 7x11x1840x1840 uint16 window on a 4-vCPU cloud VM (peak RSS
11.35 GB against an estimate of 11.25 GB), ``tools/benchmark_flow.py``.
"""


@dataclass(frozen=True)
class ResourceEstimate:
    """Memory and disk needed for one field of view, and what is available.

    Attributes
    ----------
    peak_ram_bytes
        Estimated peak memory of one upstream call plus its input window.
    available_ram_bytes
        Currently available memory, or ``None`` when the system does not tell.
    output_bytes
        Size of all saved velocity and reliability files.
    free_disk_bytes
        Free space where the outputs go.
    n_outputs
        Number of optical-flow outputs.
    seconds
        Rough processing time.
    """

    peak_ram_bytes: int
    available_ram_bytes: int | None
    output_bytes: int
    free_disk_bytes: int
    n_outputs: int
    seconds: float

    def warnings(self) -> list[str]:
        """Return plain-language warnings about insufficient resources."""
        found = []
        if self.available_ram_bytes is not None and self.peak_ram_bytes > self.available_ram_bytes:
            found.append(
                f"About {self.peak_ram_bytes / 1e9:.1f} GB of memory is needed but only "
                f"{self.available_ram_bytes / 1e9:.1f} GB is available; the calculation "
                "will probably fail. Close other programs or use a computer with "
                "more memory. Images are never downsampled automatically."
            )
        if self.output_bytes > self.free_disk_bytes:
            found.append(
                f"The outputs need {self.output_bytes / 1e9:.1f} GB but only "
                f"{self.free_disk_bytes / 1e9:.1f} GB of disk is free."
            )
        return found


def available_memory() -> int | None:
    """Return the available physical memory in bytes, or ``None`` if unknown."""
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None


def estimate_resources(
    dims: dict[str, int], itemsize: int, params: FlowParameters, output_dir: Path
) -> ResourceEstimate:
    """Estimate memory, disk and time for one field of view.

    Parameters
    ----------
    dims
        Size of each axis (``T``, ``Z``, ``Y``, ``X``).
    itemsize
        Bytes per input pixel.
    params
        Upstream parameters.
    output_dir
        Where outputs will be written (its nearest existing parent is measured).

    Returns
    -------
    ResourceEstimate
        The estimate.
    """
    voxels = dims["Z"] * dims["Y"] * dims["X"]
    n_out = len(output_frame_map(dims["T"], params))
    out_item = np.dtype(params.output_dtype).itemsize
    existing = Path(output_dir)
    while not existing.exists():
        existing = existing.parent
    return ResourceEstimate(
        peak_ram_bytes=voxels * (BYTES_PER_VOXEL_PEAK + params.window_length * itemsize),
        available_ram_bytes=available_memory(),
        output_bytes=n_out * voxels * (3 * out_item + 4),
        free_disk_bytes=shutil.disk_usage(existing).free,
        n_outputs=n_out,
        seconds=n_out * voxels * SECONDS_PER_VOXEL,
    )


def upstream_identity() -> dict[str, str]:
    """Return the identity of the vendored upstream code, after checking its hash.

    Returns
    -------
    dict
        Repository, commit and file SHA-256.

    Raises
    ------
    RuntimeError
        When the vendored ``calc_flow.py`` differs from the pinned file.
    """
    path = Path(__file__).parent / "_upstream" / "calc_flow.py"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != UPSTREAM_FILE_SHA256:
        raise RuntimeError(
            "The vendored OpticalFlow3D file has been modified "
            f"(SHA-256 {digest}); reinstall the application."
        )
    return {
        "repository": UPSTREAM_REPOSITORY,
        "commit": UPSTREAM_COMMIT,
        "calc_flow_sha256": digest,
    }


def flow_identity(
    spec: ImageSpec, header: ImageHeader, params: FlowParameters, source: dict[str, Any]
) -> dict[str, Any]:
    """Return everything an optical-flow result depends on.

    Parameters
    ----------
    spec, header
        Confirmed input and its header.
    params
        Upstream parameters (including output precision).
    source
        :func:`~opticalflow3d_profiler.image_io.file_identity` of the input.

    Returns
    -------
    dict
        Input content hash, confirmed axes, dimensions, parameters, upstream
        identity and the output-to-source frame map. Calibration is not part of it: it
        does not change the saved velocities, which stay in voxels per frame.
    """
    dims = dimensions(spec, header)
    return {
        "source": {"sha256": source["sha256"], "size_bytes": source["size_bytes"]},
        "axes": spec.axes.upper(),
        "dimensions": dims,
        "dtype": header.dtype,
        "parameters": to_record(params),
        "upstream": upstream_identity(),
        "frame_map": output_frame_map(dims["T"], params),
    }


def identity_key(identity: dict[str, Any]) -> str:
    """Return a SHA-256 of the canonical JSON of an identity mapping."""
    text = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_frame(window: np.ndarray, params: FlowParameters) -> dict[str, np.ndarray]:
    """Run upstream ``calc_flow3D`` (or ``calc_flow2D`` per Z slice) on one TZYX window.

    Parameters
    ----------
    window
        ``window_length`` time points of Z-stacks, in the file's pixel type.
    params
        Upstream parameters.

    Returns
    -------
    dict
        ``vx``, ``vy``, ``vz`` (pixels/frame, slices/frame) and ``rel``, as upstream
        returns them; velocities are cast to ``params.output_dtype``. In ``xy_per_slice``
        mode there is no ``vz``: each slice's ``vx``, ``vy`` and ``rel`` come from
        ``calc_flow2D`` and are stacked along Z.
    """
    from ._upstream.calc_flow import calc_flow2D, calc_flow3D  # noqa: PLC0415 (heavy)

    dtype = np.dtype(params.output_dtype)
    sig = (params.xyz_sig, params.t_sig, params.w_sig)
    try:
        if params.mode == "xy_per_slice":
            slices = [calc_flow2D(window[:, z], *sig) for z in range(window.shape[1])]
            return {
                "vx": np.stack([s[0] for s in slices]).astype(dtype, copy=False),
                "vy": np.stack([s[1] for s in slices]).astype(dtype, copy=False),
                "rel": np.stack([s[2] for s in slices]),
            }
        if params.mode != "xyz":
            raise InputError(f"Flow mode '{params.mode}' must be resolved before running.")
        vx, vy, vz, rel = calc_flow3D(window, *sig)
    except SystemExit as error:  # upstream reports input errors with sys.exit
        raise InputError(f"OpticalFlow3D refused the input: {error}") from error
    return {
        "vx": vx.astype(dtype, copy=False),
        "vy": vy.astype(dtype, copy=False),
        "vz": vz.astype(dtype, copy=False),
        "rel": rel,
    }


def flow_window(window: np.ndarray, params: FlowParameters) -> tuple[dict, dict[str, object]]:
    """Measure the window's brightness change, equalise it if asked, and run upstream.

    Returns
    -------
    tuple
        The upstream outputs (:func:`compute_frame`) and the brightness record of the
        output: frame means, relative change per frame and the equalisation factors
        (``None`` without equalisation).
    """
    means = window_means(window)
    record: dict[str, object] = {
        "window_mean_intensity": [float(m) for m in means],
        "brightness_change_per_frame": brightness_change(means),
        "equalisation_factors": None,
    }
    if params.brightness_equalisation == "global_mean":
        window, record["equalisation_factors"] = equalise_window(window, means)
    elif params.brightness_equalisation == "histogram_match":
        window = match_histograms_window(window)
        record["histogram_matched_to_frame"] = len(means) // 2
    return compute_frame(window, params), record


def _write_tiff_hashed(path: Path, data: np.ndarray) -> str:
    """Write one float TIFF as upstream does and return its SHA-256."""
    tifffile.imwrite(path, data, photometric="minisblack")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_flow(
    spec: ImageSpec,
    header: ImageHeader,
    params: FlowParameters,
    out_dir: Path,
    name: str,
    progress: Callable[[str], None] | None = None,
    tracker: Tracker | None = None,
) -> dict[str, Any]:
    """Calculate and save optical flow for one field of view.

    Parameters
    ----------
    spec, header
        Confirmed input and its header (validated here).
    params
        Upstream parameters.
    out_dir
        Folder to create for this field of view; it must not exist yet.
    name
        File-name prefix of the outputs (the field-of-view identifier).
    progress
        Optional callback receiving one line of text per step.
    tracker
        Optional progress display: one step per optical-flow time window.

    Returns
    -------
    dict
        The flow manifest that was written.

    Raises
    ------
    InputError
        For invalid inputs, or when ``out_dir`` already exists.
    """
    report = progress or (lambda _line: None)
    params = resolve_flow_mode(params, spec.calibration)
    validate_image(spec, header)
    dims = dimensions(spec, header)
    raise_for_errors(check_time_and_depth(dims["T"], dims["Z"], params))
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise InputError(f"{out_dir} already exists; results are never overwritten.")
    report(f"Hashing {spec.path.name} (source identity)...")
    source = file_identity(spec.path)
    identity = flow_identity(spec, header, params, source)
    partial = out_dir.with_name(out_dir.name + f".partial-{os.getpid()}")
    partial.mkdir(parents=True)
    outputs = []
    started = time.monotonic()
    stage = (tracker or Tracker()).stage(
        f"Optical flow {name}", len(identity["frame_map"]), nested=True
    )
    for index, t in enumerate(identity["frame_map"]):
        half = params.half_window
        window = read_frames(spec, header, list(range(t - half, t + half + 1)))
        frame, brightness = flow_window(window, params)
        del window
        record = {"output_index": index, "source_frame": t, "files": {}, **brightness}
        for component in frame:
            file_name = f"{name}_{component}_t{t:04d}.tiff"
            record["files"][component] = {
                "name": file_name,
                "dtype": str(frame[component].dtype),
                "sha256": _write_tiff_hashed(partial / file_name, frame[component]),
            }
        outputs.append(record)
        del frame
        report(f"Source frame {t}: done ({time.monotonic() - started:.0f} s elapsed).")
        stage.update(f"time point {t}")
    stage.close()
    manifest = {
        "kind": "opticalflow3d_profiler.flow",
        "format_version": 1,
        "name": name,
        "identity": identity,
        "identity_key": identity_key(identity),
        "source_file": source["name"],
        "outputs": outputs,
        "velocity_units": {"vx": "pixel/frame", "vy": "pixel/frame", "vz": "slice/frame"},
        "reliability": "smallest eigenvalue of the Lucas-Kanade structure tensor (upstream)",
        "application_version": __version__,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "seconds": round(time.monotonic() - started, 3),
    }
    (partial / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(partial, out_dir)
    return manifest
