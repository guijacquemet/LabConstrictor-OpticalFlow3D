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

from .brightness import WARNING_CHANGE_PER_FRAME
from .config import Calibration, FeatureSettings, FlowParameters, ForegroundSpec, ImageSpec
from .config import to_record as record
from .experiment import METADATA_COLUMNS
from .feature_dictionary import dictionary_records, frame_dictionary
from .flow_backend import flow_identity, run_flow, upstream_identity
from .flow_features import frame_features, velocity_scale
from .flow_store import FlowResult, open_result, verify_result
from .foreground import describe, threshold_frame
from .image_io import ImageHeader, dimensions, file_identity, inspect_tiff, read_frames
from .naming import ColumnNames
from .progress import Tracker
from .results import environment, now, relative, write_csv, write_json
from .temporal_features import aggregate_fov, fov_dictionary
from .validation import (
    InputError,
    check_calibration,
    check_feature_settings,
    check_time_and_depth,
    raise_for_errors,
    resolve_flow_mode,
)

LOG = logging.getLogger("opticalflow3d_profiler")
FRAME_ID_COLUMNS = ("fov_uid", "output_index", "t", "time_min")


@dataclass(frozen=True)
class RunSettings:
    """Settings shared by every field of view of a run.

    Attributes
    ----------
    axes
        Confirmed axes of every input file (single-channel videos).
    calibration
        Calibration of every input (one acquisition setting per run).
    flow, features, foreground
        Upstream parameters, feature settings and foreground definition.
    object_set
        The foreground's object-set token, the first token of every feature column
        (MorphoBricks naming, :mod:`~opticalflow3d_profiler.naming`); without foreground the
        token is ``whole``.
    """

    axes: str
    calibration: Calibration
    flow: FlowParameters = field(default_factory=FlowParameters)
    features: FeatureSettings = field(default_factory=FeatureSettings)
    foreground: ForegroundSpec = field(default_factory=ForegroundSpec)
    object_set: str = "Nuclei"

    def column_names(self) -> ColumnNames:
        """Return the checked tokens of this run's feature columns."""
        return ColumnNames.of(self.object_set, self.foreground.mode != "none")


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
    tracker: Tracker | None = None,
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
    tracker
        Optional progress display of the optical-flow windows.

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
    run_flow(spec, header, settings.flow, out, uid, progress=LOG.info, tracker=tracker)
    return open_result(out), "computed"


