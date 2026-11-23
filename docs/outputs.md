# Outputs and run folder

[:arrow_left: Documentation index](index.md)

Everything the app writes goes into a **run folder** inside your results folder. A run folder
holds exactly one run: it is never re-used, and its files are never overwritten. Your input
images are only read.

## Layout

```
<results>/
├── examples/
│   └── run-<date>-<time>/        one folder per "Process the example" (section 2), same layout
└── <run>/                        section 3 (default name run-YYYYmmdd-HHMMSS, UTC)
    ├── run_started.json          the run's claim: this folder holds one run, never entered again
    ├── run_manifest.json         inputs, calibration, settings, versions, profiler source hash, per-FOV status
    ├── experiments.csv           validated metadata with fov_uid
    ├── fovs.csv                  status of every field of view (failures included)
    ├── flow/
    │   └── <fov_uid>/            <fov_uid>_{vx,vy,vz,rel}_tNNNN.tiff + flow_manifest.json
    ├── features/
    │   ├── features_per_frame.csv   every optical-flow time point t
    │   ├── features_per_fov.csv     time averages, one row per field of view
    │   └── feature_dictionary.json  units, column naming and every column's definition
    ├── qc/                       QC figures, if ticked in section 3 (see Quality control)
    ├── analysis/
    │   ├── figures/              (created empty with the run)
    │   └── <report name>/        MorphoCoverage report.html with its figures and data,
    │                             design.json, morphocoverage_objects.csv, morphocoverage_fovs.csv
    └── logs/
        └── run.log
```

Tables are UTF-8 CSV; an undefined value (NaN) is an **empty cell**. The run's tables, manifests
and QC figures are written through a temporary file and an atomic rename, and each field of
view's optical flow is published as a complete folder, so an interrupted write never leaves a
half-written file there. (The report folder's files are written by MorphoCoverage and pandas
directly.)

## Run files

### `run_started.json`

Created exclusively before anything else is written, with the start time, process ID and host
name. If it already exists (a run finished, is running, or was interrupted in that folder), the
new run is refused: `... already holds a run, finished, running or interrupted ... a run is never
run twice or overwritten.` Choose a new run name.

### `run_manifest.json`

Written when the run ends. It records everything needed to trace a number back:

| Key | Content |
|---|---|
| `kind`, `format_version`, `stage` | `opticalflow3d_profiler.run`, version 1, `optical flow and features` |
| `started`, `finished` | UTC times |
| `environment` | App version, Python, platform, and the version of each dependency (numpy, scipy, tifffile, pandas, matplotlib, ipywidgets, natsort, tqdm, morphocoverage, morphobricks-normalization, umap-learn, scikit-learn), with the Git commit when installed from Git |
| `profiler` | `version`, number of modules, and `source_sha256`: a SHA-256 over every Python module of the app, so two different implementations never share an identity even without a version change |
| `upstream` | OpticalFlow3D repository, commit and SHA-256 of `calc_flow.py` |
| `settings` | Axes, calibration, optical-flow parameters (with the **resolved** flow mode), feature settings, foreground, foreground name |
| `calibration_issues` | Missing calibration, in words |
| `reuse_from` | The earlier run whose flow could be reused, or `null` |
| `fovs` | Per field of view: status, flow origin, number of flow frames, warnings, message, foreground rule |
| `outputs` | Precision, file format, table format |

### `experiments.csv`

The validated metadata: `fov_uid`, `condition`, `biological_repeat`, `technical_repeat`,
`position_id`, `image_path`, `source_relative_path`.

### `fovs.csv`

The metadata plus, for every field of view:

| Column | Meaning |
|---|---|
| `status` | `complete`, or `failed` (`flow complete` when only the optical flow was requested from Python) |
| `flow_origin` | `computed`; `reused: <folder>`; or `computed (earlier flow in <folder> not reused: <reasons>)` |
| `n_flow_frames` | Number of optical-flow time points |
| `warnings` | Warnings separated by ` \| `: header calibration differing from the confirmed one, shallow Z stack, brightness change above 2 %/frame, whole-image measurement |
| `message` | The error message of a failed field of view (the traceback is in `logs/run.log`) |

A failed field of view is listed, never skipped silently. It has no rows in the feature tables.

### `flow/<fov_uid>/`

The optical flow of one field of view in the upstream file layout:

- `<fov_uid>_vx_tNNNN.tiff`, `_vy_`, `_vz_` (3D mode only) and `_rel_`: one file per component and
  analysed time point, numbered by the **source frame** (0-based). `vx`, `vy` in pixels/frame,
  `vz` in slices/frame, `rel` the reliability. Always in upstream units, whatever the calibration.
