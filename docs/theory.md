# How it works

[:arrow_left: Documentation index](index.md)

This page describes every calculation, from the image to the condition comparison. For what the
numbers mean in practice, see [Interpreting results](results.md#interpreting-results); for every column, the
[Feature glossary](features.md).

**Notation.** `I(x, y, z, t)` is the raw intensity. `vx`, `vy`, `vz` are the velocity components.
A *frame* is a time point of the movie; a *window* is the group of frames the optical flow uses
for one output.

---

## 1. The optical flow (OpticalFlow3D)

The velocities come from the original OpticalFlow3D Python code (Lee et al., 2026), copied
**unchanged** into `src/opticalflow3d_profiler/_upstream/calc_flow.py` from commit `6b88604` of
[aicjanelia/OpticalFlow3D](https://github.com/aicjanelia/OpticalFlow3D). The app checks the file's
SHA-256 before every run and refuses to run if it was modified. Only the functions `calc_flow3D`
and `calc_flow2D` are called.

### Lucas–Kanade with Gaussian derivatives

Optical flow assumes that an intensity pattern keeps its brightness while it moves
(*brightness constancy*). To first order:

```
Ix·vx + Iy·vy + Iz·vz + It = 0
```

where `Ix`, `Iy`, `Iz`, `It` are the derivatives of the intensity. One equation cannot give three
unknowns, so Lucas–Kanade assumes the velocity is constant in a small neighbourhood and solves the
equations of all its voxels by weighted least squares:

```
M · v = −b
M = Σ w · ∇I ∇Iᵀ      (3 × 3 structure tensor)
b = Σ w · ∇I · It
```

The sums run over a Gaussian neighbourhood `w`. Upstream solves the 3 × 3 system explicitly at
every voxel (with machine epsilon added to the determinant).

The three parameters set the Gaussian scales (kernels are cut at ±`ceil(3σ)` and image edges are
padded with the nearest value):

| Parameter | Default | Role in the code |
|---|---|---|
| `xyzSig` | 3 voxels | Spatial derivatives: derivative of a Gaussian with σ = `xyzSig` along the derivative axis, Gaussian smoothing with σ = `xyzSig/4` along the other spatial axes. The temporal derivative is smoothed with σ = `xyzSig` in every spatial axis. |
| `tSig` | 1 frame | Temporal derivative: derivative of a Gaussian with σ = `tSig` along time. |
| `wSig` | 4 voxels | The Lucas–Kanade neighbourhood `w`: a Gaussian with σ = `wSig` in every spatial axis. |

All scales are in **voxels**, the same in X, Y and Z, whatever the physical voxel size.

### Reliability

Upstream also returns the **reliability**, the smallest eigenvalue of the structure tensor `M`.
It is large where the local pattern has strong gradients in every direction, so the velocity is
well determined. It is near zero in flat regions (no signal) and where the pattern is the same
along one direction (the aperture problem). Regions without signal produce large, meaningless
velocities with near-zero reliability, which is why the app filters on it
([section 4](#4-where-features-are-measured-foreground-and-reliability)).

### Time windows

Each output is computed from a window of consecutive frames and describes the **central frame**:

```
window length = ceil(6·tSig) + 1, made odd     (7 frames for tSig = 1)
half = window length // 2                      (3 frames for tSig = 1)
outputs for source frames t = half … T − half − 1
```

So the first and last `half` frames of the movie have no output. With 15 frames and `tSig = 1`,
there are 9 outputs, for source frames 3 to 11. Each output is saved as
`<fov_uid>_vx_t0003.tiff` and so on, numbered by its source frame (0-based) in the upstream file
layout. Only one window is held in memory at a time.

### Units of the raw output

`vx` and `vy` are in pixels/frame, `vz` in slices/frame. The velocities are saved as float64 (as
upstream returns them) or float32 if you choose so; the reliability is saved as upstream returns it.

---

## 2. 3D and per-slice 2D modes

| Mode | What runs | Outputs |
|---|---|---|
| `xyz` | `calc_flow3D` on each window of Z-stacks | `vx`, `vy`, `vz`, `rel` |
| `xy_per_slice` | `calc_flow2D` on each Z slice separately (same `xyzSig`, `tSig`, `wSig`); the slices are stacked again | `vx`, `vy`, `rel` (no `vz`) |
| `auto` (default) | `xy_per_slice` when `Z spacing / X pixel size > 3`, otherwise `xyz` (the X size stands for XY: X and Y sampling are assumed similar) | as the resolved mode |

`auto` needs the X pixel size and the Z spacing; without them it stops with a message asking you
to enter them or to choose a mode. The resolved mode is what is recorded in the run and flow
manifests.

**Why per-slice exists.** The 3D smoothing is isotropic in voxels. In a stack with 5 µm slices
and 0.25 µm pixels, 3 voxels are 15 µm in Z but 0.75 µm in XY, so nuclei only 1–2 slices deep are
blurred across the stack. On synthetic nuclei matched to that geometry, 3D recovered only
0.30–0.41× of the true XY speed, and per-slice 2D 0.91–0.95× ([Validation](validation.md)).
In per-slice mode every axial feature is undefined, with the reason
`per-slice 2D optical flow has no axial component`, and 3D speed is refused.

---

## 3. Physical units

The saved velocity files always stay in upstream units. The features convert each axis
separately (`flow_features.velocity_scale`):

```
vx [µm/min] = vx [px/frame]    × pixel_size_x / frame_interval
vy [µm/min] = vy [px/frame]    × pixel_size_y / frame_interval
vz [µm/min] = vz [slice/frame] × pixel_size_z / frame_interval
```

- Lateral features are in µm/min when X, Y and the frame interval are known, otherwise in
  px/frame.
- Axial features are in µm/min when Z and the frame interval are known, otherwise in slice/frame.
- Features that combine lateral and axial components (`speed_3d_*`, `coherence_3d_global`,
  `axial_lateral_ratio`) need both in µm/min; otherwise they are undefined, because pixels and
  slices are different lengths.

Scaling converts units only. It does not remove the optical-flow gain bias
([Limitations](results.md#limitations)). The units of a run are written in
`features/feature_dictionary.json` (`units`).

---

## 4. Where features are measured: foreground and reliability

Every feature of one output is computed over the **analysed voxels**:

```
analysed = foreground  AND  finite velocity  AND  reliable
```

- **Foreground** (`foreground.mode`):
  - `threshold`: voxels whose **raw** intensity at the output's source frame is strictly above the
    threshold, `I > threshold`. One value for every field of view; intensities are never
    normalised.
  - `none`: every voxel (whole image, exploratory).
  The optical flow itself is always computed on the whole image; the foreground only selects where
  features are measured.
- **Finite velocity:** `vx`, `vy` (and `vz` in 3D) are finite numbers. Non-finite values are
  excluded and counted (`qc_invalid_velocity_fraction`), never replaced by 0.
- **Reliable** (`features.reliability_mode`):
  - `absolute`: `rel ≥ reliability_value`;
  - `percentile`: `rel ≥ P`, where `P` is the `reliability_value`-th percentile of the finite
    reliability values inside `foreground AND finite`, recomputed for each output;
  - `none`: every voxel.
  A voxel with non-finite reliability is never reliable and never sets a percentile.

Velocities are never modified: genuine zeros stay zeros. A feature that cannot be computed is NaN
(an empty cell), and its reason is written in `undefined_features`.

---

## 5. Feature families

The features of one output form one row of `features_per_frame.csv`. Column names carry the
foreground name (`Nuclei__speed_xy_median`) or `whole__` without a foreground; `qc_*` columns have
no prefix. Below, `v_i` is the (scaled) velocity of analysed voxel `i`, `N` the number of analysed
voxels, and `s_i` its speed.

### 5.1 Speed → [glossary](features.md#speed)

```
s_i = sqrt(vx_i² + vy_i²)              speed_mode = xy  (default) → speed_xy_*
s_i = sqrt(vx_i² + vy_i² + vz_i²)      speed_mode = xyz            → speed_3d_*
```

Statistics over the analysed voxels: `mean`, `median`, `sd` (population SD), `cv = sd / mean`
(undefined when the mean is 0), `rms = sqrt(mean(s²))`, percentiles `p10`, `p25`, `p75`, `p90`,
`p95`, and `max`.

### 5.2 Velocity components → [glossary](features.md#velocity-components)

For each axis `a` in x, y, z: `va_mean = mean(va)`, `va_sd = sd(va)`, `va_abs_mean = mean(|va|)`.
`axial_lateral_ratio = mean(|vz|) / mean(sqrt(vx² + vy²))` (needs one physical unit). In 3D speed
mode, `lateral_speed_mean = mean(sqrt(vx² + vy²))` is added (in XY mode it would equal
`speed_xy_mean`).

Every `vx_*` and `vy_*` column, and `vz_mean`, depends on how the sample is oriented in the image
(rotating the image moves motion between x and y), so they are orientation descriptors, never
readouts. `vz_sd` and `vz_abs_mean` are axial readouts: Z is defined by the microscope. Image
coordinates have y pointing down.

### 5.3 Collective motion and direction → [glossary](features.md#collective-motion-and-direction)

**Global coherence** (speed weighted):

```
coherence_xy_global = |Σ_i (vx_i, vy_i)| / Σ_i |(vx_i, vy_i)|
coherence_3d_global = |Σ_i (vx_i, vy_i, vz_i)| / Σ_i |(vx_i, vy_i, vz_i)|   (one physical unit needed)
```

1 when every vector points the same way, near 0 when directions cancel out. Fast voxels weigh
more than slow ones. Undefined when every analysed vector is zero.

**Local coherence.** For each analysed voxel, take the `local_window_px × local_window_px` XY
window around it in the same Z slice, and compute the same ratio over the analysed voxels of that
window:

```
c(voxel) = |Σ_window v| / Σ_window |v|
coherence_xy_local = mean of c over the analysed voxels where c is defined
```

A window is defined only when it holds at least `min_local_vectors` (default 5) analysed nonzero
vectors, because one or two vectors always look coherent. Global coherence asks "does the whole
field of view move in one direction?"; local coherence asks "do neighbours move together?". A
tissue with swirls has high local and low global coherence.

**Directions.** The angular features use the XY directions `θ_i = atan2(vy_i, vx_i)` of the
analysed vectors whose XY speed is above `min_direction_speed` (default 0, so every nonzero
vector). With fewer than `min_direction_vectors` (default 20) such vectors, all four angular
features are undefined. They are **not** weighted by speed. With `R = |mean(exp(iθ))|` (the mean
resultant length):

```
xy_angular_dispersion     = 1 − R
xy_dominant_direction_deg = atan2(mean sin θ, mean cos θ)   in degrees, −180 to 180, y down
xy_aligned_fraction       = fraction of vectors with cos(θ − θ_dom) ≥ cos(aligned_angle_deg)
```

The dominant direction and the aligned fraction are undefined when `R` is zero (no mean
direction). The default `aligned_angle_deg` is 45°.

**Angular entropy** (`xy_angular_entropy`, `flow_features.angular_entropy`). How evenly the
directions are spread, from 0 (all in one direction) to 1 (uniform):

1. Build a smooth density of the directions: a mixture of **wrapped-normal kernels** centred on
   each direction, with standard deviation `σ = 360° / angle_bins` (10° with the default
   `angle_bins = 36`):
   `p(θ) = (1/n) Σ_i WN(θ; θ_i, σ)`.
2. Compute its differential entropy `H = −∫ p(θ) log p(θ) dθ` over the circle.
3. Normalise between the entropy of a single kernel `H_kernel` (every vector in one direction)
   and the entropy of the uniform density `log 2π`:

```
xy_angular_entropy = (H − H_kernel) / (log 2π − H_kernel)      clipped to [0, 1]
```

Because entropy is concave, `H` always lies between these two limits. There are no histogram bins,
edges or anchor angle, so for the continuous density rotating every vector leaves the value
unchanged, and moving one vector a little changes the value a little; the numerical value follows
this within the measured error given below. Numerically, the density is evaluated on 65,536 points of the
circle (each direction is spread linearly between its two nearest points), the kernel is applied
by FFT, and the integral is a trapezoid sum. The concavity bound holds for the continuous
density; the grid computation follows it within its numerical error, which was measured: with
`angle_bins` up to 360 (a 1° kernel, the largest allowed), a single direction placed anywhere on
the grid gives at most 8.4 × 10⁻⁷ instead of 0, and rotations change the value by at most
1.5 × 10⁻⁷. Finer kernels are not resolved by the grid and are refused (`angle_bins_too_large`).

### 5.4 Spatial heterogeneity → [glossary](features.md#spatial-heterogeneity)

The XY image is cut into a grid of full squares of `region_size_px` pixels (default 128), each
spanning all Z slices; partial squares at the right and bottom edges are left out. A region is
used only if it holds at least `min_region_voxels` (default 100) analysed voxels. For each used
region `k`, `R_k` is the mean speed of its analysed voxels (in the run's speed mode) and `C_k` its
XY coherence `|Σv| / Σ|v|`:

```
regional_speed_cv        = sd(R) / mean(R)
regional_speed_spread    = (P90(R) − P10(R)) / median(R)
regional_coherence_sd    = sd(C)
regional_moving_fraction = fraction of regions with R_k > motion_threshold
```

The first three need at least 2 used regions. `regional_moving_fraction` is undefined unless you
set a moving-region threshold.

### 5.5 Quality control → [glossary](features.md#quality-control)

QC columns describe the measurement, not the biology:

| Column | Calculation |
|---|---|
| `qc_reliability_threshold` | The reliability threshold applied (the absolute value, or the percentile value of this frame) |
| `qc_reliability_median`, `_p10`, `_p90` | Distribution of the finite reliability in `foreground AND finite`, before filtering |
| `qc_reliable_fraction` | `n(analysed) / n(foreground AND finite)` |
| `qc_invalid_velocity_fraction` | `n(foreground with a non-finite component) / n(foreground)` |
| `qc_invalid_reliability_fraction` | `n(non-finite rel) / n(foreground AND finite)` |
| `qc_foreground_fraction` | Fraction of the volume in the foreground (occupancy); undefined without a foreground |
| `qc_n_analysed_voxels` | Number of analysed voxels |
| `qc_n_regions`, `qc_n_regions_analysed`, `qc_region_grid_coverage` | Grid size, used regions, and the fraction of the XY image covered by full regions |
| `qc_object_mean_voxels`, `qc_object_mean_z_extent`, `qc_n_objects` | 3D connected components of the foreground: mean voxel count, mean number of slices spanned, count |
| `qc_brightness_change_per_frame` | Brightness trend of the window ([section 7](#7-brightness-change-and-optional-correction)) |
| `qc_foreground_intensity_mean` | Mean raw intensity in the foreground (only with intensity QC switched on) |

Object size matters because the optical-flow gain depends on nuclear size and axial extent
([Validation](validation.md)).

---

## 6. Time averaging per field of view

`features_per_fov.csv` holds one row per field of view, with the **same column names** as the
per-frame table. For each feature:

- the arithmetic **mean over the time points where it is defined**. Undefined time points are
  left out, never counted as 0;
- the **circular mean** for `xy_dominant_direction_deg`:
  `atan2(mean sin θ, mean cos θ)` over the defined frames (undefined if those directions cancel
  out exactly);
- NaN when the feature is undefined in every time point; `undefined_features` then says, for
  example, `0 defined frame(s) of 9`.

`n_flow_frames` is the number of optical-flow time points of the field of view. Time points are
repeated measurements of one sample, **never replicates**. Nothing is averaged per biological
repeat in the saved tables.

---

## 7. Brightness change and optional correction

Optical flow reads part of a global brightness change (illumination warm-up, focus settling,
bleaching, expression changes) as motion. On a real organoid crop that brightened 2.8× over 15
frames, the raw optical flow inflated XY speeds and produced a systematic axial velocity of up to
+1.3 slices/frame ([Validation](validation.md)).

The measurement and the corrections come from the `time_series` module of
[morphobricks-normalization](https://github.com/CellMigrationLab/morphobricks-normalization) (a
pinned dependency). The app applies them to each optical-flow window, with the window's **central
frame as the reference** (`brightness.py`).

**Always measured.** For each output, `m_j` is the mean raw intensity of frame `j` of the window
(over the whole Z-stack). The brightness change is

```
brightness_change_per_frame = (least-squares slope of m_j against j) / m_central
```

so 0.05 means brightening by 5 % of the central brightness per frame. It is undefined when the
central mean is not above 0. It is saved for every output (`flow_manifest.json` and
`qc_brightness_change_per_frame`). A field of view whose absolute change exceeds **0.02 (2 %) per frame** (brightening or dimming)
in any output gets a warning in `fovs.csv`.

**Optional correction** (`flow.brightness_equalisation`, off by default):

| Option | What it does to the optical-flow input |
|---|---|
| `none` (default) | Nothing: upstream receives the raw intensities. |
| `global_mean` | Each frame of the window is scaled so that its mean equals the central frame's mean. The factors are recorded (`equalisation_factors`). A frame with a non-positive mean cannot be scaled and stops that field of view with an error. |
| `histogram_match` | Each frame's intensity histogram (whole Z-stack) is mapped onto the central frame's (Fiji Bleach Correction "Histogram Matching"). Monotonic but non-linear, so relative intensities change. |

The correction changes only what the optical flow sees. The foreground threshold, the intensity
QC and the brightness measurement always use the raw intensities, and the input file is never
modified. The correction code's identity (version and SHA-256 of the code) is part of the flow
identity, so optical flow corrected with different code is never reused.

---

## 8. Statistics: MorphoCoverage

The condition comparison is done entirely by
[MorphoCoverage](https://github.com/CellMigrationLab/MorphoCoverage) (pinned commit `209b9be`,
imported, not reimplemented). The app (`coverage.py`) only builds MorphoCoverage's input:

- **Observation:** the field of view, with its time-averaged profile from `features_per_fov.csv`
  (`observation_unit = "fov"`).
- **Features:** readout features always; experimental axial features only when you choose them
  (a chosen axial readout is always included). Orientation descriptors and `qc_*` columns are
  never features. Features undefined in every field of view are left out and listed.
- **Repeats:** the biological repeat is also MorphoCoverage's `repeat_group`, the only way it
  pairs repeats across conditions. You must confirm this pairing in the design step. With several
  runs and unshared labels, the repeat identity is `<run label>/<repeat label>`, so repeats of
  different runs stay distinct.
- **Setup:** your control condition, your readout and the random seed.

According to the README, the report gives **Cohen's d** on the fields of view, an **exploratory
FOV-level randomization screen**, and a **paired test on the biological-repeat means**, which
needs 3 or more biological repeats, together with PCA/UMAP and a figure per feature. The
[MorphoBricks conventions](morphobricks.md#statistics-and-report-morphocoverage) page adds that
MorphoCoverage's own documentation describes a paired t-test on the repeat means and
Benjamini–Hochberg correction. For anything beyond this, refer to MorphoCoverage's documentation.

Because fields of view of one biological repeat are not independent, only the paired test on
repeat means says whether an effect repeats ([Interpreting results](results.md#interpreting-results)).

---

## 9. Code map

| Step | Module | Function |
|---|---|---|
| Folder discovery and refusals | `discovery.py` | `discover_experiment` |
| Metadata and `fov_uid` | `experiment.py` | `read_experiment_folder`, `fov_uid` |
| Header reading, axes check, calibration suggestion | `image_io.py` | `inspect_tiff`, `validate_image`, `named_axis_conflicts` |
| Axes, channel, time-window and calibration checks; `auto` mode | `validation.py` | `check_axes`, `check_time_and_depth`, `resolve_flow_mode` |
| Optical flow over windows, flow manifest | `flow_backend.py` | `run_flow`, `compute_frame`, `flow_identity` |
| Upstream algorithm (unchanged) | `_upstream/calc_flow.py` | `calc_flow3D`, `calc_flow2D` |
| Brightness trend and corrections | `brightness.py` (morphobricks-normalization) | `brightness_change`, `equalise_window`, `match_histograms_window` |
| Foreground | `foreground.py` | `threshold_frame` |
| Per-frame features | `flow_features.py` | `frame_features`, `angular_entropy`, `local_coherence_map` |
| Time averages | `temporal_features.py` | `aggregate_fov`, `circular_mean` |
| Feature dictionary | `feature_dictionary.py` | `frame_dictionary` |
| Column names | `naming.py` | `ColumnNames` |
| Orchestration, run manifest | `pipeline.py` | `run_experiment`, `process_fov` |
| Flow reuse verification | `flow_store.py` | `verify_result`, `open_result` |
| Combining runs | `analysis.py` | `load_runs` |
| MorphoCoverage input and report | `coverage.py` | `coverage_input`, `run_report` |
| QC figures | `qc_export.py`, `figures.py` | `export_qc_figures` |
