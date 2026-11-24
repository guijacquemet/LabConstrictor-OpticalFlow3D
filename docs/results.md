# Results

[:arrow_left: Documentation index](index.md)

Where everything is saved, how to check the quality, how to interpret it, and what the app cannot do.

- [Outputs and run folder](#outputs-and-run-folder)
- [Quality control](#quality-control)
- [Interpreting results](#interpreting-results)
- [Limitations](#limitations)

## Outputs and run folder

Everything the app writes goes into a **run folder** inside your results folder. A run folder
holds exactly one run: it is never re-used, and its files are never overwritten. Your input
images are only read.

### Layout

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

### Run files

#### `run_started.json`

Created exclusively before anything else is written, with the start time, process ID and host
name. If it already exists (a run finished, is running, or was interrupted in that folder), the
new run is refused: `... already holds a run, finished, running or interrupted ... a run is never
run twice or overwritten.` Choose a new run name.

#### `run_manifest.json`

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

#### `experiments.csv`

The validated metadata: `fov_uid`, `condition`, `biological_repeat`, `technical_repeat`,
`position_id`, `image_path`, `source_relative_path`.

#### `fovs.csv`

The metadata plus, for every field of view:

| Column | Meaning |
|---|---|
| `status` | `complete`, or `failed` (`flow complete` when only the optical flow was requested from Python) |
| `flow_origin` | `computed`; `reused: <folder>`; or `computed (earlier flow in <folder> not reused: <reasons>)` |
| `n_flow_frames` | Number of optical-flow time points |
| `warnings` | Warnings separated by ` \| `: header calibration differing from the confirmed one, shallow Z stack, brightness change above 2 %/frame, whole-image measurement |
| `message` | The error message of a failed field of view (the traceback is in `logs/run.log`) |

A failed field of view is listed, never skipped silently. It has no rows in the feature tables.

#### `flow/<fov_uid>/`

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

#### `features/`

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
  applicability (`biological`, `experimental_axial`, `orientation`, `qc`) and when it is undefined;
  and `feature_implementation`: the SHA-256 of all these definitions and of the code that computes
  the features. Runs are combined only when both are equal.
  The human-readable version is the [Feature glossary](features.md).

Column names: `<foreground name>__<feature>` (`Nuclei__speed_xy_median`), or `whole__<feature>`
without a foreground; `qc_*` columns keep their plain names
([MorphoBricks conventions](morphobricks.md#feature-tables-and-column-names)).

#### `analysis/<report name>/`

Written by section 4c. The folder must not exist yet: reports are never overwritten.

| File | Content |
|---|---|
| `report.html` (with its figures and data) | MorphoCoverage's report |
| `design.json` | Creation time, the design (control, readout, `repeats_paired`, `include_axial`, `random_state`), observation unit `fov`, declared features, notes, the runs used, MorphoCoverage version and commit |
| `morphocoverage_objects.csv` | Exactly what MorphoCoverage received: one row per field of view with the identity columns and the declared features |
| `morphocoverage_fovs.csv` | The fields of view with their `repeat_group` |

With several runs, the report goes into the first run folder (in path order), and
`design.json` lists every run.

#### `logs/run.log`

One line per step, and the full traceback of every failed field of view.

### Reusing earlier optical flow

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

## Quality control

Optical flow always returns a number, even where there is nothing to measure. Before you trust a
comparison, check that the flow was reliable, that the foreground selected the nuclei, and that
the conditions were measured alike. This page lists the tools the app gives you: QC columns,
warnings and figures.

---

### Quick checklist

1. **Status:** every field of view is `complete` in `fovs.csv`; failures are understood.
2. **Warnings:** read the `warnings` column of `fovs.csv` (brightness change, calibration,
   shallow Z, whole-image measurement).
3. **Foreground:** the outlines in `qc/<fov_uid>/foreground_t*.png` follow the nuclei.
4. **Flow:** in `qc/<fov_uid>/flow_t*.png`, coloured (reliable) vectors sit on the nuclei and
   point in plausible directions; grey (unreliable) vectors are mostly in the background.
5. **Reliability and coverage:** `qc_reliable_fraction` and `qc_n_analysed_voxels` are not tiny,
   and similar between conditions.
6. **Confounders:** `qc_object_mean_voxels`, `qc_object_mean_z_extent`, `qc_foreground_fraction`
   and `qc_brightness_change_per_frame` are similar between conditions.
7. **Time course:** `qc/<fov_uid>/features_over_time.png` shows no single aberrant time point
   driving the average.

---

### QC columns

All QC columns are in both feature tables, with plain names (`qc_*`, no foreground prefix). They
are metadata: **never** given to MorphoCoverage as features. Full definitions:
[Feature glossary → Quality control](features.md#quality-control).

| Question | Columns | What to look for |
|---|---|---|
| Was the flow reliable where I measured? | `qc_reliable_fraction`, `qc_reliability_median`, `qc_reliability_p10`, `qc_reliability_p90`, `qc_reliability_threshold` | A low reliable fraction means most foreground voxels were excluded. With an absolute filter, compare the reliability distribution with your threshold. With a percentile filter, `qc_reliability_threshold` shows how the threshold moved between frames. |
| Were velocities valid? | `qc_invalid_velocity_fraction`, `qc_invalid_reliability_fraction` | Should be 0 or very small. Non-finite values are excluded, never replaced by 0. |
| How much was measured? | `qc_n_analysed_voxels`, `qc_foreground_fraction` | Tiny counts make every feature noisy. Occupancy differences between conditions change what the foreground holds. |
| Were the regional features well supported? | `qc_n_regions`, `qc_n_regions_analysed`, `qc_region_grid_coverage` | Regional features need at least 2 analysed regions; more is better. Coverage below 1 means partial edge regions were left out. |
| Are nuclei of similar size? | `qc_object_mean_voxels`, `qc_object_mean_z_extent`, `qc_n_objects` | The optical-flow gain depends on nuclear size and Z extent ([Validation](validation.md)). A size difference between conditions is a confounder of speed. Objects are 3D connected components of the foreground, so touching nuclei count as one object. |
| Did the brightness change? | `qc_brightness_change_per_frame` | The relative brightness slope per frame in each window (always measured, on raw intensities). Above 0.02 (2 %/frame) is flagged. |
| Similar intensity? (opt-in) | `qc_foreground_intensity_mean` | Only with *Also report intensity-based QC* ticked in section 2. |

In `features_per_fov.csv` the QC columns are time averages, like the features. Use
`features_per_frame.csv` to see them frame by frame.

#### Undefined values

Empty cells are values that do not exist, never zeros. `undefined_features` gives the reason for
each one, for example `no analysed voxel (empty foreground or nothing passes the reliability
criterion)`, `no motion threshold was set`, `per-slice 2D optical flow has no axial component`, or
`3D speed needs X, Y, Z and time calibration (one physical unit)`. In `features_per_fov.csv` it
gives the count of defined frames, for example `0 defined frame(s) of 9`.

---

### Warnings

Warnings do not stop the run. They are printed after the example run (section 2) and in the
section 3 table, and stored in the `warnings` column of `fovs.csv` and in `run_manifest.json`.

| Warning (start of the text) | Cause | What to do |
|---|---|---|
| `The global brightness changes by up to X% per frame (optical flow reads part of it as motion; consider brightness equalisation)` | `qc_brightness_change_per_frame` above 0.02 in at least one window of the field of view. | Compare `qc_brightness_change_per_frame` between conditions. If it differs or is large, consider a [brightness correction](theory.md#7-brightness-change-and-optional-correction) (for every condition). |
| `Brightness QC not reused: …` | The optical flow was reused from a run whose brightness QC was measured by another brightness implementation. The velocities are still valid; `qc_brightness_change_per_frame` is left empty with the reason. | Recompute the optical flow (a new run without `reuse_from`) if you need the brightness QC. |
| `... (brightness equalisation was applied to the optical-flow input)` | Same, with a correction switched on. | Check that the correction removed the artefact (speeds stable over time, `vz` near 0). |
| `The header states pixel_size_x=… but … was used.` | The image header's calibration differs by more than 1 % from the confirmed calibration. | Check which value is right. Images with different acquisition settings belong in separate runs. |
| `The Z stack (N slices) is shorter than the spatial derivative kernel …` | 3D mode with fewer slices than `2·ceil(3·xyzSig) + 1`. | Treat axial features as experimental, or use per-slice 2D flow. |
| `Whole-image measurement: background and nuclear occupancy may influence the features.` | Foreground set to *none*. | Prefer an intensity-threshold foreground for comparisons. |

Calibration issues are also shown when you confirm section 1 and recorded in
`run_manifest.json` (`calibration_issues`):
- `XY pixel size or frame interval is unknown: velocities stay in pixels/frame ...`
- `Z spacing is unknown: axial velocities stay in slices/frame ...`

---

### QC figures

With **Save QC figures of every FOV** ticked in section 3 (the default), the app saves figures in
`<run>/qc/` for every field of view whose optical flow completed. The figures only display saved
results; they compute no new numbers. If `<run>/qc` already exists, nothing is overwritten.

| File | What it shows | What to check |
|---|---|---|
| `qc/<fov_uid>/input_montage_z<z>.png` | The video at the middle Z slice, every time point, on one shared raw-intensity scale | Drift, focus loss, bleaching or brightening, frames that look different |
| `qc/<fov_uid>/foreground_t<NNNN>.png` | Raw slice and the foreground outline at each analysed time point, with the percentage of the slice in the foreground (only with a threshold foreground) | The outline follows the nuclei, without background or holes |
| `qc/<fov_uid>/flow_t<NNNN>.png` | Three panels at each analysed time point: the image with flow vectors (colour = direction, −180° to 180°, y down; **unreliable or out-of-foreground vectors in grey**), the XY speed map (px/frame), and log10 reliability | Reliable vectors on nuclei, plausible directions; no large speeds in empty regions counted as reliable |
| `qc/<fov_uid>/features_over_time.png` | Per-frame median speed, global XY coherence and `qc_reliable_fraction` | Stable values, or a smooth trend; one outlier frame can bias the average |
| `qc/feature_histograms.png` | Histograms of the same three columns over every frame of the run, with the number of undefined values | Outlier fields of view or frames |

The Z slice shown is the middle slice. Velocities in the figures are in upstream units
(pixels/frame). For flow reused from an earlier run, the figures read the flow from that run's
folder.

The example processed in section 2 shows the same flow panels (without the grey reliability
marking) and the per-frame plots, so you can adjust settings before processing everything.

---

### Before you trust a comparison

- [ ] QC columns are similar between conditions, or their differences are reported.
- [ ] The foreground and flow figures look right for a few fields of view of every condition.
- [ ] The effect holds in the per-frame table, not just in one time point.
- [ ] The effect is seen in each biological repeat, and the paired test on repeat means (3 or
      more repeats) supports it. A PCA/UMAP separation or the FOV-level screen alone is not
      enough.
- [ ] Axial features, if used, are treated as experimental.
- [ ] Speeds are described as relative optical-flow speeds, not calibrated displacements.

See [Interpreting results](#interpreting-results) for the reasoning behind each point.

## Interpreting results

This page is about reading the numbers: what each feature family tells you biologically, which
columns are readouts, and the traps to avoid. The calculations are in [How it works](theory.md);
every column is in the [Feature glossary](features.md).

### What the app actually measures

Optical flow measures how the **intensity pattern** of the nuclear signal moves between frames,
voxel by voxel. When nuclei move, their pattern moves, so the flow reflects nuclear motion. But it
also reflects anything else that changes the pattern: nuclei changing shape or brightness,
division, focus drift, bleaching, illumination changes, noise. And it gives no identity: a voxel's
velocity is not "the speed of nucleus 12".

Think of the results as a **motion profile of the field of view**: how fast the nuclear signal
moves, how ordered the motion is, and how uniform it is in space. Compare profiles between
conditions imaged with the same settings; do not read them as absolute nuclear speeds.

### What each family tells you

| Family | Biological question | Typical columns | Example interpretation |
|---|---|---|---|
| [Speed](features.md#speed) | How fast does the nuclear signal move? | `speed_xy_median`, `speed_xy_mean`, `speed_xy_p90`, `speed_xy_cv` | A drug that stalls migration lowers the median and the high percentiles. `cv` and the spread between `p10` and `p90` describe how variable motion is within the field of view. |
| [Velocity components](features.md#velocity-components) | How is motion split between axes? | `vx_sd`, `vy_sd`, `vx_abs_mean`, `vy_abs_mean`; axial `vz_*` | `vx_abs_mean` and `vy_abs_mean` differ when motion is mostly along one image axis. Axial columns are experimental. |
| [Collective motion and direction](features.md#collective-motion-and-direction) | Do nuclei move together, and in which pattern? | `coherence_xy_global`, `coherence_xy_local`, `xy_angular_entropy`, `xy_angular_dispersion`, `xy_aligned_fraction` | Collective migration in one direction: high global coherence, low entropy and dispersion, high aligned fraction. Swirls or local streams: high local but low global coherence. Random motion: low coherence, entropy near 1. |
| [Spatial heterogeneity](features.md#spatial-heterogeneity) | Is motion uniform across the field of view? | `regional_speed_cv`, `regional_speed_spread`, `regional_coherence_sd`, `regional_moving_fraction` | A tissue with a migrating front and a static core has high regional variation. `regional_moving_fraction` tells how much of the field of view moves above your chosen speed. |
| [Quality control](features.md#quality-control) | Can I trust and compare these numbers? | `qc_reliable_fraction`, `qc_foreground_fraction`, `qc_object_mean_voxels`, `qc_brightness_change_per_frame` | Used to check comparability, never as a result. See [Quality control](#quality-control). |

Speed-weighted versus unweighted: `coherence_xy_global` gives fast voxels more weight, while the
angular features (`xy_angular_entropy`, `xy_angular_dispersion`, `xy_aligned_fraction`) count every
directed vector equally. If the two disagree, the fast-moving part of the field of view moves more
(or less) coherently than the slow part.

### Readouts, orientation descriptors and QC

Every column has a *use* in the glossary (and in `feature_dictionary.json` as `applicability`):

| Use | Given to MorphoCoverage? | Columns | Why |
|---|---|---|---|
| **readout** | Always | XY speed, `lateral_speed_mean`, XY coherence, angular entropy, dispersion and aligned fraction, regional columns | They describe the motion itself and do not change when the image is rotated, except the regional columns: their XY grid moves with the image, so compare samples imaged in a similar orientation. |
| **axial readout (experimental)** | Only when you tick *Also include experimental axial features* (a chosen axial readout is always included) | `vz_sd`, `vz_abs_mean`, `axial_lateral_ratio`, `coherence_3d_global`, `speed_3d_*` | Axial velocities are less reliable in shallow stacks (see pitfalls). |
| **orientation descriptor** | Never | every `vx_*` and `vy_*` column (`vx_mean`, `vx_sd`, `vx_abs_mean`, and the same for `vy`), `vz_mean`, `xy_dominant_direction_deg` | They depend on how the sample was placed under the microscope. Two identical samples rotated by 90° give different values, so they are not phenotypes. Use them only within one image, for example to check a known flow direction. |
| **quality control** | Never | every `qc_*` column | They describe the measurement (reliability, occupancy, object size, brightness), not the biology. Treating them as phenotypes would let imaging differences masquerade as effects. |

### Checking comparability

Before you believe a difference between conditions, check that the measurement was similar in
both. Compare these QC columns between conditions in `features_per_fov.csv` (or
`features_per_frame.csv` for time trends):

| Check | Column(s) | Why it matters |
|---|---|---|
| Similar reliability | `qc_reliable_fraction`, `qc_reliability_median` | If one condition has much less reliable flow, its features come from fewer, possibly different voxels. |
| Similar occupancy | `qc_foreground_fraction`, `qc_n_analysed_voxels` | Denser or sparser tissue changes what the foreground holds; with no foreground, background dominates sparse fields of view. |
| Similar object size | `qc_object_mean_voxels`, `qc_object_mean_z_extent` | **The optical-flow gain depends on nuclear size and axial extent.** If nuclei are larger in one condition, its speeds can differ even with identical motion. |
| Little brightness change | `qc_brightness_change_per_frame` | Brightening or bleaching is partly read as motion. Values above 0.02/frame are flagged. |
| Similar intensity (optional) | `qc_foreground_intensity_mean` | Brightness affects gradients and therefore reliability and noise. |
| Enough regions | `qc_n_regions_analysed` | Regional features from 2–3 regions are noisy. |

If a confounder differs, the comparison is not necessarily wrong, but you must say so and
consider whether it can explain the effect.

### Pitfalls

1. **Gain bias with object size.** On synthetic nuclei the 3D algorithm recovers only 0.5–0.85
   of the true XY speed and up to 1.7× the Z speed, and the factor depends on nuclear size and
   Z extent ([Validation](validation.md)). Speeds are relative. A change in nuclear size between
   conditions can look like a change in speed. Per-slice 2D flow is much closer to the true XY
   speed on anisotropic stacks, but still underestimates large displacements (about 30 % at
   5 px/frame).
2. **Large displacements are underestimated.** Lucas–Kanade follows small motions best. When
   nuclei move several pixels per frame, every mode underestimates. Shorter frame intervals help.
3. **Axial features are experimental.** In shallow stacks (fewer slices than the spatial kernel,
   19 with `xyzSig = 3`), upstream pads with the edge slices; axial velocities in the top and
   bottom slices are biased by 20–30 %. With no true axial motion, mean |vz| still has a noise
   floor (about 0.02 slices/frame on the synthetic demo), which dominates |vz| features of slowly
   moving samples once scaled to µm/min.
4. **Fields of view within a repeat are not independent.** Fields of view imaged on the same day
   share the same culture, staining and microscope state. A separation between conditions in the
   PCA or UMAP is not evidence that a treatment changes migration. The FOV-level randomization
   screen is exploratory. Only the paired test on biological-repeat means (3 or more repeats) says
   whether an effect repeats.
5. **Time points are not replicates.** Each field of view contributes one time-averaged profile.
6. **Orientation-dependent features are never readouts.** `vx_mean`, `vy_mean`, `vz_mean` and
   `xy_dominant_direction_deg` change with how the sample lies in the image.
7. **The foreground matters.** A threshold that is too low includes background (spurious,
   unreliable velocities); one that is too high keeps only bright nuclear cores. Check the
   foreground outlines in the [QC figures](#qc-figures). Whole-image measurement is
   exploratory.
8. **Reliability mode.** With `percentile`, the threshold adapts to each frame, so a fixed
   fraction of the foreground is always kept, even when the whole frame is unreliable. With
   `absolute`, one value applies to every field of view, which keeps the criterion identical
   across conditions.
9. **Undefined is not zero.** An empty cell means the value does not exist (for example no
   region with enough voxels, or 3D speed without a full calibration). The reason is in
   `undefined_features`. Never fill empty cells with 0 before your own analysis.
10. **Brightness correction is a choice.** `global_mean` and `histogram_match` reduce spurious
    motion from brightness changes, but they change the input of the optical flow. Use the same
    choice for every condition you compare (runs with different settings cannot be combined).

### A worked reading

Suppose the report shows that `drug` has a higher `coherence_xy_global` than `ctrl` (Cohen's d
large, higher in every biological repeat, paired test significant) and a similar
`speed_xy_median`. A careful reading:

1. Check QC: `qc_reliable_fraction`, `qc_object_mean_voxels` and `qc_brightness_change_per_frame`
   are similar in both conditions. Good.
2. Check the per-frame table: the coherence is high in every time point, not in one frame only.
3. Look at the QC flow figures of a few fields of view: vectors point the same way in `drug`.
4. Conclusion: nuclei move more collectively in `drug`, at a similar optical-flow speed. Report it
   as motion of the nuclear signal measured by optical flow, not as tracked cell migration.

## Limitations

The OpticalFlow3D Profiler is **experimental**. Real-data validation is pending: the accuracy
figures below come from synthetic nuclei and one real crop ([Validation](validation.md)).

### What optical flow can and cannot tell you

- **Intensity-pattern motion, not tracking.** Optical flow measures how the nuclear signal moves.
  There are no single-cell trajectories, no per-nucleus speeds and no identity across frames.
  Shape changes, division, brightness changes and noise also move the pattern.
- **Speeds carry a size-dependent gain bias.** On synthetic nuclei, the 3D algorithm recovers
  0.5–0.85 of the true XY speed and up to 1.7× the true Z speed; the factor depends on nuclear size
  and axial extent. On very anisotropic stacks with nuclei about 1.5 slices deep, 3D recovered only
  0.30–0.41× of the XY speed, which is why `auto` selects per-slice 2D flow there (0.91–0.95×).
  Physical units (µm/min) convert units but do not correct this bias. **Speeds are relative:**
  compare conditions imaged with the same settings and check the object-size QC columns.
- **Large displacements are underestimated.** Even per-slice 2D underestimates about 30 % at
  5 px/frame. For future acquisitions, motion at or below about 2 px/frame (shorter frame
  intervals) keeps the flow close to exact ([Validation](validation.md)).
- **Static frames give zero velocity, and directions are correct** on synthetic data; the
  response is close to linear in speed up to about 1 voxel/frame.

### Axial (Z) measurements are experimental

- The 3D smoothing kernels are isotropic in voxels and longer (19 voxels with `xyzSig = 3`) than a
  typical 11-slice stack. Upstream pads with the edge slices, and axial velocities in the top and
  bottom two slices are biased by 20–30 %.
- With no true axial motion, mean |vz| has a noise floor of about 0.02 slices/frame on the
  synthetic demo, which dominates |vz| features of slowly moving samples once scaled to µm/min.
- Axial features are given to MorphoCoverage only when you choose them, and the default speed is
  XY speed. In per-slice 2D mode there is no `vz` at all.

### Data and design

- **3D time-lapses only:** single-channel TZYX TIFF/OME-TIFF, one field of view per file. No 2D
  time-lapses, no multi-channel files (a channel is never chosen for you), no OME-Zarr, no
  multi-series files, no RGB.
- **The first and last `half` frames have no output** (3 each with `tSig = 1`), and movies need
  at least 7 frames with the default settings.
- **One axis order and one calibration per run.** Images acquired with different settings must
  be processed as separate runs. Runs can be combined in the analysis only if their optical-flow,
  feature and foreground settings, units and feature columns are identical.
- **Foreground is a single raw-intensity threshold** (or the whole image), the same for every
  field of view. There is no segmentation and no mask input.
- **The design step requires paired repeats.** MorphoCoverage receives the biological repeat as
  its `repeat_group`, and the app refuses a design unless you confirm that a repeat label means the
  same biological repeat in every condition and at least one repeat holds both the control and
  another condition.
- **Statistics:** fields of view within a biological repeat are not independent. The FOV-level
  randomization screen is exploratory; only the paired test on biological-repeat means (3 or more
  repeats) says whether an effect repeats.
- **Reusing earlier optical flow** is possible from Python only, not from a notebook widget
  ([Outputs](#reusing-earlier-optical-flow)).

### Resources

- **Memory:** about **11–12 GB of RAM** per 1840 × 1840 × 11 Z-stack (one time window is held at
  a time; measured 11.35 GB peak for a 7 × 11 × 1840 × 1840 uint16 window on a 4-vCPU machine).
- **Time:** about 12–15 minutes per 1840 × 1840 × 11 × 15 field of view on a 4-vCPU machine
  (83.5 s measured per optical-flow output, 9 outputs; the notebook's estimate is rough).
- **Disk:** 9.4 GB of float64 output per such field of view (4.7 GB as float32).
- **No tiling, GPU or multiprocessing**, and images are never downsampled. If the memory estimate
  exceeds the available memory, use a computer with more memory.
- The resource estimate in section 2 uses figures measured on the 3D algorithm, also in per-slice
  mode (which writes no `vz` files, so its output is smaller than estimated).

### Platforms

- The desktop installer is built and tested for **Linux x86-64 only**. Windows and macOS
  installers are not built; use Google Colab or a Python install there
  ([Installation](getting_started.md#installation)).
- On a remote Jupyter server, the report link (`127.0.0.1`) opens on your own computer; open
  `report.html` from the file browser instead.

### By design

These are deliberate choices, not missing features:

- Nothing is guessed: no axes, channels, calibration, conditions or replicates.
- Undefined values stay empty (NaN), never 0; invalid velocities are excluded, never zeroed.
- Intensities are never normalised for features or thresholds; brightness correction is opt-in
  and only changes the optical-flow input.
- No Z projection.
- Inputs are never modified; runs, flow results, QC figures and reports are never overwritten.
- The OpticalFlow3D code is used unchanged; the statistics are MorphoCoverage's.
