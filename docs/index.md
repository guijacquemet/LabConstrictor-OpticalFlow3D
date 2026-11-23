# OpticalFlow3D Profiler documentation

The OpticalFlow3D Profiler measures how nuclei move in 3D fluorescence time-lapses. It runs the
original [OpticalFlow3D](https://github.com/aicjanelia/OpticalFlow3D) algorithm on every field of
view, turns the velocity fields into motion features, and compares your experimental conditions
with [MorphoCoverage](https://github.com/CellMigrationLab/MorphoCoverage).

> **Status: experimental.** Speeds are optical-flow speeds of intensity patterns, with a
> size-dependent gain bias. They are not tracked nuclear displacements. Read
> [Limitations](results.md#limitations) before you interpret a result.

## Choose your page

| You want to… | Read |
|---|---|
| Install the app and organise your images | [Getting started](getting_started.md) |
| Run the notebook, section by section (every setting explained), or fix an error | [Workflow](workflow.md) |
| Know what each column means | [Feature glossary](features.md) (every feature, generated from the code) |
| Find your files, check the quality, interpret a comparison, know the limits | [Results](results.md) |
| See the calculations behind every feature | [How it works](theory.md) |

New installation? Run the optional **synthetic demo** at the end of the notebook first: it checks
every step against a known answer ([Workflow → synthetic demo](workflow.md#optional-synthetic-demo)).

Reference: [MorphoBricks conventions](morphobricks.md) (folder layout, column names, pinned
sources) · [Validation of the optical-flow engine](validation.md) (accuracy, gain bias,
brightness artefact, resources) · dated review records in [archive/](archive/).

## Overview

### Purpose

The OpticalFlow3D Profiler quantifies **collective nuclear motion** in 3D fluorescence
time-lapses (for example nuclei in an organoid or a tissue). For every field of view it measures
how fast the nuclear signal moves, whether it moves in a common direction, and how much the
motion differs between regions. It then compares experimental conditions with a control.

It does not follow individual nuclei. It measures the motion of the intensity pattern at every
voxel and summarises it over the field of view.

### How it works

```
3D time-lapse (one TIFF per field of view, single channel, T Z Y X)
  │  you confirm the axes and the calibration once per run
  ▼
OpticalFlow3D (unchanged upstream code), one sliding time window at a time
  │  per analysed time point: vx, vy, vz velocity volumes + reliability volume
  │  (3D mode, or 2D slice per slice for very anisotropic stacks: no vz)
  ▼
Per-frame motion features
  │  inside the foreground (intensity threshold, or the whole image)
  │  and the reliability filter; units µm/min when calibrated
  │  → features_per_frame.csv (one row per field of view and time point)
  ▼
Per-FOV time averages
  │  mean over the time points (circular mean for the direction)
  │  → features_per_fov.csv (one row per field of view)
  ▼
MorphoCoverage comparison
     each condition against your control, the field of view as the observation;
     Cohen's d, exploratory FOV-level randomization screen, paired test on
     biological-repeat means, PCA/UMAP and per-feature figures → report.html
```

Each step is described with formulas in [How it works](theory.md). Every file the app writes is
listed in [Outputs and run folder](results.md#outputs-and-run-folder).

### The data you need

- **Images:** 3D time-lapses of a nuclear marker. One **single-channel** TIFF or OME-TIFF per
  field of view, with time (`T`), depth (`Z`), `Y` and `X` axes. A channel axis is accepted only
  with length 1. 2D time-lapses (no Z) are not accepted.
- **Enough time points:** with the default `tSig = 1`, the optical flow needs 7 time points per
  output. The first 3 and last 3 time points have no output, so a 15-frame movie gives 9 analysed
  time points.
- **A MorphoBricks experiment folder:**
  `<root>/<condition>/<biological repeat>/<technical repeat>/<image>.tif`. Every level is
  optional. See [Preparing your data](getting_started.md#preparing-your-data).
- **Calibration (recommended):** X and Y pixel size, Z spacing and frame interval. Without it,
  results stay in pixels (slices) per frame and some features are undefined.
- **For statistics:** a control condition, and biological repeats whose labels mean the same
  repeat in every condition. The paired test on repeat means needs 3 or more biological repeats.
- **Computer:** about 11–12 GB of RAM for an 1840 × 1840 × 11 stack (see
  [Limitations](results.md#resources)).

### What it does NOT do

- **No tracking.** There are no single-cell trajectories, no per-nucleus speeds and no
  displacement over the whole movie.
- **No segmentation of individual nuclei.** The foreground is a single raw-intensity threshold
  (or the whole image). Connected foreground objects are counted only as a quality-control
  confounder.
- **No calibrated displacement.** Optical-flow speeds are the motion of intensity patterns. On
  synthetic nuclei the 3D algorithm underestimates XY speed (×0.5–0.85) and overestimates Z speed
  (up to ×1.7), and the bias depends on nuclear size ([Validation](validation.md)). Compare
  conditions imaged with the same settings.
- **No guessing.** Axes, calibration and replicates are never guessed. Missing calibration stays
  missing, and an undefined value stays empty (NaN), never 0.
- **No silent normalisation, no Z projection.** Intensities are used raw. Brightness correction
  is an opt-in choice and is applied only to the optical-flow input.
- **No changes to your files.** Input images are only read. A run folder and a report are never
  overwritten.
- **No tiling, GPU, multiprocessing or downsampling.** Each field of view is processed in full,
  one time window at a time.

## Citation

If you use this app, please cite the OpticalFlow3D paper:

> Lee, R. M., Eisenman, L. R., Hobson, C. M., Aaron, J. S. and Chew, T.-L. (2026). OpticalFlow3D –
> a tool for measuring amorphous motion in three-dimensional fluorescence microscopy images.
> *J. Cell Sci.* 139(21), jcs264851. https://doi.org/10.1242/jcs.264851

and [LabConstrictor](https://doi.org/10.48550/arXiv.2603.10704). The condition statistics and
the report are MorphoCoverage's (CellMigrationLab, MIT licence).