def frame_rows(
    result: FlowResult,
    settings: RunSettings,
    foreground_of: Callable,
    intensity_of: Callable | None,
    tracker: Tracker | None = None,
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
    tracker
        Optional progress display of the frames.

    Returns
    -------
    list of dict
        One row per output with identifiers, values and ``undefined_features``.
    """
    rows = []
    dt = settings.calibration.frame_interval
    stage = (tracker or Tracker()).stage(f"Features {result.name}", len(result.frames), True)
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
        recorded = result.manifest.get("outputs", [{}] * (index + 1))[index]
        features.put(
            "qc_brightness_change_per_frame",
            recorded.get("brightness_change_per_frame"),
            "not recorded (optical flow from an older result)",
        )
        row: dict[str, object] = {
            "fov_uid": result.name,
            "output_index": index,
            "t": t,
            "time_min": t * dt if dt else None,
        }
        row.update(features.values)
        row["undefined_features"] = "; ".join(
            f"{k}: {v}" for k, v in sorted(features.undefined.items())
        )
        rows.append(row)
        stage.update(f"time point {t}")
    stage.close()
    return rows


def brightness_warning(result: FlowResult, equalised: bool) -> str:
    """Return a warning when the global brightness changes markedly, or an empty string."""
    changes = [
        abs(o["brightness_change_per_frame"])
        for o in result.manifest.get("outputs", [])
        if o.get("brightness_change_per_frame") is not None
    ]
    if not changes or max(changes) <= WARNING_CHANGE_PER_FRAME:
        return ""
    advice = (
        "brightness equalisation was applied to the optical-flow input"
        if equalised
        else "optical flow reads part of it as motion; consider brightness equalisation"
    )
    return (
        f"The global brightness changes by up to {max(changes):.1%} per frame ({advice}). "
        "Compare qc_brightness_change_per_frame between conditions."
    )


def foreground_reader(spec: ForegroundSpec, dims: dict[str, int]) -> tuple[Callable, dict]:
    """Return the per-frame foreground function and its provenance description."""
    del dims  # the threshold works on each frame's intensities
    if spec.mode == "threshold":
        if spec.threshold is None:
            raise InputError("A foreground threshold value is required.")
        return (lambda _t, i: threshold_frame(i, spec.threshold)), describe(spec)
    return (lambda _t, _i: None), describe(spec)


def process_fov(
    row: dict[str, str],
    settings: RunSettings,
    run_dir: Path,
    reuse_from: Path | None = None,
    flow_only: bool = False,
    tracker: Tracker | None = None,
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
    tracker
        Optional progress display (nested bars of this field of view).

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
        spec = ImageSpec(Path(row["image_path"]), settings.axes, settings.calibration)
        header = inspect_tiff(spec.path)
        warnings = calibration_warnings(header, settings.calibration)
        dims = dimensions(spec, header)
        warnings += [
            i.message
            for i in check_time_and_depth(dims["T"], dims["Z"], settings.flow)
            if i.severity == "warning"
        ]
        result, origin = obtain_flow(spec, header, settings, run_dir, uid, reuse_from, tracker)
        warnings += [
            w
            for w in [brightness_warning(result, settings.flow.brightness_equalisation != "none")]
            if w
        ]
        if flow_only:
            status.update(
                status="flow complete",
                flow_origin=origin,
                n_flow_frames=len(result.frames),
                warnings=" | ".join(warnings),
            )
            return FovOutcome(status)
        fg_spec = settings.foreground
        foreground_of, fg_record = foreground_reader(fg_spec, dims)
        rows = frame_rows(
            result, settings, foreground_of, lambda t: read_frames(spec, header, [t])[0], tracker
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
    defs = frame_dictionary(settings.features.speed_mode, settings.features.intensity_features)
    rows = []
    for uid, group in frame_table.groupby("fov_uid", sort=True):
        group = group.sort_values("t")
        values, undefined = aggregate_fov(group.to_dict("records"), defs)
        rows.append(
            {
                "fov_uid": uid,
                **values,
                "undefined_features": "; ".join(f"{k}: {v}" for k, v in sorted(undefined.items())),
            }
        )
    return pd.DataFrame(rows)


def rename_features(table: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Rename feature columns and the names in ``undefined_features`` notes."""
    out = table.rename(columns=mapping)
    if "undefined_features" in out.columns:
        out["undefined_features"] = [
            "; ".join(
                f"{mapping.get(k, k)}:{v}"
                for k, _, v in (p.partition(":") for p in str(n).split("; "))
            )
            if isinstance(n, str) and n
            else n
            for n in out["undefined_features"]
        ]
    return out


def write_feature_tables(
    run_dir: Path, metadata: pd.DataFrame, frame_table: pd.DataFrame, settings: RunSettings
) -> pd.DataFrame:
    """Write the full per-frame table, the per-FOV time averages and the feature dictionary.

    Feature columns are renamed to the MorphoBricks scheme ``{object_set}__{feature}``
    (single-channel videos); ``qc_*`` columns keep their names (metadata).
    Undefined-feature notes name the columns too.

    Returns
    -------
    pandas.DataFrame
        The per-FOV table with the metadata columns first.
    """
    defs = frame_dictionary(settings.features.speed_mode, settings.features.intensity_features)
    time_unit = "min" if settings.calibration.frame_interval else "frame"
    names = settings.column_names()
    mapping = names.mapping(d.name for d in defs)
    per_fov = rename_features(fov_table(frame_table, settings), mapping)
    meta = metadata[[c for c in METADATA_COLUMNS if c in metadata.columns]]
    per_fov = meta.merge(per_fov, on="fov_uid", how="inner")
    per_frame = meta.merge(rename_features(frame_table, mapping), on="fov_uid", how="inner")
    defs = [replace(d, name=mapping[d.name]) for d in defs]
    write_csv(run_dir / "features" / "features_per_frame.csv", per_frame)
    write_csv(run_dir / "features" / "features_per_fov.csv", per_fov)
    scale = velocity_scale(settings.calibration)
    write_json(
        run_dir / "features" / "feature_dictionary.json",
        {
            "units": {"lateral": scale.lateral_unit, "axial": scale.axial_unit, "time": time_unit},
            "column_naming": {
                "scheme": "MorphoBricks {object_set}__{feature} (single channel); qc_* unprefixed",
                "object_set": names.object_set,
            },
            "metadata_columns": list(meta.columns),
            "frame_identifier_columns": list(FRAME_ID_COLUMNS),
            "frame_features": dictionary_records(defs),
            "fov_features": dictionary_records(fov_dictionary(defs)),
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
    tracker: Tracker | None = None,
) -> dict[str, object]:
    """Process every field of view of a validated metadata table into a run folder.

    A run folder is used once: a second call on a folder that holds a ``run_manifest.json``
    is refused, a flow-only run included, so no status or provenance file is ever replaced.
    To extract features from earlier optical flow, or with other settings, create a new run
    with ``reuse_from``.

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
    tracker
        Optional progress display (:mod:`~opticalflow3d_profiler.progress`): one bar over
        the fields of view, nested bars over each one's flow windows and feature frames.

    Returns
    -------
    dict
        The run manifest that was written.

    Raises
    ------
    InputError
        When the run folder already holds a run.
    """
    if (run_dir / "run_manifest.json").exists():
        raise InputError(
            f"{run_dir} already holds a run (run_manifest.json); a run is never run twice or "
            "overwritten. Create a new run, with reuse_from to reuse its verified optical flow."
        )
    settings = replace(settings, flow=resolve_flow_mode(settings.flow, settings.calibration))
    if not flow_only:
        raise_for_errors(check_feature_settings(settings.features, settings.foreground))
        settings.column_names()
        if settings.flow.mode == "xy_per_slice" and settings.features.speed_mode == "xyz":
            raise InputError(
                "3D speed needs 3D optical flow; with per-slice 2D flow choose XY speed."
            )
    handler = logging.FileHandler(run_dir / "logs" / "run.log", encoding="utf-8")
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    started = now()
    outcomes = []
    tracker = tracker or Tracker()
    stage = tracker.stage("Fields of view", len(metadata))
    try:
        for row in metadata.to_dict("records"):
            (progress or LOG.info)(f"Processing {row['fov_uid']}...")
            outcomes.append(process_fov(row, settings, run_dir, reuse_from, flow_only, tracker))
            (progress or LOG.info)(f"{row['fov_uid']}: {outcomes[-1].status['status']}")
            stage.update(f"{row['position_id']}: {outcomes[-1].status['status']}")
    finally:
        stage.close()
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
