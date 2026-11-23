# Phase 1 validation of the OpticalFlow3D engine

Engine: unchanged `calc_flow.py` from aicjanelia/OpticalFlow3D at commit
`6b88604a75319d80002de47ca993ce8b55fb9c46`, default parameters `xyzSig=3`, `tSig=1`,
`wSig=4`. The tests that reproduce the findings are in `tests/profiler/test_flow_science.py`
and `tests/profiler/test_flow_backend.py`.

**Real-data validation is pending.** Everything below uses synthetic nuclei
(`opticalflow3d_profiler.synthetic`) unless stated otherwise.

## What the upstream code does (verified in the source)

| Question | Answer |
|---|---|
| Input axes | `calc_flow3D(images)` takes a 4D array `T, Z, Y, X`; the central time point is analysed. |
| Output units | `vx`, `vy` in pixels/frame, `vz` in slices/frame, float64; reliability (smallest eigenvalue of the structure tensor) in float32. |
| Time window | `6*tSig + 1` frames (made odd). With 15 frames and `tSig=1`: **9 outputs, for source frames 3 to 11** (`process_flow` names them `_t0003` ... `_t0011`). |
| Spatial kernels | Derivative taps `2*ceil(3*xyzSig)+1` = 19 voxels in every axis, including Z, with `mode="nearest"` padding; LK window `2*ceil(3*wSig)+1` = 25 voxels. An 11-slice stack is shorter than both kernels. |
| Errors | `sys.exit` on invalid input (the profiler validates first and converts it to an error message). |
| Analysis notebook | Per-frame 90th-percentile reliability mask, `v[v==0] = nan` (destroys genuine zeros; not reproduced), quiver plot, magnitude and XY-angle histograms, mean magnitude over time. |

## Synthetic results

Gaussian nuclei moving at a known velocity, 11 slices, recovered median velocity inside
bright nuclear voxels away from the borders (ratio recovered/true):

| Nuclear size (σxy, σz voxels) | X, 3D | X, 2D (`calc_flow2D`, mid plane) | Z, 3D |
|---|---|---|---|
| 4, 1.5 | 0.49-0.56 | 0.76-0.90 | 0.85-1.02 |
| 8, 1.5 | 0.53-0.64 | 0.93-0.97 | 1.01-1.16 |
| 8, 3 | 0.79-0.84 | 0.93-0.97 | 1.26-1.66 |
| 12, 2 | 0.66-0.74 | 0.97-1.00 | 1.14-1.40 |

(speeds 0.1-2 voxels/frame; the gain is nearly constant up to 1 voxel/frame.)

Findings:

1. **Static frames give exactly zero velocity** (|v| < 1e-9).
2. **Direction is correct**; the response is close to linear in speed.
3. **3D magnitudes are not calibrated displacements.** Lateral speed is underestimated
   (gain 0.5-0.85) and axial speed overestimated (up to 1.7x), and the gain depends on the
   size and axial extent of the nuclei. A likely cause, from the source: the temporal
   gradient is smoothed with `xyzSig` in all three spatial axes while each spatial gradient
   uses `xyzSig/4` across its two orthogonal axes; 2D (one orthogonal axis) is close to
   unbiased.
4. **Axial velocities are plausible inside the stack** but biased by 20-30 % in the top and
   bottom two slices (edge padding). They are labelled *experimental*.
5. Regions without signal produce large spurious velocities with near-zero reliability:
   reliability filtering is required.
6. With additive noise (SD 20 on amplitude 1000) static nuclei stay well below moving
   ones (test `test_noise_on_static_nuclei_is_small_compared_with_motion`).

Consequences for the profiler (agreed): the algorithm is kept unchanged; speeds are
reported as *optical-flow speeds* in upstream units or as µm/min flagged *uncalibrated
gain*; XY speed is the default; Z-dependent features are experimental and excluded from
PCA by default; foreground size and axial extent are exported as QC confounders because
the gain depends on them.

## Synthetic end-to-end demo (`tools/demo_synthetic.py`)

A 12-field-of-view experiment: 256 × 256 × 11 × 15, 80 nuclei, noise SD 20, calibration
0.65 / 0.65 / 2.0 µm and 1 min. `ctrl` nuclei move at 0.3 px/frame in random directions;
`drug` nuclei move at 0.6 px/frame within ±15° of +x. All 17 expectations passed:

