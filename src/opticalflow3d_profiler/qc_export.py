"""Save quality-control figures of every field of view of a run (orchestration).

For visual confirmation of each intermediate step, ``<run>/qc/<fov_uid>/`` receives:

- ``input_montage_z<z>.png``: the analysed channel at one Z slice for every time point;
- ``foreground_t<t>.png``: the foreground outline at each optical-flow time point (when
  a foreground is defined);
- ``flow_t<t>.png``: image with flow vectors (unreliable vectors grey), XY speed and
  reliability at each optical-flow time point;
- ``features_over_time.png``: per-frame features of the field of view.

``<run>/qc/feature_histograms.png`` shows the per-frame features of the whole run. The
figures only display saved results; they compute no new numbers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import figures
from .config import ImageSpec
from .flow_features import reliability_mask
from .flow_store import open_result
from .image_io import dimensions, inspect_tiff, read_frames
from .naming import find_column
from .pipeline import RunSettings, foreground_reader
from .progress import Tracker
from .validation import InputError

QC_DPI = 120


def flow_folder(run_dir: Path, status: dict[str, object]) -> Path:
    """Return the optical-flow folder of a field of view from its ``fovs.csv`` row."""
    origin = str(status.get("flow_origin", ""))
    if origin.startswith("reused: "):
        return Path(origin.removeprefix("reused: "))
    return Path(run_dir) / "flow" / str(status["fov_uid"])


def _plotted(frames: pd.DataFrame) -> list[str]:
    """Return the speed-median, coherence and reliable-fraction columns of a table."""
    speed = find_column(frames.columns, "speed_3d_median") or find_column(
        frames.columns, "speed_xy_median"
    )
    coherence = find_column(frames.columns, "coherence_xy_global")
    return [c for c in (speed, coherence, "qc_reliable_fraction") if c in frames.columns]


def export_fov(
    run_dir: Path, status: dict[str, object], settings: RunSettings, z: int | None = None
) -> list[Path]:
    """Save the QC figures of one field of view.

    Parameters
    ----------
    run_dir
        Run folder.
    status
        The field of view's row of ``fovs.csv`` (metadata and status columns).
    settings
        Run settings (axes, channel, foreground and reliability).
    z
        Z slice to show; default is the middle slice.

    Returns
    -------
    list of pathlib.Path
        The written figures.
    """
    uid = str(status["fov_uid"])
    out = Path(run_dir) / "qc" / uid
    spec = ImageSpec(Path(str(status["image_path"])), settings.axes, settings.channel)
    header = inspect_tiff(spec.path)
    dims = dimensions(spec, header)
    z = dims["Z"] // 2 if z is None else z
    written = [out / f"input_montage_z{z}.png"]
    planes = [read_frames(spec, header, [t])[0][z] for t in range(dims["T"])]
    figures.save(
        figures.time_montage(
            planes, [f"t={t}" for t in range(dims["T"])], f"{uid}: input, Z slice {z}"
        ),
        written[-1],
        dpi=QC_DPI,
    )
    foreground_of, _ = foreground_reader(settings.foreground, dims)
    for frame in open_result(flow_folder(run_dir, status)).frames:
        t = frame.source_frame
        intensity = read_frames(spec, header, [t])[0]
        flow = frame.load()
        foreground = foreground_of(t, intensity)
        considered = foreground if foreground is not None else np.ones(intensity.shape, bool)
        finite = np.isfinite(flow["vx"]) & np.isfinite(flow["vy"])
        if "vz" in flow:
            finite &= np.isfinite(flow["vz"])
        reliable, _ = reliability_mask(flow["rel"], considered & finite, settings.features)
        if foreground is not None:
            written.append(out / f"foreground_t{t:04d}.png")
            figures.save(
                figures.foreground_overlay(
                    intensity, foreground, z, f"{uid}: foreground, t={t}, z={z}"
                ),
                written[-1],
                dpi=QC_DPI,
            )
        written.append(out / f"flow_t{t:04d}.png")
        figure = figures.flow_overview(
            intensity, flow, z, step=max(4, dims["X"] // 40), reliable=reliable & considered
        )
        figure.suptitle(f"{uid}: optical flow, source time point {t}, z={z}")
        figures.save(figure, written[-1], dpi=QC_DPI)
    return written


def export_qc_figures(
    run_dir: Path, settings: RunSettings, z: int | None = None, tracker: Tracker | None = None
) -> list[Path]:
    """Save QC figures for every completed field of view of a run.

    Parameters
    ----------
    run_dir
        Run folder with ``fovs.csv`` (and feature tables for the time plots).
    settings
        The run's settings.
    z
        Z slice to show; default is the middle slice.
    tracker
        Optional progress display (one step per field of view).

    Returns
    -------
    list of pathlib.Path
        Every written figure.

    Raises
    ------
    InputError
        When ``<run>/qc`` already exists (figures are never overwritten).
    """
    run_dir = Path(run_dir)
    if (run_dir / "qc").exists():
        raise InputError(f"{run_dir / 'qc'} exists; QC figures are never overwritten.")
    statuses = pd.read_csv(run_dir / "fovs.csv", dtype=str, keep_default_na=False)
    done = statuses[statuses["status"].isin(["complete", "flow complete"])]
    table = run_dir / "features" / "features_per_frame.csv"
    frames = pd.read_csv(table) if table.exists() else None
    written: list[Path] = []
    stage = (tracker or Tracker()).stage("QC figures", len(done))
    for status in done.to_dict("records"):
        written += export_fov(run_dir, status, settings, z)
        if frames is not None:
            own = frames[frames["fov_uid"] == status["fov_uid"]].sort_values("t")
            path = run_dir / "qc" / status["fov_uid"] / "features_over_time.png"
            figures.save(
                figures.feature_timeseries(
                    own,
                    _plotted(own),
                    "t",
                ),
                path,
                dpi=QC_DPI,
            )
            written.append(path)
        stage.update(str(status["position_id"]))
    stage.close()
    if frames is not None:
        path = run_dir / "qc" / "feature_histograms.png"
        figures.save(
            figures.feature_histograms(frames, _plotted(frames)),
            path,
            dpi=QC_DPI,
        )
        written.append(path)
    return written
