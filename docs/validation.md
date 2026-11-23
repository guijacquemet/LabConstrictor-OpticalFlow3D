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

## Resources (measured)

| Input window | Time | Peak RSS | Estimate |
|---|---|---|---|
| 7 × 11 × 1840 × 1840 uint16 (synthetic), 4-vCPU VM | 83.5 s | 11.35 GB | 11.25 GB |

For the representative dataset (15 frames): about 12-13 minutes and 11-12 GB of RAM per
field of view, and 9.4 GB of float64 output (4.7 GB as float32). Not yet measured on the
real data.