- `flow_manifest.json`:
  - `identity`: what the result depends on: the input file's SHA-256 and size, the confirmed axes,
    the dimensions, the pixel type, the optical-flow parameters (resolved mode, sigmas, precision,
    brightness correction), the upstream identity, the frame map (source frame of each output)
    and, when a brightness correction is used, the correction code's identity. The calibration is
    **not** part of it, because the saved velocities do not depend on it;
  - `identity_key`: a SHA-256 of the identity;
  - `outputs`: per output, its source frame, each file's name, type and SHA-256, the window's
    mean intensities, `brightness_change_per_frame`, and the equalisation factors (or the
    histogram reference frame);
  - `velocity_units`, `reliability`, app and Python/NumPy versions, and the computing time.

A field of view's flow is written into a temporary folder and published with one rename only when
complete, so an interrupted run leaves no partial result.

### `features/`

- **`features_per_frame.csv`**: one row per field of view and optical-flow time point, with the
  metadata, `output_index`, `t` (source frame, 0-based), `time_min` (`t × frame interval`, empty
  without a frame interval), every feature, and `undefined_features` (the reason for each empty
  feature).
- **`features_per_fov.csv`**: one row per field of view (complete ones only), with the metadata,
  each feature averaged over time under the same column name (circular mean for the direction),
  `n_flow_frames` and `undefined_features`.
- **`feature_dictionary.json`**: `units` (`lateral`, `axial`, `time`), `column_naming` (scheme and
  object-set name), the metadata and frame-identifier columns, and one entry per column for the
  per-frame and per-FOV tables: name, family, description, formula, unit, level, requirements,
  applicability (`biological`, `experimental_axial`, `orientation`, `qc`) and when it is undefined.
  The human-readable version is the [Feature glossary](features.md).

Column names: `<foreground name>__<feature>` (`Nuclei__speed_xy_median`), or `whole__<feature>`
without a foreground; `qc_*` columns keep their plain names
([MorphoBricks conventions](morphobricks.md#feature-tables-and-column-names)).

### `analysis/<report name>/`

Written by section 4c. The folder must not exist yet: reports are never overwritten.

| File | Content |
|---|---|
| `report.html` (with its figures and data) | MorphoCoverage's report |
| `design.json` | Creation time, the design (control, readout, `repeats_paired`, `include_axial`, `random_state`), observation unit `fov`, declared features, notes, the runs used, MorphoCoverage version and commit |
| `morphocoverage_objects.csv` | Exactly what MorphoCoverage received: one row per field of view with the identity columns and the declared features |
| `morphocoverage_fovs.csv` | The fields of view with their `repeat_group` |

With several runs, the report goes into the first run folder (in path order), and
`design.json` lists every run.

### `logs/run.log`

One line per step, and the full traceback of every failed field of view.

## Reusing earlier optical flow

The optical flow is the slow part. To extract features again from the same optical flow (for
example with another foreground, reliability filter or region size), you can create a **new** run
that reuses the flow of an earlier one. This is available from Python, not from a notebook
widget:

```python
from pathlib import Path
from opticalflow3d_profiler.experiment import read_experiment_folder
from opticalflow3d_profiler.pipeline import RunSettings, run_experiment
from opticalflow3d_profiler.results import create_run

metadata = read_experiment_folder(Path("my_experiment"))
settings = RunSettings(...)            # same axes and optical-flow settings as the earlier run
run = create_run(Path("results"), "run-whole-image")
run_experiment(metadata, settings, run, reuse_from=Path("results/run-threshold"))
```

For each field of view, the earlier `flow/<fov_uid>/` is reused **only if**:

1. its `flow_manifest.json` identity is exactly the identity the new run would compute (same input
   file content, axes, dimensions, pixel type, optical-flow parameters and resolved mode, upstream
   code, frame map and, if used, brightness-correction code);
2. its identity key matches its identity;
3. every planned output is present with all its components; and
4. every file exists with its recorded SHA-256.

Then `flow_origin` is `reused: <earlier folder>`, and the new run reads the flow from there (it is
not copied, so keep the earlier run). Otherwise the flow is **recomputed** into the new run, and
`flow_origin` names every reason, for example:

```
computed (earlier flow in results/run-1/flow/<fov_uid> not reused: Different inputs or settings: parameters.w_sig: 4.0 → 3.0.)
```

The earlier result is never modified. Because the calibration is not part of the flow identity,
flow can be reused with a corrected calibration, as long as the resolved flow mode stays the same
(in `auto` mode the calibration decides between 3D and per-slice flow); the features are then
recomputed in the new units.
