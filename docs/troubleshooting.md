# Troubleshooting

[:arrow_left: Documentation index](index.md)

The app stops with a plain message (starting with ⚠️ in the notebook) whenever an input cannot be
analysed as configured. Most messages name the problem and the fix. This page groups the common
ones by notebook section, as **Message → Cause → Fix**. Messages are quoted from the code; `…`
stands for the names or numbers of your data.

## Jump to

- [Installation and the notebook](#installation-and-the-notebook)
- [Section 1: loading the experiment](#section-1-loading-the-experiment)
- [Section 1: axes and calibration](#section-1-axes-and-calibration)
- [Section 2 and 3: settings and processing](#sections-2-and-3-settings-and-processing)
- [Memory, disk and time](#memory-disk-and-time)
- [Empty (undefined) features](#empty-undefined-features)
- [Section 4: loading runs, design and report](#section-4-loading-runs-design-and-report)
- [Synthetic demo](#synthetic-demo)

---

## Installation and the notebook

**Widgets do not appear, or a button does nothing.**
Run the cells in order, starting with **Section 0 → Install**: it creates the app that every later
cell uses. If you restarted the kernel, run Section 0 again (choices are not kept across
restarts). On Colab, the Install cell enables Colab's custom widget manager.

**`ImportError: ipywidgets is not installed`** (first cell).
You are not in the app's environment. Use the installed app, or install the requirements
([Installation](installation.md#option-3-python-from-the-repository)).

**`The vendored OpticalFlow3D file has been modified (SHA-256 …); reinstall the application.`**
The copy of the OpticalFlow3D code differs from the pinned file. Reinstall the app; do not edit
`_upstream/calc_flow.py`.

**Desktop installer for Windows or macOS.**
Only the Linux x86-64 installer is built. Use Google Colab or a Python install
([Installation](installation.md)).

---

## Section 1: loading the experiment

| Message | Cause | Fix |
|---|---|---|
| `Give the experiment folder and the results folder.` | A field is empty. | Fill in both. |
| `The results folder must be outside the experiment folder.` | Results would be written inside your data. | Choose a folder outside the experiment folder. |
| `The experiment folder … does not exist.` | Wrong path (on Colab, Drive not mounted). | Check the path; on Colab, mount Drive and use `/content/gdrive/MyDrive/...`. |
| `No TIFF image was found in a leaf folder of …` | No `.tif`/`.tiff` in a leaf folder. | Check the folder and the file extensions. |
| `tiff_outside_leaf`, `invalid_name`, `case_conflict`, `duplicate_position_id`, `reserved_folder_name`, `image_named_as_mask`, `link_outside_folder`, `… max 3 levels`, `OME-Zarr images are not supported` | The folder breaks a layout rule. | See [What is refused](data_preparation.md#what-is-refused). |
| `Load the experiment first.` | You clicked *Another example image* or *Confirm* before *Load the experiment*. | Click **1. Load the experiment** first. |
| `… could not be read as a TIFF file: …` | Corrupt or non-TIFF file with a TIFF extension. | Re-export the file, or remove it from the experiment. |

**The design table does not match my experiment.**
Check the folder names: every folder level is read as condition, biological repeat, technical
repeat in that order, and a missing level becomes `single`.

---

## Section 1: axes and calibration

**`Some images cannot be processed: …`**
The header check of every image found problems. The table above the message lists each image and
its problem. Typical problems:

| Problem text | Cause | Fix |
|---|---|---|
| `The axes have not been confirmed.` | The axes field is empty (the header did not name all axes). | Type the axis letters in file order, for example `TZYX`. |
| `Unknown axis letters: …` / `An axis letter is repeated …` | Invalid letters. | Use each of `T`, `Z`, `C`, `Y`, `X` at most once. |
| `N axis letters were given for an image with M dimensions …` | Wrong number of letters, or images with a different number of dimensions. | One letter per dimension; all images must have the same axes. |
| `The image has no T axis.` / `no Z axis` | 2D time-lapse, or a single Z-stack. | 3D optical flow needs a time-lapse of Z-stacks (TZYX). |
| `axes_contradict_header: … names its axes … in its header, but … was confirmed` | You confirmed a role that contradicts an axis the header names. | Confirm the header's axes, or fix the file's metadata (for example re-save it in Fiji with the correct hyperstack dimensions). |
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

## Sections 2 and 3: settings and processing

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

## Memory, disk and time

**`About X GB of memory is needed but only Y GB is available; the calculation will probably fail.`**
The resource estimate exceeds the available memory. Close other programs or use a computer with
more memory. The app never downsamples or tiles your images.

**The kernel died or JupyterLab disconnected during processing.**
Usually the computer ran out of memory. The run folder keeps its `run_started.json` without a
`run_manifest.json` and cannot be reused: start a new run (new name) after freeing memory. Fields
of view finished before the crash have complete flow folders, but there are no feature tables for
an interrupted run. From Python, a new run can reuse the verified flow of the interrupted one
([Outputs, reuse](outputs.md#reusing-earlier-optical-flow)).

**`The outputs need X GB but only Y GB of disk is free.`**
Free disk space, choose another results folder, or choose `float32` precision (half the size).

**Processing is very slow.**
Expect about 12–15 minutes per 1840 × 1840 × 11 × 15 field of view on 4 CPUs. There is no GPU or
multiprocessing. The progress bars show the time left.

---

## Empty (undefined) features

Empty cells are deliberate: the value does not exist. The reason is in `undefined_features`.

| Columns empty | Likely reason | Fix |
|---|---|---|
| Almost everything | No analysed voxel: the foreground is empty or nothing passes the reliability filter. | Lower the intensity threshold or the reliability value; check `qc_reliability_median` and the foreground figures. |
| `speed_3d_*`, `coherence_3d_global`, `axial_lateral_ratio` | Calibration incomplete (lateral and axial not both in µm/min). | Enter the full calibration. |
| Every `vz_*` and axial column | Per-slice 2D optical flow. | Expected; choose 3D if you need axial features. |
| `xy_angular_*`, `xy_aligned_fraction`, `xy_dominant_direction_deg` | Fewer than 20 analysed vectors with a direction. | More analysed voxels (foreground, reliability). |
| `coherence_xy_local` | No window with 5 analysed nonzero vectors. | More analysed voxels, or a larger local window. |
| `regional_*` | Fewer than 2 full regions with 100 analysed voxels; the region size may exceed the image. | Smaller region size. |
| `regional_moving_fraction` | No moving-region threshold set. | Enter one in section 2. |
| `qc_foreground_fraction`, `qc_object_*` | No foreground (whole image). | Expected. |
| `qc_brightness_change_per_frame` | The central frame's mean intensity is not above 0. | Check the images. |
| `time_min` | No frame interval. | Enter it in section 1. |

---

## Section 4: loading runs, design and report

| Message | Cause | Fix |
|---|---|---|
| `List at least one run folder, or process the experiment first.` | Nothing to load. | Run section 3, or list run folders. |
| `… has no feature tables; extract features first.` | The run failed completely or is not a run folder. | List a completed run folder (the folder that contains `features/`). |
| `… has no run_manifest.json; its settings cannot be checked.` | Interrupted run or wrong folder. | List a completed run. |
| `… uses other units (…) than … ; runs cannot be combined.` | One run has a calibration (µm/min) and the other not (px/frame), or another frame interval unit. | Re-run with the same calibration. |
| `… has other feature columns than … (for example …): another speed mode or object-set name; runs cannot be combined.` | The runs used another foreground name, speed mode, or intensity QC. | Re-run with the same settings. |
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

## Synthetic demo

| Message or result | Cause | Fix |
|---|---|---|
| `Choose a new, empty folder.` | Folder field empty. | Enter a path to a new folder. |
| `… is not empty; the demo writes into a new folder.` | Existing content. | Choose a new folder. |
| `Some expectations FAILED.` | A check did not meet its expected range. | Open `demo_report.md` in the demo folder to see which check, its observed value and expected range. Report it with the run's `run_manifest.json`. |

---

Still stuck? Check the LabConstrictor guide for the installed app
([troubleshooting the installed app](../.tools/docs/troubleshooting_installed_app.md)) and open an
issue on the repository with the message, `fovs.csv`, `run_manifest.json` and `logs/run.log`.
