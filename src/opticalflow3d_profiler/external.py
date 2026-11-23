"""Features from optical flow calculated earlier by upstream ``process_flow`` (orchestration).

The source image of such a result cannot be verified, so the run manifest marks it
``external, not verified`` and the intensity QC columns stay undefined. Without the original
image there is no intensity threshold, so the foreground is ``none`` (whole volume).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import to_record
from .experiment import validate_metadata
from .flow_store import open_upstream_result
from .foreground import describe
from .pipeline import RunSettings, frame_rows, write_feature_tables
from .results import environment, now, write_csv, write_json
from .validation import InputError


def external_features(
    folder: Path, name: str, metadata_row: dict[str, str], settings: RunSettings, run_dir: Path
) -> dict[str, object]:
    """Extract features from an upstream result folder into a new run.

    Parameters
    ----------
    folder, name
        Upstream output folder and its ``imNameSave`` prefix.
    metadata_row
        The experimental metadata of this field of view (``image_path`` may name the
        original image for the record; it is not read).
    settings
        Run settings (``axes`` and ``channel`` are recorded but not used).
    run_dir
        New run folder.

    Returns
    -------
    dict
        The run manifest that was written.

    Raises
    ------
    InputError
        For an incomplete result or a threshold foreground (needs the image).
    """
    result = open_upstream_result(Path(folder), name)
    metadata = validate_metadata(pd.DataFrame([metadata_row]))
    uid = metadata.loc[0, "fov_uid"]
    result = type(result)(result.folder, uid, result.frames, result.manifest, result.verified)
    fg = settings.foreground
    if fg.mode == "threshold":
        raise InputError(
            "A threshold foreground needs the original image; use no foreground for an "
            "external result."
        )
    rows = frame_rows(result, settings, lambda _t, _i: None, None)
    write_feature_tables(run_dir, metadata, pd.DataFrame(rows), settings)
    status = {
        "fov_uid": uid,
        "status": "complete",
        "n_flow_frames": len(rows),
        "flow_origin": f"external, not verified: {Path(folder).as_posix()}",
        "warnings": "Source image identity unknown; intensity QC undefined.",
        "message": "",
    }
    write_csv(run_dir / "fovs.csv", metadata.merge(pd.DataFrame([status]), on="fov_uid"))
    write_csv(run_dir / "experiments.csv", metadata)
    manifest = {
        "kind": "opticalflow3d_profiler.run",
        "format_version": 1,
        "stage": "features from an external upstream result",
        "created": now(),
        "environment": environment(),
        "settings": to_record(settings),
        "external_result": result.manifest,
        "foreground": describe(fg),
        "fovs": [status],
    }
    write_json(run_dir / "run_manifest.json", manifest)
    return manifest
