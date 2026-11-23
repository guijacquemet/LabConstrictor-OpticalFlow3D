# Workflow: the notebook step by step

[:arrow_left: Documentation index](index.md)

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

Every choice is saved in the run folder (`run_manifest.json`), so a result can always be traced
back to its images and settings ([Outputs](outputs.md)).

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

See [Installation](installation.md) for details.

---

## Section 1: Load the data

### Folders

| Field | What to enter |
|---|---|
| **Experiment folder** | The root of your MorphoBricks experiment folder ([Preparing your data](data_preparation.md)). |
| **Results folder** | Where runs and reports are written. It must be **outside** the experiment folder. It is created when needed; existing results in it are never overwritten. |

### 1. Load the experiment

Click **1. Load the experiment**. The app:

1. reads the folder tree and refuses it with a named reason if it breaks a layout rule
   ([what is refused](data_preparation.md#what-is-refused));
2. prints the number of fields of view and a table of **fields of view per condition and
   biological repeat**. Check that it matches your design;
3. opens a **random example image** and shows its header: condition, repeats, position, file
   name, format (OME-TIFF, ImageJ TIFF or TIFF), shape, header axes, pixel type, number of image
   series, file size, X/Y pixel size, Z spacing, frame interval, calibration source, and notes
   (for example units taken from defaults, or axes not named). The random seed is printed.

**Another example image** opens a different random image, so you can check that the images look
alike. It also resets the axes and calibration fields to that image's header values.

### 2. Confirm axes and calibration

| Field | Meaning |
|---|---|
| **Confirmed axes (file order)** | The axis letters of the file, for example `TZYX`. Pre-filled when the header names every axis including `T`. Axes the header names cannot be changed ([rules](data_preparation.md#3-axes-confirmation)). Single-channel videos only: a `C` axis of length 1 is accepted. |
| **X pixel size**, **Y pixel size**, **Z spacing** | Voxel size, in the **Length unit** (µm or nm). Pre-filled from the header; check each value. |
| **Frame interval** | Time between frames, in the **Time unit** (min, s or h). |

Leave a value empty when it is unknown: results then stay in pixels (slices) per frame. Nothing
is assumed ([calibration](data_preparation.md#4-calibration)).

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
| `angle_bins` | 36 | Angular resolution of `xy_angular_entropy`: kernel SD = 360°/36 = 10°. |
| `aligned_angle_deg` | 45 | Vectors within 45° of the dominant direction count as aligned. |
| `min_direction_speed` | 0 | XY speed above which a vector has a direction for the angular features (0: every nonzero vector). |
| `min_direction_vectors` | 20 | Fewer directed vectors make the angular features undefined. |
| `min_local_vectors` | 5 | Minimum analysed nonzero vectors in a local-coherence window. |

### Estimate resources

**Estimate resources** prints, for one field of view of the example's size:

```
9 optical-flow outputs per field of view; peak memory ≈ 11.2 GB; output ≈ 9.4 GB; time ≈ 13 min (rough).
```

(numbers for an 1840 × 1840 × 11 × 15 uint16 stack). It warns when the estimated memory is larger
than the memory currently available, or the output larger than the free disk space where results
go. Images are never downsampled automatically. The estimate uses figures measured on the 3D
algorithm (see [Limitations, resources](limitations.md#resources)).

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
| **Save QC figures of every FOV** | ticked | After processing, saves the [QC figures](qc.md#qc-figures) in `<run>/qc/`. |

Click **Process the experiment**. With the settings of section 2, the app:

1. creates the run folder, then checks the settings (missing threshold or reliability value,
   incompatible choices) before writing any file in it. If the settings are refused, fix them and
   click again with **another run name** (or an empty name): the folder already created counts as
   used;
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

What is written, file by file: [Outputs and run folder](outputs.md).

> **Reusing earlier optical flow.** The notebook always computes the optical flow afresh. To
> extract features again from the optical flow of an earlier run (for example with another
> foreground), use the Python function `run_experiment(..., reuse_from=<earlier run>)`; the earlier
> flow is reused only after its identity and file hashes are verified
> ([Outputs, reuse](outputs.md#reusing-earlier-optical-flow)).

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
tables, when its units or feature columns differ from the first run's, or when its optical-flow,
feature or foreground settings differ (the message names the settings). The calibration values
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
| **Readout** | median speed (`speed_3d_median` when it has values, else `speed_xy_median`) | The main feature: it leads the report. Every declared feature is still tested alike. The list holds every readout feature with values, including the experimental axial ones; a chosen axial readout is always included. |
| **Also include experimental axial features** | unticked | Also give the Z-dependent features (`vz_*`, `axial_lateral_ratio`, `coherence_3d_global`, `speed_3d_*`) to MorphoCoverage. |
| **A biological-repeat label is the same repeat in every condition** | unticked | **Required.** Your confirmation that, for example, `rep1` of the control and `rep1` of the treatment were imaged the same day. MorphoCoverage pairs repeats across conditions only on this confirmation. |
| **Random seed** | 0 | Seed of every MorphoCoverage resampling, so the report is reproducible. |

3. Click **Confirm the design**. The app prints what MorphoCoverage will receive (number of
   fields of view, number of features, control, readout), lists features left out because they
   are undefined in every field of view, and shows the fields of view per condition and repeat
   group.

Only readout features (and axial ones on request) are given to MorphoCoverage. Orientation
descriptors (`vx_mean`, `vy_mean`, `vz_mean`, `xy_dominant_direction_deg`) and `qc_*` columns are
never features ([why](concepts.md#readouts-orientation-descriptors-and-qc)).

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
interactive PCA/UMAP and a figure per feature. How to read it: [Interpreting results](concepts.md).

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

- [Quality control](qc.md): what to check before trusting a comparison.
- [Interpreting results](concepts.md): what each feature family tells you.
- [Outputs and run folder](outputs.md): where everything is.
