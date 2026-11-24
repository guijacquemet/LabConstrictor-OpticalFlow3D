# Getting started

[:arrow_left: Documentation index](index.md)

Install the app and prepare your images.

- [Installation](#installation)
- [Preparing your data](#preparing-your-data)

## Installation

There are three ways to run the OpticalFlow3D Profiler. They all run the same notebook,
`OpticalFlow3D_Profiler.ipynb`, with the same package and the same pinned dependencies.

| Option | Best for | Platforms |
|---|---|---|
| [Desktop app (installer)](#option-1-desktop-app-labconstrictor-installer) | Everyday use on your own computer, offline after installation | **Linux x86-64 only** is built (each release is tested before publication) |
| [Google Colab](#option-2-google-colab) | Trying the app without installing anything | Any browser |
| [Python from the repository](#option-3-python-from-the-repository) | Developers, servers, other operating systems | Python 3.11 |

### Requirements

- **Memory:** the optical flow is memory hungry. Plan about **11–12 GB of RAM** for an
  1840 × 1840 × 11 Z-stack (measured on a 4-vCPU machine). The notebook estimates memory, disk and
  time for your own images before you process them ([Workflow](workflow.md#estimate-resources)).
- **Disk:** about 9.4 GB of optical-flow output per 1840 × 1840 × 11 × 15 field of view with
  float64 velocities, 5.4 GB with float32 (the reliability volume keeps the upstream's precision:
  float32 in 3D, float64 per slice, so per-slice outputs are about 8.0 GB or 5.4 GB).
- **No GPU** is used, and none is needed.

### Option 1: desktop app (LabConstrictor installer)

The app is packaged with [LabConstrictor](https://doi.org/10.48550/arXiv.2603.10704) as a
desktop installer that sets up Python, JupyterLab and every dependency.

1. Download the installer from the
   [Releases page](https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D/releases) of the
   repository, once a release is published. Step-by-step instructions are in
   [Install the app locally](../.tools/docs/download_executable.md).
2. **Linux x86-64:** run the downloaded `.sh` file in a terminal:
   ```bash
   bash "OpticalFlow3D Profiler-<version>-Linux-x86_64.sh"
   ```
   and follow the prompts. The installer downloads the Python packages during installation.
   After that, the app works offline.
3. Start **OpticalFlow3D Profiler** from your applications menu. A terminal window opens and keeps
   JupyterLab running: leave it open. JupyterLab opens in your browser with the **Welcome
   notebook**.
4. Run the Welcome notebook's cell and click **Open the notebook** next to
   `OpticalFlow3D_Profiler`. More detail: [Open and use an app](../.tools/docs/notebook_usage.md).

> **Platforms.** Only the Linux x86-64 installer is built (`distribution.platforms:
> [linux-x86_64]` in `labconstrictor-app.yaml`). Release 0.1.0 was installed and run on Linux;
> every new release is tested again before it is published. The code is pure Python and should run on
> Windows and macOS, but those installers are not built. On those systems, use
> [Google Colab](#option-2-google-colab) or [Python](#option-3-python-from-the-repository).

In the installed app, the notebook's first cell (**check this notebook's version**) shows a link
to the Welcome notebook, which tells you whether a newer notebook version exists.

### Option 2: Google Colab

1. Open `notebooks/OpticalFlow3D_Profiler/OpticalFlow3D_Profiler.ipynb` from the repository in
   [Google Colab](https://colab.research.google.com/) (File → Open notebook → GitHub).
2. *(Optional)* The first cell checks the notebook's version: give the repository URL
   (`https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D`) and click **Test Connection**.
3. Run **Section 0 → Install**. On Colab it installs the app from GitHub together with the
   pinned versions of MorphoCoverage, morphobricks-normalization and tqdm (a minute or two):
   ```
   pip install "git+https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D" \
     "morphocoverage @ git+https://github.com/CellMigrationLab/MorphoCoverage@209b9be40a14aef5a5e244a8d031a4828f1e96ef" \
     "tqdm==4.70.1" \
     "morphobricks-normalization @ git+https://github.com/CellMigrationLab/morphobricks-normalization@26112a5b5019d3c1af91450aeabf623a05d6ba36"
   ```
   It ends by printing `Ready.`
4. *(Optional)* Run **Mount Google Drive (Colab only)** to reach your images. Your Drive then
   appears under `/content/gdrive/MyDrive`; use paths below it for the experiment and results
   folders.

Colab notes:
- Choose a results folder **on your Drive**. Files written elsewhere in the Colab machine are lost
  when the session ends.
- Free Colab machines have limited memory. Check the resource estimate in section 2 before you
  process large stacks.
- The MorphoCoverage report opens through Colab's own proxy in a new window
  ([Workflow, section 4c](workflow.md#4c-html-report)).

### Option 3: Python from the repository

The package needs **Python 3.11** (`python_requires=">=3.11"`; the app is built and tested with
Python 3.11.13). The exact dependency list is `requirements.txt`, generated from
`notebooks/OpticalFlow3D_Profiler/requirements.yaml`; `requirements.lock.txt` pins every package
the installer installs.

```bash
git clone https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D
cd LabConstrictor-OpticalFlow3D
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt   # pinned dependencies, incl. MorphoCoverage from GitHub
python -m pip install .                     # the opticalflow3d_profiler package (src/)
python -m pip install jupyterlab
jupyter lab notebooks/OpticalFlow3D_Profiler/OpticalFlow3D_Profiler.ipynb
```

`requirements.txt` is needed because MorphoCoverage and morphobricks-normalization are installed
from pinned Git commits, which the package metadata alone does not install.

Then run the notebook from Section 0. Outside Colab, the **Install** cell only prints
`Local Jupyter: the packages come with the installed app.` and loads the widgets.

#### Check the installation

- In the notebook: run the optional [synthetic demo](workflow.md#optional-synthetic-demo).
- From a terminal, in the repository folder:
  ```bash
  python tools/demo_synthetic.py /path/to/new/empty/folder --small
  ```
  It writes a synthetic experiment, runs every step and writes `demo_report.md` with PASS or FAIL
  for each expectation. It exits with code 1 if an expectation fails.
- Developers: `python tools/check_profiler.py` runs Ruff, the code-size rules and the test suite.

### Pinned versions

| Component | Pinned version |
|---|---|
| OpticalFlow3D (vendored, unchanged) | commit `6b88604` of aicjanelia/OpticalFlow3D; the app refuses to run if the file's SHA-256 differs |
| MorphoCoverage | commit `209b9be40a14aef5a5e244a8d031a4828f1e96ef` |
| morphobricks-normalization | commit `26112a5b5019d3c1af91450aeabf623a05d6ba36` |
| Python | 3.11.13 |

Every run records the versions it actually used (Python, platform, each dependency with its Git
commit when installed from Git) in `run_manifest.json` ([Outputs](results.md#run_manifestjson)).

## Preparing your data

The app reads a **MorphoBricks experiment folder**: the folder names give the condition and the
repeats, and each image is one field of view. This page explains the layout, the image format,
and how axes and calibration are confirmed. The folder layout and every image **header** (axes,
shape, pixel type, header calibration) are checked **before** any computation; what depends on
an image's length and the chosen optical-flow settings (for example enough time points for
`tSig`) is checked per field of view when it is processed, and a failing field of view is
recorded as failed, never skipped silently. When something is wrong, the app stops with a message
that names the problem; it never guesses.

### 1. Folder layout

```
<experiment root>/<condition>/<biological repeat>/<technical repeat>/<image>.tif
```

Example:

```
my_experiment/
├── control/
│   ├── rep1/
│   │   ├── fov1.tif
│   │   └── fov2.tif
│   └── rep2/
│       └── fov1.tif
└── drug/
    ├── rep1/
    │   └── fov1.tif
    └── rep2/
        └── fov1.tif
```

Rules:

- **Images live in leaf folders only.** A leaf folder holds images and no subfolders.
- **Every level is optional.** A missing level is recorded as `single`. In the example above,
  there is no technical-repeat level, so every image gets `technical_repeat = single`. A single
  folder of images gives `single / single / single`.
- **At most three folder levels** (condition, biological repeat, technical repeat).
- **`position_id`** is the image name without `.tif` / `.tiff` (any case), including a preceding
  `.ome`: `fov1.ome.tif` → `fov1`.
- A field of view is identified by `condition`, `biological_repeat`, `technical_repeat` and
  `position_id`. The app also gives each field of view a stable identifier, `fov_uid`
  (a readable name plus 8 hexadecimal digits, for example `control_rep1_single_fov1-1a2b3c4d`),
  used for its folders in the run.
- **Name biological repeats consistently across conditions.** The statistics pair `rep1` of the
  control with `rep1` of the treatment only when you confirm that they are the same repeat
  (for example imaged on the same day). See [Workflow, section 4b](workflow.md#4b-experimental-design).
- **Ignored:** hidden files and folders (names starting with `.`), `Thumbs.db`, `desktop.ini`
  and `__MACOSX`. Files that are not TIFFs are not listed.
- **The results folder must be outside the experiment folder.**

#### What is refused

| Message starts with | Cause | Fix |
|---|---|---|
| `tiff_outside_leaf` | A folder holds both images and subfolders. | Move the images into a subfolder, or remove the subfolders. |
| `invalid_name` | A folder or image name has spaces at its start or end, or reads as a missing value (`NA`, `nan`, `none`, `null`, `n/a`, `<na>`, empty). | Rename it. |
| `case_conflict` | Two folders of one level differ only in case anywhere in the experiment (`Control` and `control`). | Use one spelling. |
| `duplicate_position_id` | Two images of one leaf folder have the same name ignoring case (`fov1.tif` and `FOV1.tiff`). | Rename one of them. |
| `reserved_folder_name` | A folder named `single` in another case (`Single`), or beside other folders. | `single` is accepted only in lower case and as the only folder in its place. |
| `image_named_as_mask` | An image is named as a mask of another image of the same folder (`fov1_mask.tif` beside `fov1.tif`; also `_masks`, `_cp_masks`, `_labels`, `_label`, `_seg`, `_segmentation`). | Masks are not used: remove the file from the experiment. |
| `link_outside_folder` | A symbolic link points outside the experiment folder. | Copy the data into the experiment folder. |
| `... is below the technical-repeat level (max 3 levels)` | More than three folder levels. | Flatten the folder tree. |
| `OME-Zarr images are not supported` | A `.zarr` entry. | Convert to OME-TIFF. |
| `No TIFF image was found in a leaf folder` | Empty experiment, or a wrong path. | Check the folder. |

The MorphoBricks description files (`morphobricks.toml`, `experiment_design.csv`) are not read.
More on the conventions: [MorphoBricks conventions](morphobricks.md).

### 2. Image format

| Requirement | Detail |
|---|---|
| File type | TIFF or OME-TIFF (`.tif`, `.tiff`, `.ome.tif`, `.ome.tiff`). |
| One field of view per file | Only the first image series is read; a file with several series (positions or scenes) is refused (`multiple_series`). |
| Single channel | A `C` axis is accepted only with length 1 (`multi_channel_not_supported`). Save the nuclear channel alone, for example with Fiji. |
| Axes | `T`, `Z`, `Y` and `X` are all required (a 2D time-lapse without Z is refused, even for per-slice 2D optical flow). Allowed letters: `T`, `Z`, `C`, `Y`, `X`. |
| Layout | `Y` and `X` must be the last two axes (each TIFF page is an XY plane). |
| Greyscale | Files with samples per pixel (RGB) are refused. |
| Same pixel type | All images of the experiment must have the same pixel type (for example all `uint16`). Different image sizes are allowed and reported as a note. |
| Enough time points | At least `6·tSig + 1` frames, made odd: **7** with the default `tSig = 1` (`too_few_frames`). |
| Z slices | 3D optical flow needs at least 2 slices (`single_z`). A stack shorter than the spatial kernel (`2·ceil(3·xyzSig) + 1` = 19 slices with the default `xyzSig = 3`) gives a `shallow_z` warning: axial velocities are then experimental. |

Your files are only read; the app never writes into the experiment folder.

### 3. Axes confirmation

The notebook opens a **random example image** and shows what its header says (shape, header axes,
pixel type, number of series, file size, calibration, notes). You then type the axis letters in
**file order**, for example `TZYX`.

- When the header names every axis with `T`, `Z`, `C`, `Y` or `X` and includes `T`, the field is
  pre-filled with the header's axes. Otherwise it is left empty and the header table says
  `(not named: confirm)`.
- **An axis the header names keeps its role.** You may only choose the role of axes the header
  leaves unknown (tifffile shows them as `Q` or `I`). If the header says `ZCYX` you cannot confirm
  `TZYX`: Z planes read as time points would give false velocities. An axis the header names with
  any other letter (`E`, `H`, `A`, `R`, `0`, …) is a dimension the app does not analyse, so such a
  file is refused too. The refusal starts with `axes_contradict_header`. Fix the file's metadata instead (for example, re-save it in Fiji with
  the correct hyperstack dimensions).
- One axis order is confirmed for the **whole run**. On **Confirm**, every image header of the
  experiment is checked against it (headers only, no pixels read). If any image cannot be
  processed, the table of problem images is shown and nothing is computed.

### 4. Calibration

The calibration converts velocities to µm/min. Four values are needed:

| Value | Used for |
|---|---|
| X pixel size, Y pixel size | Lateral (XY) speeds in µm/min |
| Z spacing | Axial (Z) speeds in µm/min; the `auto` flow mode |
| Frame interval | Every speed in µm/min; the `time_min` column |

#### Header suggestion

The fields are pre-filled from the example image's header, converted to µm and minutes. They are
a **suggestion only**: check each value before you confirm.

- **OME-TIFF:** `PhysicalSizeX/Y/Z` and `TimeIncrement` of the first image, with their units. When
  a unit is not stated, the OME schema default is used (µm for sizes, s for the time increment)
  and a note says so: `Units taken from the OME schema defaults: ... Check these values before
  confirming.`
- **ImageJ TIFF:** `XResolution` / `YResolution` with the header's length unit, `spacing` for Z,
  and `finterval` for time. `finterval` is used **only when the header states its time unit**;
  otherwise a note asks you to enter the frame interval yourself. A header whose unit is
  `pixel` gives no physical size.
- **Plain TIFF:** no suggestion (`The header states no calibration.`).
- Accepted units: nm, µm (um, micron), mm; ms, s (sec), min, h. A value that is not a positive
  number, or has another unit, is not used and is named in a note.

#### What you confirm

- Enter values with the **Length unit** (µm or nm) and **Time unit** (min, s or h) drop-downs.
- **Leave a value empty when it is unknown.** Nothing is assumed: results then stay in
  pixels/frame (lateral) or slices/frame (axial), and features that need a common physical unit
  (3D speed, 3D coherence, axial/lateral ratio) are undefined with a reason. The `auto` flow mode
  also needs the XY pixel size and the Z spacing.
- **One confirmed calibration per run.** If the headers of your images state different
  calibrations, the app shows a note: process images acquired with different settings as
  separate runs. During processing, a field of view whose header differs by more than 1 % from
  the confirmed value gets a warning in `fovs.csv`, for example
  `The header states pixel_size_x=0.65 but 0.5 was used.`
- The confirmed calibration is recorded in `run_manifest.json`, with missing values listed under
  `calibration_issues`.

### 5. Checklist before you start

- [ ] One single-channel TZYX TIFF/OME-TIFF per field of view, in leaf folders.
- [ ] Conditions and biological repeats named consistently (same repeat label = same repeat in
      every condition, if that is your design).
- [ ] At least 7 time points (default settings); preferably several more, since the first and
      last 3 have no output.
- [ ] All images acquired with the same settings (pixel type, calibration).
- [ ] A results folder outside the experiment folder, with enough free disk space.
