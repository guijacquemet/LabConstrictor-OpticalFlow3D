"""Process fields of view: optical flow, then features, then tables (orchestration).

Every field of view listed in the metadata is attempted in ``fov_uid`` order. A failure
is recorded in ``fovs.csv`` and the run manifest with its message and the run continues;
nothing is skipped silently. Optical flow from an earlier run is reused only after its
identity and file hashes are verified (:func:`~opticalflow3d_profiler.flow_store.verify_result`).
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

from .config import Calibration, FeatureSettings, FlowParameters, ForegroundSpec, ImageSpec
from .config import to_record as record
from .experiment import METADATA_COLUMNS
from .feature_dictionary import dictionary_records, frame_dictionary
from .flow_backend import flow_identity, run_flow, upstream_identity
from .flow_features import frame_features, velocity_scale
from .flow_store import FlowResult, open_result, verify_result
from .foreground import MaskInfo, check_mask, describe, mask_frame, threshold_frame
from .image_io import ImageHeader, dimensions, file_identity, inspect_tiff, read_frames
from .results import environment, now, relative, write_csv, write_json
from .temporal_features import aggregate_fov, fov_dictionary
from .validation import InputError, check_calibration

LOG = logging.getLogger("opticalflow3d_profiler")
FRAME_ID_COLUMNS = ("fov_uid", "output_index", "source_frame", "time_min")


@dataclass(frozen=True)
class RunSettings:
    """Settings shared by every field of view of a run.

    Attributes
    ----------
    axes, channel
        Confirmed axes and channel of every input file.
    calibration
        Calibration of every input (one acquisition setting per run).
    flow, features, foreground
        Upstream parameters, feature settings and foreground definition. With a
        ``mask_path`` column in the metadata, each field of view uses its own mask.
    """

    axes: str
    channel: int | None
    calibration: Calibration
    flow: FlowParameters = field(default_factory=FlowParameters)
    features: FeatureSettings = field(default_factory=FeatureSettings)
    foreground: ForegroundSpec = field(default_factory=ForegroundSpec)


@dataclass
class FovOutcome:
    """Status and per-frame feature rows of one field of view."""

    status: dict[str, object]
    rows: list[dict[str, object]] = field(default_factory=list)


def calibration_warnings(header: ImageHeader, calibration: Calibration) -> list[str]:
    """Return disagreements between the header calibration and the confirmed one."""
    found = []
    suggestion = header.calibration_suggestion
    for name in ("pixel_size_x", "pixel_size_y", "pixel_size_z", "frame_interval"):
        stated, used = getattr(suggestion, name), getattr(calibration, name)
        if stated is not None and used is not None and abs(stated - used) > 0.01 * used:
            found.append(f"The header states {name}={stated:g} but {used:g} was used.")
    return found


def obtain_flow(
    spec: ImageSpec,
    header: ImageHeader,
    settings: RunSettings,
    run_dir: Path,
    uid: str,
    reuse_from: Path | None,
) -> tuple[FlowResult, str]:
    """Return the verified optical flow of one field of view, computing it if needed.

    Parameters
    ----------
    spec, header
        Input and header.
    settings
        Run settings.
    run_dir
        Current run folder.
    uid
        Field-of-view identifier.
    reuse_from
        Earlier run folder whose ``flow/<uid>`` may be reused.

    Returns
    -------
    tuple
        The result and its origin (``"computed"`` or ``"reused: <path>"``).

    Raises
    ------
    InputError
        When an earlier result exists but cannot be reused (it is never overwritten).
    """
    if reuse_from is not None and (Path(reuse_from) / "flow" / uid).is_dir():
        folder = Path(reuse_from) / "flow" / uid
        expected = flow_identity(spec, header, settings.flow, file_identity(spec.path))
        problems = verify_result(folder, expected)
        if problems:
            raise InputError(
                f"The earlier optical flow in {folder} cannot be reused: " + " ".join(problems)
            )
        return open_result(folder), f"reused: {folder.as_posix()}"
    out = run_dir / "flow" / uid
    run_flow(spec, header, settings.flow, out, uid, progress=LOG.info)
    return open_result(out), "computed"


def frame_rows(
    result: FlowResult,
    settings: RunSettings,
    foreground_of: Callable,
    intensity_of: Callable | None,
) -> list[dict[str, object]]:
    """Compute the feature rows of every output of a flow result, one frame at a time.

    Parameters
    ----------
    result
        Optical-flow outputs.
    settings
        Run settings.
    foreground_of
        ``source_frame -> boolean ZYX or None``.
    intensity_of
        ``source_frame -> ZYX intensities`` or ``None``.

    Returns
    -------
    list of dict
        One row per output with identifiers, values and ``undefined_features``.
    """
    rows = []
    dt = settings.calibration.frame_interval
    for index, frame in enumerate(result.frames):
        t = frame.source_frame
        intensity = intensity_of(t) if intensity_of else None
        features = frame_features(
            frame.load(),
            foreground_of(t, intensity),
            intensity,
            settings.calibration,
            settings.features,
        )
        row: dict[str, object] = {
            "fov_uid": result.name,
            "output_index": index,
            "source_frame": t,
            "time_min": t * dt if dt else None,
        }
        row.update(features.values)
        row["undefined_features"] = "; ".join(
            f"{k}: {v}" for k, v in sorted(features.undefined.items())
        )
        rows.append(row)
    return rows


def foreground_reader(spec: ForegroundSpec, dims: dict[str, int]) -> tuple[Callable, dict]:
    """Return the per-frame foreground function and its provenance description."""
    info: MaskInfo | None = None
    if spec.mode == "mask":
        info = check_mask(spec, dims)
        return (lambda t, _i: mask_frame(info, t, dims)), describe(spec, info)
    if spec.mode == "threshold":
        if spec.threshold is None:
            raise InputError("A foreground threshold value is required.")
        return (lambda _t, i: threshold_frame(i, spec.threshold)), describe(spec, None)
    return (lambda _t, _i: None), describe(spec, None)


def process_fov(
    row: dict[str, str],
    settings: RunSettings,
    run_dir: Path,
    reuse_from: Path | None = None,
    flow_only: bool = False,
) -> FovOutcome:
    """Run optical flow and feature extraction for one metadata row.

    Parameters
    ----------
    row
        Validated metadata row.
    settings
        Run settings.
    run_dir
        Current run folder.
    reuse_from
        Earlier run folder for verified flow reuse.
    flow_only
        Stop after the optical flow (status ``flow complete``).

    Returns
    -------
    FovOutcome
        ``status`` is ``complete``, ``flow complete`` or ``failed`` (with the message).
    """
    uid = row["fov_uid"]
    status: dict[str, object] = {
        "fov_uid": uid,
        "status": "failed",
        "flow_origin": "",
        "n_flow_frames": 0,
        "warnings": "",
        "message": "",
    }
    try:
        spec = ImageSpec(
            Path(row["input_path"]), settings.axes, settings.channel, settings.calibration
        )
        header = inspect_tiff(spec.path)
        warnings = calibration_warnings(header, settings.calibration)
        result, origin = obtain_flow(spec, header, settings, run_dir, uid, reuse_from)
        if flow_only:
            status.update(
                status="flow complete",
                flow_origin=origin,
                n_flow_frames=len(result.frames),
                warnings=" | ".join(warnings),
            )
            return FovOutcome(status)
        dims = dimensions(spec, header)
        fg_spec = settings.foreground
        if row.get("mask_path"):
            fg_spec = replace(fg_spec, mask_path=Path(row["mask_path"]))
        foreground_of, fg_record = foreground_reader(fg_spec, dims)
        rows = frame_rows(
            result, settings, foreground_of, lambda t: read_frames(spec, header, [t])[0]
        )
        if fg_spec.mode == "none":
            warnings.append(fg_record["warning"])
        status.update(
            status="complete",
            flow_origin=origin,
            n_flow_frames=len(rows),
            warnings=" | ".join(warnings),
            foreground=fg_record,
        )
        return FovOutcome(status, rows)
    except Exception as error:  # noqa: BLE001 (every failure is recorded, never skipped)
        status["message"] = str(error)
        LOG.error("Field of view %s failed: %s\n%s", uid, error, traceback.format_exc())
        return FovOutcome(status)


def fov_table(frame_table: pd.DataFrame, settings: RunSettings) -> pd.DataFrame:
    """Aggregate the per-frame table into ``features_per_fov`` (one row per FOV)."""
    defs = frame_dictionary(settings.features.speed_mode)
    rows = []
    for uid, group in frame_table.groupby("fov_uid", sort=True):
        group = group.sort_values("source_frame")
        values, undefined = aggregate_fov(
            group.to_dict("records"),
            group["source_frame"].tolist(),
            defs,
            settings.calibration.frame_interval,
        )
        rows.append(
            {
                "fov_uid": uid,
                **values,
                "undefined_features": "; ".join(f"{k}: {v}" for k, v in sorted(undefined.items())),
            }
        )
    return pd.DataFrame(rows)


def write_feature_tables(
    run_dir: Path, metadata: pd.DataFrame, frame_table: pd.DataFrame, settings: RunSettings
) -> pd.DataFrame:
    """Write the frame and FOV feature tables and the feature dictionary.

    Returns
    -------
    pandas.DataFrame
        The per-FOV table with the metadata columns first.
    """
    defs = frame_dictionary(settings.features.speed_mode)
    time_unit = "min" if settings.calibration.frame_interval else "frame"
    per_fov = fov_table(frame_table, settings)
    meta = metadata[[c for c in METADATA_COLUMNS if c in metadata.columns]]
    per_fov = meta.merge(per_fov, on="fov_uid", how="inner")
    per_frame = meta.merge(frame_table, on="fov_uid", how="inner")
    write_csv(run_dir / "features" / "features_per_frame.csv", per_frame)
    write_csv(run_dir / "features" / "features_per_fov.csv", per_fov)
    scale = velocity_scale(settings.calibration)
    write_json(
        run_dir / "features" / "feature_dictionary.json",
        {
            "units": {"lateral": scale.lateral_unit, "axial": scale.axial_unit, "time": time_unit},
            "metadata_columns": list(meta.columns),
            "frame_identifier_columns": list(FRAME_ID_COLUMNS),
            "frame_features": dictionary_records(defs),
            "fov_features": dictionary_records(fov_dictionary(defs, time_unit)),
        },
    )
    return per_fov


def run_experiment(
    metadata: pd.DataFrame,
    settings: RunSettings,
    run_dir: Path,
    reuse_from: Path | None = None,
    progress: Callable[[str], None] | None = None,
    flow_only: bool = False,
) -> dict[str, object]:
    """Process every field of view of a validated metadata table into a run folder.

    Run it once with ``flow_only=True`` and again with ``reuse_from=run_dir`` to calculate
    the optical flow and the features in two steps; features are extracted only once per
    run (use a new run with ``reuse_from`` for other feature settings).

    Parameters
    ----------
    metadata
        Output of :func:`~opticalflow3d_profiler.experiment.validate_metadata`.
    settings
        Run settings.
    run_dir
        Run folder from :func:`~opticalflow3d_profiler.results.create_run`.
    reuse_from
        Earlier run folder whose verified optical flow may be reused.
    progress
        Optional callback for one line per field of view.
    flow_only
        Calculate and verify the optical flow only.

    Returns
    -------
    dict
        The run manifest that was written.

    Raises
    ------
    InputError
        When the run already holds feature tables.
    """
    if (run_dir / "features" / "features_per_fov.csv").exists():
        raise InputError(
            f"{run_dir} already holds features; create a new run that reuses "
            "its optical flow to extract features with other settings."
        )
    handler = logging.FileHandler(run_dir / "logs" / "run.log", encoding="utf-8")
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    started = now()
    outcomes = []
    try:
        for row in metadata.to_dict("records"):
            (progress or LOG.info)(f"Processing {row['fov_uid']}...")
            outcomes.append(process_fov(row, settings, run_dir, reuse_from, flow_only))
            (progress or LOG.info)(f"{row['fov_uid']}: {outcomes[-1].status['status']}")
    finally:
        LOG.removeHandler(handler)
        handler.close()
    rows = [r for o in outcomes for r in o.rows]
    frame_table = pd.DataFrame(rows)
    if not frame_table.empty:
        write_feature_tables(run_dir, metadata, frame_table, settings)
    statuses = pd.DataFrame(
        [{k: v for k, v in o.status.items() if k != "foreground"} for o in outcomes]
    )
    write_csv(run_dir / "fovs.csv", metadata.merge(statuses, on="fov_uid", how="left"))
    write_csv(run_dir / "experiments.csv", metadata)
    manifest = {
        "kind": "opticalflow3d_profiler.run",
        "format_version": 1,
        "stage": "optical flow" if flow_only else "optical flow and features",
        "started": started,
        "finished": now(),
        "environment": environment(),
        "upstream": upstream_identity(),
        "settings": record(settings),
        "calibration_issues": [i.message for i in check_calibration(settings.calibration)],
        "reuse_from": relative(reuse_from, run_dir) if reuse_from else None,
        "fovs": [o.status for o in outcomes],
        "outputs": {
            "precision": settings.flow.output_dtype,
            "format": "TIFF (upstream layout)",
            "tables": "CSV, UTF-8, NaN as empty cell",
        },
    }
    write_json(run_dir / "run_manifest.json", manifest)
    return manifest
