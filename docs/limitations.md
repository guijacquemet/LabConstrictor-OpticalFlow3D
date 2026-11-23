# Limitations

[:arrow_left: Documentation index](index.md)

The OpticalFlow3D Profiler is **experimental**. Real-data validation is pending: the accuracy
figures below come from synthetic nuclei and one real crop ([Validation](validation.md)).

## What optical flow can and cannot tell you

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

## Axial (Z) measurements are experimental

- The 3D smoothing kernels are isotropic in voxels and longer (19 voxels with `xyzSig = 3`) than a
  typical 11-slice stack. Upstream pads with the edge slices, and axial velocities in the top and
  bottom two slices are biased by 20–30 %.
- With no true axial motion, mean |vz| has a noise floor of about 0.02 slices/frame on the
  synthetic demo, which dominates |vz| features of slowly moving samples once scaled to µm/min.
- Axial features are given to MorphoCoverage only when you choose them, and the default speed is
  XY speed. In per-slice 2D mode there is no `vz` at all.

## Data and design

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
  ([Outputs](outputs.md#reusing-earlier-optical-flow)).

## Resources

- **Memory:** about **11–12 GB of RAM** per 1840 × 1840 × 11 Z-stack (one time window is held at
  a time; measured 11.35 GB peak for a 7 × 11 × 1840 × 1840 uint16 window on a 4-vCPU machine).
- **Time:** about 12–15 minutes per 1840 × 1840 × 11 × 15 field of view on a 4-vCPU machine
  (83.5 s measured per optical-flow output, 9 outputs; the notebook's estimate is rough).
- **Disk:** 9.4 GB of float64 output per such field of view (4.7 GB as float32).
- **No tiling, GPU or multiprocessing**, and images are never downsampled. If the memory estimate
  exceeds the available memory, use a computer with more memory.
- The resource estimate in section 2 uses figures measured on the 3D algorithm, also in per-slice
  mode (which writes no `vz` files, so its output is smaller than estimated).

## Platforms

- The desktop installer is built and tested for **Linux x86-64 only**. Windows and macOS
  installers are not built; use Google Colab or a Python install there
  ([Installation](installation.md)).
- On a remote Jupyter server, the report link (`127.0.0.1`) opens on your own computer; open
  `report.html` from the file browser instead.

## By design

These are deliberate choices, not missing features:

- Nothing is guessed: no axes, channels, calibration, conditions or replicates.
- Undefined values stay empty (NaN), never 0; invalid velocities are excluded, never zeroed.
- Intensities are never normalised for features or thresholds; brightness correction is opt-in
  and only changes the optical-flow input.
- No Z projection.
- Inputs are never modified; runs, flow results, QC figures and reports are never overwritten.
- The OpticalFlow3D code is used unchanged; the statistics are MorphoCoverage's.
