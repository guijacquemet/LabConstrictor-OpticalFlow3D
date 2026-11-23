# Overview

[:arrow_left: Documentation index](index.md)

A short technical note before the detailed pages. If you just want to run the app, go to
[Installation](installation.md) and [Workflow](workflow.md), and come back here later.

## Purpose

The OpticalFlow3D Profiler quantifies **collective nuclear motion** in 3D fluorescence
time-lapses (for example nuclei in an organoid or a tissue). For every field of view it measures
how fast the nuclear signal moves, whether it moves in a common direction, and how much the
motion differs between regions. It then compares experimental conditions with a control.

It does not follow individual nuclei. It measures the motion of the intensity pattern at every
voxel and summarises it over the field of view.

## How it works

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
listed in [Outputs and run folder](outputs.md).

## The data you need

- **Images:** 3D time-lapses of a nuclear marker. One **single-channel** TIFF or OME-TIFF per
  field of view, with time (`T`), depth (`Z`), `Y` and `X` axes. A channel axis is accepted only
  with length 1. 2D time-lapses (no Z) are not accepted.
- **Enough time points:** with the default `tSig = 1`, the optical flow needs 7 time points per
  output. The first 3 and last 3 time points have no output, so a 15-frame movie gives 9 analysed
  time points.
- **A MorphoBricks experiment folder:**
  `<root>/<condition>/<biological repeat>/<technical repeat>/<image>.tif`. Every level is
  optional. See [Preparing your data](data_preparation.md).
- **Calibration (recommended):** X and Y pixel size, Z spacing and frame interval. Without it,
  results stay in pixels (slices) per frame and some features are undefined.
- **For statistics:** a control condition, and biological repeats whose labels mean the same
  repeat in every condition. The paired test on repeat means needs 3 or more biological repeats.
- **Computer:** about 11–12 GB of RAM for an 1840 × 1840 × 11 stack (see
  [Limitations](limitations.md#resources)).

## What it does NOT do

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

## The other pages

- [Installation](installation.md): desktop installer (Linux x86-64), Google Colab, or Python.
- [Preparing your data](data_preparation.md): folder layout, file format, axes and calibration
  rules, and what is refused.
- [Workflow](workflow.md): the notebook section by section, with every setting and its default.
- [How it works](theory.md): the algorithm and the feature formulas.
- [Interpreting results](concepts.md): what the features tell you, and the pitfalls.
- [Feature glossary](features.md): every column.
- [Quality control](qc.md): QC columns, warnings and figures.
- [Outputs and run folder](outputs.md): every file, and the reuse of earlier optical flow.
- [Limitations](limitations.md) and [Troubleshooting](troubleshooting.md).
