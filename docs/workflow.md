# Workflow: the notebook step by step

The notebook `OpticalFlow3D_Profiler.ipynb` has five sections. Run them **in order**, top to
bottom. Each section shows its widgets; buttons run the step and print the result (or a message
starting with ⚠️ that says what to fix) below them.

| Section | What you do | What is written |
|---|---|---|
| [0. Initialise](#section-0-initialise) | Install (Colab) and load the app; optionally mount Google Drive | nothing |
| [1. Load the data](#section-1-load-the-data) | Choose folders, look at an example image, confirm axes and calibration | nothing |
| [2. Choose the settings](#section-2-choose-the-settings-and-process-one-example) | Optical-flow and feature settings; estimate resources; process one example | `<results>/examples/<run>/` |
| [3. Process the experiment](#section-3-process-the-experiment) | Process every field of view | `<results>/<run>/` |
| [4. Analyse the results](#section-4-analyse-the-results) | Load runs, define the design, create the MorphoCoverage report | `<run>/analysis/<report name>/` |
| [Optional: synthetic demo](#optional-synthetic-demo) | Check an installation against a known answer | a new demo folder |

Every processing choice (calibration, optical-flow, foreground, reliability and feature settings)
is saved in the run folder (`run_manifest.json`); the design of a comparison (control, readout,
pairing, seed) is saved with its report (`analysis/<report>/design.json`). The QC-figure option of
section 3 only controls an optional export. So a result can always be traced back to its images
and settings ([Outputs](results.md#outputs-and-run-folder)).

---

## Version check (first cell)

The first cell checks the notebook's version. In the installed app it shows a link to the
**Welcome notebook**, which compares your version with the latest one. On Colab it asks for the
repository URL and compares the versions when you click **Test Connection**. This cell is
optional.

---

## Section 0: Initialise

1. **Install.** In the installed app or a local Python install, the packages are already there:
   the cell only loads the app. On Google Colab it installs the package and its pinned
   dependencies (a minute or two). The cell ends with `Ready.`
2. **Optional: mount Google Drive (Colab only).** Your Drive appears under
   `/content/gdrive/MyDrive`. Outside Colab the cell prints that there is nothing to mount.

See [Installation](getting_started.md#installation) for details.

---

## Section 1: Load the data

### Folders

| Field | What to enter |
|---|---|
| **Experiment folder** | The root of your MorphoBricks experiment folder ([Preparing your data](getting_started.md#preparing-your-data)). |
| **Results folder** | Where runs and reports are written. It must be **outside** the experiment folder. It is created when needed; existing results in it are never overwritten. |

### 1. Load the experiment

Click **1. Load the experiment**. The app:

1. reads the folder tree and refuses it with a named reason if it breaks a layout rule
   ([what is refused](getting_started.md#what-is-refused));
2. prints the number of fields of view and a table of **fields of view per condition and
   biological repeat**. Check that it matches your design;
3. opens a **random example image** and shows its header: condition, repeats, position, file
   name, format (OME-TIFF, ImageJ TIFF or TIFF), shape, header axes, pixel type, number of image
   series, file size, X/Y pixel size, Z spacing, frame interval, calibration source, and notes
   (for example units taken from defaults, or axes not named). The random seed is printed.

**Another example image** draws another random image (it can be the same one again), so you can
check that the images look alike. It also resets the axes and calibration fields to that image's header values.

### 2. Confirm axes and calibration

| Field | Meaning |
|---|---|
| **Confirmed axes (file order)** | The axis letters of the file, for example `TZYX`. Pre-filled when the header names every axis including `T`. Axes the header names cannot be changed ([rules](getting_started.md#3-axes-confirmation)). Single-channel videos only: a `C` axis of length 1 is accepted. |
| **X pixel size**, **Y pixel size**, **Z spacing** | Voxel size, in the **Length unit** (µm or nm). Pre-filled from the header; check each value. |
| **Frame interval** | Time between frames, in the **Time unit** (min, s or h). |

Leave a value empty when it is unknown: results then stay in pixels (slices) per frame. Nothing
is assumed ([calibration](getting_started.md#4-calibration)).

Click **2. Confirm axes and calibration**. The app:

1. validates the axes against the example's header;
2. checks **every image header** of the experiment with these axes (headers only). Unreadable
   files, wrong axes, several channels or series, and mixed pixel types are problems: the table
   of problem images is shown and you cannot continue. Different image sizes or header
   calibrations are shown as notes;
3. prints the confirmed dimensions, for example `{'T': 15, 'Z': 11, 'Y': 1840, 'X': 1840}`;
4. prints `WARNING:` lines for missing calibration (XY pixel size or frame interval unknown;
   Z spacing unknown) and an `ERROR:` line if the movie is shorter than the default time window
   (`The movie has N time points; tSig=1.0 needs at least 7.`). The confirmation itself goes
   through, but such a movie cannot be processed with that `tSig`;
5. shows a **preview** of the example on its raw intensity scale (no normalisation). Move the
   **Time point** and **Z slice** sliders to browse it. Use the colour bar to choose a foreground
   threshold for section 2.

---

## Section 2: Choose the settings and process one example

### Optical-flow settings

These are passed to the unchanged OpticalFlow3D code. The defaults are the original algorithm's.
See [How it works](theory.md#1-the-optical-flow-opticalflow3d) for what they do.

| Widget | Setting (`run_manifest.json`) | Default | Effect |
|---|---|---|---|
| **Optical flow** | `flow.mode` | `auto` | `auto`: 2D per slice when the Z spacing is more than 3× the XY pixel size, else 3D; needs the XY pixel size and Z spacing. `xy_per_slice`: upstream `calc_flow2D` on every Z slice separately (no `vz`, axial features undefined). `xyz`: upstream `calc_flow3D` on each Z-stack. The resolved mode is recorded. |
| **xyzSig (voxels)** | `flow.xyz_sig` | 3.0 | Spatial smoothing scale of the derivatives. Larger values follow larger, smoother patterns. |
| **tSig (frames)** | `flow.t_sig` | 1.0 | Temporal smoothing scale. Sets the time window: `6·tSig + 1` frames, made odd (7 with the default). Half a window is lost at each end of the movie. |
| **wSig (voxels)** | `flow.w_sig` | 4.0 | Size of the Gaussian neighbourhood over which each velocity is solved (Lucas–Kanade window). |
| **Brightness** | `flow.brightness_equalisation` | `none` | `none`: raw intensities. `global_mean` (opt-in): in each time window, every frame is scaled so that its mean equals the central frame's mean. `histogram_match` (opt-in): every frame's histogram is mapped onto the central frame's (non-linear). Applied **only to the optical-flow input**; features and the foreground threshold always use raw intensities. See [brightness correction](theory.md#7-brightness-change-and-optional-correction). |
| **Saved precision** | `flow.output_dtype` | `float64` | Precision of the saved velocity files. `float64` is what upstream returns; `float32` halves the disk use. Recorded as a deliberate choice. |

All three sigmas must be positive numbers.

### Feature settings

| Widget | Setting | Default | Effect |
|---|---|---|---|
| **Foreground** | `foreground.mode` | intensity threshold | **intensity threshold**: features are measured only in voxels whose raw intensity is strictly above the threshold, at the analysed time point. **none (whole image)**: exploratory; background and nuclear occupancy may influence the features (a warning is recorded). The optical flow itself is always computed on the whole image. |
| **Raw-intensity threshold** | `foreground.threshold` | empty | Required with the intensity-threshold foreground. One raw value for every field of view (never normalised). Choose it from the preview in section 1. |
| **Foreground name** | `object_set` | `Nuclei` | First part of every feature column name: `Nuclei__speed_xy_median`. It must start with a letter and use only letters, digits and single underscores; names reserved by MorphoBricks (`whole`, `cell`, `nucleus`, `cytoplasm`, `ring`, `expanded_nucleus`, identity names such as `condition`, `t`, `z`) and names with an `in` part are refused. Without a foreground, columns start with `whole__`. |
| **Reliability filter** | `features.reliability_mode` | `absolute` | `absolute`: keep voxels with reliability ≥ the value (one value for every field of view). `percentile`: in each frame, keep voxels at or above that percentile of the foreground reliability (the threshold then differs between frames and is recorded in `qc_reliability_threshold`). `none`: no filtering. |
| **Reliability value** | `features.reliability_value` | empty | Required unless the filter is `none`: an absolute threshold, or a percentile from 0 to 100. Look at `qc_reliability_median` / `p10` / `p90` of the example to choose it. |
| **Speed** | `features.speed_mode` | XY speed (recommended) | `xy`: speed from `vx`, `vy` (`speed_xy_*` columns). `xyz`: 3D speed (`speed_3d_*`, experimental; needs 3D flow and the full calibration, otherwise undefined). 3D speed with per-slice flow is refused. |
| **Region size (px)** | `features.region_size_px` | 128 | Side of the square XY regions of the [spatial-heterogeneity features](features.md#spatial-heterogeneity). At least 2. |
| **Local window (px)** | `features.local_window_px` | 15 | Side of the XY window of the local coherence (`coherence_xy_local`). At least 3. |
| **Moving-region threshold** | `features.motion_threshold` | empty (optional) | Speed, in feature units, above which a region counts as moving. Empty leaves `regional_moving_fraction` undefined. |
| **Also report intensity-based QC (opt-in)** | `features.intensity_features` | off | Adds `qc_foreground_intensity_mean`. |

These feature settings are fixed at their defaults in the notebook (they are recorded in
`run_manifest.json` and can be changed only from Python):

| Setting | Default | Meaning |
|---|---|---|
| `min_region_voxels` | 100 | A region with fewer analysed voxels has no regional value. |
| `angle_bins` | 36 | Angular resolution of `xy_angular_entropy`: kernel SD = 360°/36 = 10°. Allowed: 2 to 360. |
| `aligned_angle_deg` | 45 | Vectors within 45° of the dominant direction count as aligned. |
| `min_direction_speed` | 0 | XY speed above which a vector has a direction for the angular features (0: every nonzero vector). |
| `min_direction_vectors` | 20 | Fewer directed vectors make the angular features undefined. |
| `min_local_vectors` | 5 | Minimum analysed nonzero vectors in a local-coherence window. |

### Choosing a first reliability threshold

The reliability filter starts as `absolute` with an empty value, which must be filled before
anything is processed. A simple first procedure:

1. Set the filter to `none` and **Process the example** (exploration only).
2. Look at `qc_reliability_median`, `qc_reliability_p10` and `qc_reliability_p90` of the example
   (and at the log10 reliability panel of the [QC figures](results.md#qc-figures)).
3. Choose an `absolute` threshold below most foreground values, for example near the 10th
   percentile, and process the example again to check `qc_reliable_fraction`.
4. Use that one threshold for every condition of the experiment.

Without filtering (`none`), every finite velocity counts, including those in flat, textureless
areas where optical flow is poorly determined: use it to explore, and say so if you report it.

### Estimate resources

**Estimate resources** prints, for one field of view of the example's size:

```
9 optical-flow outputs per field of view; peak memory ≈ 11.2 GB; output ≈ 9.4 GB; time ≈ 13 min (rough).
```

(numbers for an 1840 × 1840 × 11 × 15 uint16 stack). It warns when the estimated memory is larger
than the memory currently available, or the output larger than the free disk space where results
go. Images are never downsampled automatically. The estimate uses figures measured on the 3D
algorithm (see [Limitations, resources](results.md#resources)).

### Process the example

**Process the example** runs optical flow and features on the example image only, into a new run
folder `<results>/examples/run-<date>-<time>/`. Progress bars show the time windows and the
feature frames with the time left. The app then prints the example's status and warnings and, if
it completed, shows:

- the image at the middle analysed time point and middle Z slice, with flow vectors (colour =
  direction), the XY speed map and the reliability map (velocities in pixels/frame);
- per-frame plots of the median speed, the global XY coherence, `qc_reliable_fraction` and
  `qc_brightness_change_per_frame`;
- a table of their time averages.

Adjust the settings and process the example again until the foreground, reliability and speeds
look plausible. Each click creates a new example run; earlier ones are kept.

---

## Section 3: Process the experiment

| Widget | Default | Effect |
|---|---|---|
| **Run name (optional)** | `run-<date>-<time>` (UTC) | Name of the new run folder inside the results folder. An existing, non-empty folder is refused: choose another name. |
| **Save QC figures of every FOV** | ticked | After processing, saves the [QC figures](results.md#qc-figures) in `<run>/qc/`. |

Click **Process the experiment**. With the settings of section 2, the app:

1. checks the settings **before creating the run folder** (sigmas, missing threshold or
   reliability value, incompatible choices, angle_bins): a refused setting leaves no folder, so
   you can fix it and click again with the same run name. Problems that can only be found while
   reading an image (for example a movie too short for `tSig`) are found per field of view during
   processing and recorded as that field of view's failure;
   then creates the run folder;
2. **claims the run folder** by creating `run_started.json`. A folder that already holds a run
   (finished, running or interrupted) is never entered again;
3. processes every field of view in `fov_uid` order. Progress bars show the fields of view, and
   for each one its optical-flow windows and feature frames, with the elapsed time and the time
   left;
4. lists every field of view with its status (`complete` or `failed`), warnings and message, and
   prints `N complete, M failed (listed above, never skipped).` A failure (for example running
   out of memory) is recorded and the run continues with the next field of view;
5. writes the feature tables `features_per_frame.csv` (every time point) and
   `features_per_fov.csv` (time averages), then the QC figures if ticked.

What is written, file by file: [Outputs and run folder](results.md#outputs-and-run-folder).

> **Reusing earlier optical flow.** The notebook always computes the optical flow afresh. To
> extract features again from the optical flow of an earlier run (for example with another
> foreground), use the Python function `run_experiment(..., reuse_from=<earlier run>)`; the earlier
> flow is reused only after its identity and file hashes are verified
> ([Outputs, reuse](results.md#reusing-earlier-optical-flow)).

---

## Section 4: Analyse the results

### 4a. Load the results

| Widget | Default | Effect |
|---|---|---|
| **Run folders** | empty = the run of section 3 | One run folder per line, to analyse earlier runs or combine several. |
| **Repeat labels mean the same biological repeat in every run** | unticked | See below. |

Click **Load the results**. The app reads `features/features_per_fov.csv` of each run and shows,
per condition, the number of biological repeats and fields of view.

Runs can be combined only when they are comparable. A run is refused when it has no feature
tables, when its units or feature columns differ from the first run's, when its optical-flow,
feature or foreground settings differ (the message names the settings), or when its features
were computed with other feature definitions or feature code (another app version: one column
name may then measure something else). A run extracted before this identity was recorded can be
loaded alone but not combined. The calibration values
may differ as long as the units are the same. The same field of view in two runs is refused.

**The shared-labels checkbox asserts something only you know.** Tick it only when the runs share
their biological repeats, for example control and treatment of one experiment day processed as
separate runs. The same repeat label in several runs then counts as **one** biological repeat, and
the app prints a warning for each merged label. Unticked, each run's repeats are its own: `rep1`
of run A and `rep1` of run B are two repeats. The software cannot check this.

### 4b. Experimental design

1. Click **Read the conditions**. The drop-downs are filled from the loaded results.
2. Choose:

| Widget | Default | Meaning |
|---|---|---|
| **Control** | first condition (alphabetical) | The condition every other condition is compared with. |
| **Readout** | a speed with values: `speed_3d_median`, else `speed_xy_median`, else `lateral_speed_mean`, else the first lateral feature with values (an experimental axial feature only when nothing else has values) | The main feature: it leads the report. Every declared feature is still tested alike. The list holds every readout feature with values, including the experimental axial ones; a chosen axial readout is always included. |
| **Also include experimental axial features** | unticked | Also give the Z-dependent features (`vz_*`, `axial_lateral_ratio`, `coherence_3d_global`, `speed_3d_*`) to MorphoCoverage. |
| **A biological-repeat label is the same repeat in every condition** | unticked | **Required.** Your confirmation that, for example, `rep1` of the control and `rep1` of the treatment were imaged the same day. MorphoCoverage pairs repeats across conditions only on this confirmation. |
| **Random seed** | 0 | Seed of every MorphoCoverage resampling, so the report is reproducible. |

3. Click **Confirm the design**. The app prints what MorphoCoverage will receive (number of
   fields of view, number of features, control, readout), lists features left out because they
   are undefined in every field of view, and shows the fields of view per condition and repeat
   group.

Only readout features (and axial ones on request) are given to MorphoCoverage. Orientation
descriptors (every `vx_*` and `vy_*` column, `vz_mean`, `xy_dominant_direction_deg`; the
[glossary](features.md) gives each column's use) and `qc_*` columns are never features
([why](results.md#readouts-orientation-descriptors-and-qc)).

The design is refused when the repeats are not confirmed as paired, the control is unknown, there
is only one condition, or no biological repeat holds both the control and another condition.

### 4c. HTML report

| Widget | Default | Effect |
|---|---|---|
| **Report name** | `report-1` | Folder name of the report, `<run>/analysis/<report name>/`. With several runs, the report goes into the first run folder (in path order). An existing report folder is refused. |

Click **Create the HTML report**. Progress bars show the design scan, the statistics and the HTML
page. The app prints a short summary from MorphoCoverage and a link **Open the report in a new
tab**:

- in the installed app or local Jupyter, the link opens `http://127.0.0.1:<port>/report.html`,
  served read-only from the report folder;
- on Google Colab, the link opens through Colab's proxy in a new window;
- on a remote Jupyter server, the `127.0.0.1` link opens on your own computer, not the server:
  open `report.html` from the file browser instead. The file path is printed under the link.

The report is MorphoCoverage's: Cohen's d on the fields of view, the exploratory FOV-level
randomization screen, the paired test on biological-repeat means (needs 3 or more repeats), the
interactive PCA/UMAP and a figure per feature. How to read it: [Interpreting results](results.md#interpreting-results).

---

## Optional: synthetic demo

Use it to confirm that a new installation works. It writes a synthetic experiment with a known
answer, runs every step and checks the results:

- `ctrl` nuclei move slowly (0.3 px/frame) in random directions;
- `drug` nuclei move twice as fast (0.6 px/frame), all within ±15° of +x.

There are 3 biological repeats × 2 fields of view per condition, plus one deliberately unreadable
TIFF whose failure must be recorded.

| Widget | Default | Effect |
|---|---|---|
| **New demo folder** | empty | A new, empty folder (a non-empty folder is refused). |
| **Small images (quick, ~3 min)** | ticked | 96 × 96 images with 14 nuclei. Unticked: 256 × 256 × 11 × 15 images with 80 nuclei (much slower). |

Click **Run the synthetic demo**. It shows a table of every expectation with its observed value
and PASS or FAIL, then `All expectations passed.` or `Some expectations FAILED.`, and a link to the
demo's MorphoCoverage report.

The checks cover the speed ratio, coherence, direction, axial drift and noise floor, the
MorphoCoverage verdict on coherence, the recording of the failing file, and verified reuse of the
optical flow in a second, whole-image run. The demo folder keeps every file: `experiment/`,
`ground_truth.json`, `results/run-threshold/` (with QC figures and `analysis/demo/report.html`),
`results/run-whole-image/`, `expectations.csv` and `demo_report.md`. The demo uses 3D flow,
calibration 0.65 / 0.65 / 2.0 µm and 1 min, reliability threshold 50 and intensity threshold 300.

---

## Next steps

- [Quality control](results.md#quality-control): what to check before trusting a comparison.
- [Interpreting results](results.md#interpreting-results): what each feature family tells you.
- [Outputs and run folder](results.md#outputs-and-run-folder): where everything is.

## Troubleshooting

The app stops with a plain message (starting with ⚠️ in the notebook) whenever an input cannot be
analysed as configured. Most messages name the problem and the fix. This page groups the common
ones by notebook section, as **Message → Cause → Fix**. Messages are quoted from the code; `…`
stands for the names or numbers of your data.

### Jump to

- [Installation and the notebook](#installation-and-the-notebook)
- [Section 1: loading the experiment](#section-1-loading-the-experiment)
- [Section 1: axes and calibration](#section-1-axes-and-calibration)
- [Section 2 and 3: settings and processing](#sections-2-and-3-settings-and-processing)
- [Memory, disk and time](#memory-disk-and-time)
- [Empty (undefined) features](#empty-undefined-features)
- [Section 4: loading runs, design and report](#section-4-loading-runs-design-and-report)
- [Synthetic demo](#synthetic-demo)

---

### Installation and the notebook

**Widgets do not appear, or a button does nothing.**
Run the cells in order, starting with **Section 0 → Install**: it creates the app that every later
cell uses. If you restarted the kernel, run Section 0 again (choices are not kept across
restarts). On Colab, the Install cell enables Colab's custom widget manager.

**`ImportError: ipywidgets is not installed`** (first cell).
You are not in the app's environment. Use the installed app, or install the requirements
([Installation](getting_started.md#option-3-python-from-the-repository)).

**`The vendored OpticalFlow3D file has been modified (SHA-256 …); reinstall the application.`**
The copy of the OpticalFlow3D code differs from the pinned file. Reinstall the app; do not edit
`_upstream/calc_flow.py`.

**Desktop installer for Windows or macOS.**
Only the Linux x86-64 installer is built. Use Google Colab or a Python install
([Installation](getting_started.md#installation)).

---

### Section 1: loading the experiment

| Message | Cause | Fix |
|---|---|---|
| `Give the experiment folder and the results folder.` | A field is empty. | Fill in both. |
| `The results folder must be outside the experiment folder.` | Results would be written inside your data. | Choose a folder outside the experiment folder. |
| `The experiment folder … does not exist.` | Wrong path (on Colab, Drive not mounted). | Check the path; on Colab, mount Drive and use `/content/gdrive/MyDrive/...`. |
| `No TIFF image was found in a leaf folder of …` | No `.tif`/`.tiff` in a leaf folder. | Check the folder and the file extensions. |
| `tiff_outside_leaf`, `invalid_name`, `case_conflict`, `duplicate_position_id`, `reserved_folder_name`, `image_named_as_mask`, `link_outside_folder`, `… max 3 levels`, `OME-Zarr images are not supported` | The folder breaks a layout rule. | See [What is refused](getting_started.md#what-is-refused). |
| `Load the experiment first.` | You clicked *Another example image* or *Confirm* before *Load the experiment*. | Click **1. Load the experiment** first. |
| `… could not be read as a TIFF file: …` | Corrupt or non-TIFF file with a TIFF extension. | Re-export the file, or remove it from the experiment. |

**The design table does not match my experiment.**
Check the folder names: every folder level is read as condition, biological repeat, technical
repeat in that order, and a missing level becomes `single`.

---

### Section 1: axes and calibration

**`Some images cannot be processed: …`**
The header check of every image found problems. The table above the message lists each image and
its problem. Typical problems:

| Problem text | Cause | Fix |
|---|---|---|
| `The axes have not been confirmed.` | The axes field is empty (the header did not name all axes). | Type the axis letters in file order, for example `TZYX`. |
| `Unknown axis letters: …` / `An axis letter is repeated …` | Invalid letters. | Use each of `T`, `Z`, `C`, `Y`, `X` at most once. |
| `N axis letters were given for an image with M dimensions …` | Wrong number of letters, or images with a different number of dimensions. | One letter per dimension; all images must have the same axes. |
| `The image has no T axis.` / `no Z axis` | 2D time-lapse, or a single Z-stack. | 3D optical flow needs a time-lapse of Z-stacks (TZYX). |
| `axes_contradict_header: … names its axes … in its header, but … was confirmed` | You confirmed a role that contradicts an axis the header names, or the header names an axis the app does not analyse (`… a dimension not analysed`). | Confirm the header's axes, or fix the file's metadata (for example re-save it in Fiji with the correct hyperstack dimensions). |
| `Y and X must be the last two axes of the file …` | The file stores another layout. | Re-save the file with Y and X last. |
| `The image has N channels; this tool analyses single-channel videos.` | Multi-channel file. | Save the nuclear channel alone (for example with Fiji). |
| `multiple_series: … holds N image series …` | Several positions or scenes in one file. | Save one field of view per file. |
| `The file stores samples per pixel (RGB or similar planar samples) …` | RGB image. | Save the nuclear channel as a greyscale TIFF. |
| `Images have different pixel types: …` | For example `uint8` and `uint16` mixed. | Convert all images to one pixel type. |

**`ERROR: The movie has N time points; tSig=… needs at least M.`**
The movie is shorter than one optical-flow window (7 frames with `tSig = 1`). It is printed after
confirmation in section 1, and stops the resource estimate and the processing. Use longer movies or
a smaller `tSig`.

**`A length calibration must be positive, not …`** (or `A time calibration …`)
A calibration value is zero, negative or `nan`. Enter a positive number, or leave the field empty
if unknown.

**`could not convert string to float: …`**
A calibration or threshold field holds text. Enter a plain number (use `.` as the decimal mark).

**`Header calibrations differ between images; one confirmed calibration is used for the whole run`**
(a note). Your images do not all state the same calibration. If they were acquired with different
settings, split them into separate experiments and runs.

**Calibration fields are empty after loading.**
The header states no usable calibration (plain TIFF, ImageJ unit `pixel`, or `finterval` without a
time unit). Enter the values from your acquisition records, or leave them empty: results then stay
in pixels (slices) per frame.

---

### Sections 2 and 3: settings and processing

| Message | Cause | Fix |
|---|---|---|
| `Confirm the axes and calibration in section 1 first.` | Section 1 was not confirmed. | Click **2. Confirm axes and calibration**. |
| `The flow mode 'auto' needs the XY pixel size and the Z spacing; enter them, or choose 'xyz' (3D) or 'xy_per_slice' (2D per slice).` | Calibration incomplete. | Enter the X pixel size and Z spacing in section 1, or choose a mode. |
| `Reliability mode 'absolute' needs a value.` (or `'percentile'`) | Reliability value empty. | Enter a threshold or a percentile, or choose `none`. |
| `A reliability percentile must be 0-100, not …` | Out of range. | Enter 0–100. |
| `The intensity-threshold foreground needs a threshold value.` | Threshold empty. | Enter a raw intensity (use the preview's colour bar), or choose *none (whole image)*. |
| `Object-set name … is not valid (for example Nuclei).` / `… is reserved by MorphoBricks; choose another.` | Invalid foreground name. | Use letters, digits and single underscores, starting with a letter; avoid reserved names (`whole`, `nucleus`, `cell`, `t`, `z`, …) and names with an `in` part. |
| `3D speed needs 3D optical flow; with per-slice 2D flow choose XY speed.` | Per-slice flow (chosen, or resolved by `auto`) with 3D speed. | Choose XY speed, or 3D optical flow. |
| `The optical-flow parameters must be positive numbers (…)` | A sigma is 0, negative or not finite. | Use positive values (defaults 3, 1, 4). |
| `region_size_px must be at least 2.` / `local_window_px must be at least 3.` | Too small. | Increase the value. |
| `… already exists and is not empty; choose another run name. Existing results are never overwritten.` | The run name is taken. | Choose another name, or leave it empty for a date-time name. |
| `… already holds a run, finished, running or interrupted (run_started.json or run_manifest.json) …` | The folder was already used (for example an interrupted run). | Start a new run with a new name. A run folder is never entered twice. |
| `The image has a single Z slice.` | 3D flow on a single-slice image. | 3D optical flow needs Z-stacks. |

**A field of view is `failed` in the section 3 table.**
Read its `message` column; the full traceback is in `<run>/logs/run.log`. The run continued with
the other fields of view. Common causes:
- `OpticalFlow3D refused the input: …`: the upstream code rejected the window;
- a brightness-equalisation error when a frame's mean intensity is not positive (choose
  `histogram_match` or `none`);
- a memory error (see below);
- a file that changed or became unreadable after section 1.

To process failed fields of view again, start a **new** run.

---

### Memory, disk and time

**`About X GB of memory is needed but only Y GB is available; the calculation will probably fail.`**
The resource estimate exceeds the available memory. Close other programs or use a computer with
more memory. The app never downsamples or tiles your images.

**The kernel died or JupyterLab disconnected during processing.**
Usually the computer ran out of memory. The run folder keeps its `run_started.json` without a
`run_manifest.json` and cannot be reused: start a new run (new name) after freeing memory. Fields
of view finished before the crash have complete flow folders, but there are no feature tables for
an interrupted run. From Python, a new run can reuse the verified flow of the interrupted one
([Outputs, reuse](results.md#reusing-earlier-optical-flow)).

**`The outputs need X GB but only Y GB of disk is free.`**
Free disk space, choose another results folder, or choose `float32` precision (half the size).

**Processing is very slow.**
Expect about 12–15 minutes per 1840 × 1840 × 11 × 15 field of view on 4 CPUs. There is no GPU or
multiprocessing. The progress bars show the time left.

---

### Empty (undefined) features

Empty cells are deliberate: the value does not exist. The reason is in `undefined_features`.

| Columns empty | Likely reason | Fix |
|---|---|---|
| Almost everything | No analysed voxel: the foreground is empty or nothing passes the reliability filter. | Lower the intensity threshold or the reliability value; check `qc_reliability_median` and the foreground figures. |
| `speed_3d_*`, `coherence_3d_global`, `axial_lateral_ratio` | Calibration incomplete (lateral and axial not both in µm/min). | Enter the full calibration. |
| Every `vz_*` and axial column | Per-slice 2D optical flow. | Expected; choose 3D if you need axial features. |
| `xy_angular_*`, `xy_aligned_fraction`, `xy_dominant_direction_deg` | Fewer than 20 analysed vectors with a direction. | More analysed voxels (foreground, reliability). |
| `coherence_xy_local` | No window with 5 analysed nonzero vectors. | More analysed voxels, or a larger local window. |
| `regional_speed_cv`, `regional_speed_spread`, `regional_coherence_sd` | Fewer than 2 full regions with 100 analysed voxels (the region size may exceed the image), or a zero mean/median regional speed. | Smaller region size. |
| `regional_moving_fraction` | No moving-region threshold set, or no region with 100 analysed voxels (one is enough). | Enter a threshold in section 2; a smaller region size. |
| `qc_foreground_fraction`, `qc_object_*` | No foreground (whole image). | Expected. |
| `qc_brightness_change_per_frame` | The central frame's mean intensity is not above 0. | Check the images. |
| `time_min` | No frame interval. | Enter it in section 1. |

---

### Section 4: loading runs, design and report

| Message | Cause | Fix |
|---|---|---|
| `List at least one run folder, or process the experiment first.` | Nothing to load. | Run section 3, or list run folders. |
| `… has no feature tables; extract features first.` | The run failed completely or is not a run folder. | List a completed run folder (the folder that contains `features/`). |
| `… has no run_manifest.json; its settings cannot be checked.` | Interrupted run or wrong folder. | List a completed run. |
| `… uses other units (…) than … ; runs cannot be combined.` | One run has a calibration (µm/min) and the other not (px/frame), or another frame interval unit. | Re-run with the same calibration. |
| `… has other feature columns than … (for example …): another speed mode or object-set name; runs cannot be combined.` | The runs used another foreground name, speed mode, or intensity QC. | Re-run with the same settings. |
| `… and … were computed with other feature definitions / feature code (another profiler version) …` | The runs come from different app versions. | Re-extract the features of every run with one version (new runs with `reuse_from` reuse their optical flow). |
| `… was extracted before runs recorded the identity of their feature definitions and code …` | An older run is combined with others. | Re-extract it with this version. |
| `sigma_too_large: The optical-flow parameters must be at most 10000 …` | A sigma above 10,000. | Use values of a few units (defaults 3, 1, 4). |
| `angle_bins must be at most 360 …` | A finer angular resolution than the entropy can compute. | Use 36 (default) up to 360. |
| `… was analysed with different settings from … (…); its features are not comparable.` | Optical-flow, feature or foreground settings differ (they are named). | Re-extract the features with the same settings. |
| `The same field of view appears in several runs: …` | The same images were processed in two listed runs. | Load only one of these runs. |
| `… and … are the same run folder; load it once.` | A folder listed twice. | Remove the duplicate line. |
| `Several columns share a feature key (two object sets in one table): …` | Runs with different foreground names. | Combine runs extracted with the same foreground name. |
| `Load the results first.` | Section 4a not done. | Click **Load the results**. |
| `Confirm that each biological-repeat label is the same biological repeat in every condition …` | The pairing box is not ticked. | Tick it if true. The app cannot analyse unpaired designs. |
| `Only one condition: nothing to compare with the control.` | One condition in the loaded results. | Load runs that hold several conditions. |
| `The control '…' is not one of …` / `The readout '…' is not a feature with values.` | Stale choice. | Click **Read the conditions** again. |
| `No biological repeat holds both the control and …` | No repeat label is shared between the control and that condition. With several runs, repeats are run-specific unless declared shared. | Tick *Repeat labels mean the same biological repeat in every run* if true, and reload; or rename repeat folders consistently. |
| `Several fields of view share condition, biological repeat, technical repeat and position_id after the runs were combined …` | Shared labels made two fields of view identical. | Load the runs without shared labels, or give them distinct labels. |
| `No feature has values in these results; nothing can be compared.` | Every feature is undefined. | See [Empty features](#empty-undefined-features). |
| `Confirm the experimental design first.` | Section 4b not confirmed. | Click **Confirm the design**. |
| `… exists; reports are never overwritten.` | The report name is taken. | Choose another report name. |

**The report link does not open.**
On a remote Jupyter server the `127.0.0.1` link points to your own computer. Open `report.html`
from the file browser instead (its path is printed under the link). In the installed app or local
Jupyter, the link is served only while the notebook's kernel is running.

---

### Synthetic demo

| Message or result | Cause | Fix |
|---|---|---|
| `Choose a new, empty folder.` | Folder field empty. | Enter a path to a new folder. |
| `… is not empty; the demo writes into a new folder.` | Existing content. | Choose a new folder. |
| `Some expectations FAILED.` | A check did not meet its expected range. | Open `demo_report.md` in the demo folder to see which check, its observed value and expected range. Report it with the run's `run_manifest.json`. |

---

Still stuck? Check the LabConstrictor guide for the installed app
([troubleshooting the installed app](../.tools/docs/troubleshooting_installed_app.md)) and open an
issue on the repository with the message, `fovs.csv`, `run_manifest.json` and `logs/run.log`.