| Check | Result |
|---|---|
| speed ratio drug/ctrl (true 2.0) | 2.14 |
| speed gain ctrl / drug | 0.55 / 0.59 |
| global XY coherence drug / ctrl | 0.987 / 0.078 |
| dominant direction drug | within 2.9° of 0° |
| net axial drift (true vz = 0) | ≤ 0.0022 slice/frame |
| axial noise floor (true vz = 0) | mean \|vz\| ≤ 0.020 slice/frame |
| PCA | PC1 (91 % of variance) separates the conditions |
| threshold versus ground-truth-mask foreground | median speed within 0.8 % |

**Axial noise floor.** With no true axial motion, mean |vz| is about 0.02 slices/frame,
about 5 % of the lateral speed in voxel units. With 2 µm slices and 0.65 µm pixels, physical
scaling multiplies it about 3×. In µm/min, |vz| features of slowly moving samples are then
dominated by this floor. This is one more reason why axial features are experimental.

Runtime: 645 s for the whole demo (12 fields of view, flow, features, QC figures, PCA and a
second feature extraction), 0.47 GB peak RSS, on a 4-vCPU VM.

## First real crop: brightness change (day6_wt_5-1, 15 × 11 × 256 × 256)

The movie brightens 2.8× over 15 time points (+3 % to +11 % per frame). On the raw data, the
optical flow reads this as motion: XY speed 1.1-2.9 px/frame, falling as the brightening
slows, and a systematic vz of +0.3 to +1.3 slices/frame. With the opt-in
`brightness_equalisation="global_mean"`, XY speed is 0.9-1.25 px/frame and roughly constant,
and vz is about 0 (+0.23 in the steepest window). Synthetic static nuclei with an 8 %/frame
ramp show the same effect: equalisation removes more than 99 % of the spurious motion
(`tests/profiler/test_brightness.py`). Every output now records
`qc_brightness_change_per_frame`, and changes above 2 %/frame give a warning.

## Anisotropic stacks: per-slice 2D flow (`FlowParameters.mode`)

Calibration of the first real crop: 0.2537 µm XY, **5 µm Z** (anisotropy 19.7), **60 min** per
frame. With nuclei only about 1.5 slices deep, the isotropic-in-voxels smoothing of the 3D
algorithm (about 3 voxels = 15 µm in Z) blurs them across the stack. Synthetic nuclei matched to
this geometry (σxy 8 px, σz 0.7 slice; recovered/true XY speed):

| True speed (px/frame) | 3D, xyzSig 3 / 6 / 9 | 2D per slice, xySig 3 / 6 / 9 |
|---|---|---|
| 1 | 0.41 / 0.35 / 0.34 | 0.95 / 0.87 / 0.81 |
| 2 | 0.39 / 0.35 / 0.33 | 0.91 / 0.84 / 0.80 |
| 5 | 0.30 / 0.30 / 0.30 | 0.71 / 0.71 / 0.72 |
| 10 | 0.16 / 0.20 / 0.21 | 0.36 / 0.43 / 0.51 |

The default `mode="auto"` therefore runs the unchanged upstream `calc_flow2D` on every Z slice
when the Z spacing exceeds 3× the XY pixel size. The chosen mode is recorded. In this mode there
is no vz, and axial features are NaN with a reason.

On the real crop, phase correlation of 64 × 64 patches between consecutive frames gives a
displacement of about 5 px (1.3 µm) per hour for moving patches (90th percentile 10.7 px). That is
at the edge of what Lucas-Kanade optical flow follows at these settings: even 2D underestimates
about 30 % at 5 px/frame. **For future acquisitions, 15-20 min intervals** would keep the motion
at or below 2 px/frame, where 2D is nearly exact.

Results on the crop (median XY speed in the tissue; brightness-equalised input):
- 3D: about 0.25 µm/h;
- 2D per slice: about 0.5 µm/h, stable over time (raw input: 1.25 falling to 0.55 µm/h, the
  brightening artefact);
- global XY coherence: 0.22-0.49.

## Resources (measured)

| Input window | Time | Peak RSS | Estimate |
|---|---|---|---|
| 7 × 11 × 1840 × 1840 uint16 (synthetic), 4-vCPU VM | 83.5 s | 11.35 GB | 11.25 GB |

For the representative dataset (15 frames): about 12-13 minutes and 11-12 GB of RAM per
field of view, and 9.4 GB of float64 output (4.7 GB as float32). Not yet measured on the
real data.
