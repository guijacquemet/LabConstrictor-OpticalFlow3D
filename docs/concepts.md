# Interpreting results

[:arrow_left: Documentation index](index.md)

This page is about reading the numbers: what each feature family tells you biologically, which
columns are readouts, and the traps to avoid. The calculations are in [How it works](theory.md);
every column is in the [Feature glossary](features.md).

## What the app actually measures

Optical flow measures how the **intensity pattern** of the nuclear signal moves between frames,
voxel by voxel. When nuclei move, their pattern moves, so the flow reflects nuclear motion. But it
also reflects anything else that changes the pattern: nuclei changing shape or brightness,
division, focus drift, bleaching, illumination changes, noise. And it gives no identity: a voxel's
velocity is not "the speed of nucleus 12".

Think of the results as a **motion profile of the field of view**: how fast the nuclear signal
moves, how ordered the motion is, and how uniform it is in space. Compare profiles between
conditions imaged with the same settings; do not read them as absolute nuclear speeds.

## What each family tells you

| Family | Biological question | Typical columns | Example interpretation |
|---|---|---|---|
| [Speed](features.md#speed) | How fast does the nuclear signal move? | `speed_xy_median`, `speed_xy_mean`, `speed_xy_p90`, `speed_xy_cv` | A drug that stalls migration lowers the median and the high percentiles. `cv` and the spread between `p10` and `p90` describe how variable motion is within the field of view. |
| [Velocity components](features.md#velocity-components) | How is motion split between axes? | `vx_sd`, `vy_sd`, `vx_abs_mean`, `vy_abs_mean`; axial `vz_*` | `vx_abs_mean` and `vy_abs_mean` differ when motion is mostly along one image axis. Axial columns are experimental. |
| [Collective motion and direction](features.md#collective-motion-and-direction) | Do nuclei move together, and in which pattern? | `coherence_xy_global`, `coherence_xy_local`, `xy_angular_entropy`, `xy_angular_dispersion`, `xy_aligned_fraction` | Collective migration in one direction: high global coherence, low entropy and dispersion, high aligned fraction. Swirls or local streams: high local but low global coherence. Random motion: low coherence, entropy near 1. |
| [Spatial heterogeneity](features.md#spatial-heterogeneity) | Is motion uniform across the field of view? | `regional_speed_cv`, `regional_speed_spread`, `regional_coherence_sd`, `regional_moving_fraction` | A tissue with a migrating front and a static core has high regional variation. `regional_moving_fraction` tells how much of the field of view moves above your chosen speed. |
| [Quality control](features.md#quality-control) | Can I trust and compare these numbers? | `qc_reliable_fraction`, `qc_foreground_fraction`, `qc_object_mean_voxels`, `qc_brightness_change_per_frame` | Used to check comparability, never as a result. See [Quality control](qc.md). |

Speed-weighted versus unweighted: `coherence_xy_global` gives fast voxels more weight, while the
angular features (`xy_angular_entropy`, `xy_angular_dispersion`, `xy_aligned_fraction`) count every
directed vector equally. If the two disagree, the fast-moving part of the field of view moves more
(or less) coherently than the slow part.

## Readouts, orientation descriptors and QC

Every column has a *use* in the glossary (and in `feature_dictionary.json` as `applicability`):

| Use | Given to MorphoCoverage? | Columns | Why |
|---|---|---|---|
| **readout** | Always | XY speed, `lateral_speed_mean`, XY coherence, angular entropy, dispersion and aligned fraction, regional columns | They describe the motion itself and do not change when the image is rotated. |
| **axial readout (experimental)** | Only when you tick *Also include experimental axial features* (a chosen axial readout is always included) | `vz_sd`, `vz_abs_mean`, `axial_lateral_ratio`, `coherence_3d_global`, `speed_3d_*` | Axial velocities are less reliable in shallow stacks (see pitfalls). |
| **orientation descriptor** | Never | every `vx_*` and `vy_*` column (`vx_mean`, `vx_sd`, `vx_abs_mean`, and the same for `vy`), `vz_mean`, `xy_dominant_direction_deg` | They depend on how the sample was placed under the microscope. Two identical samples rotated by 90° give different values, so they are not phenotypes. Use them only within one image, for example to check a known flow direction. |
| **quality control** | Never | every `qc_*` column | They describe the measurement (reliability, occupancy, object size, brightness), not the biology. Treating them as phenotypes would let imaging differences masquerade as effects. |

## Checking comparability

Before you believe a difference between conditions, check that the measurement was similar in
both. Compare these QC columns between conditions in `features_per_fov.csv` (or
`features_per_frame.csv` for time trends):

| Check | Column(s) | Why it matters |
|---|---|---|
| Similar reliability | `qc_reliable_fraction`, `qc_reliability_median` | If one condition has much less reliable flow, its features come from fewer, possibly different voxels. |
| Similar occupancy | `qc_foreground_fraction`, `qc_n_analysed_voxels` | Denser or sparser tissue changes what the foreground holds; with no foreground, background dominates sparse fields of view. |
| Similar object size | `qc_object_mean_voxels`, `qc_object_mean_z_extent` | **The optical-flow gain depends on nuclear size and axial extent.** If nuclei are larger in one condition, its speeds can differ even with identical motion. |
| Little brightness change | `qc_brightness_change_per_frame` | Brightening or bleaching is partly read as motion. Values above 0.02/frame are flagged. |
| Similar intensity (optional) | `qc_foreground_intensity_mean` | Brightness affects gradients and therefore reliability and noise. |
| Enough regions | `qc_n_regions_analysed` | Regional features from 2–3 regions are noisy. |

If a confounder differs, the comparison is not necessarily wrong, but you must say so and
consider whether it can explain the effect.

## Pitfalls

1. **Gain bias with object size.** On synthetic nuclei the 3D algorithm recovers only 0.5–0.85
   of the true XY speed and up to 1.7× the Z speed, and the factor depends on nuclear size and
   Z extent ([Validation](validation.md)). Speeds are relative. A change in nuclear size between
   conditions can look like a change in speed. Per-slice 2D flow is much closer to the true XY
   speed on anisotropic stacks, but still underestimates large displacements (about 30 % at
   5 px/frame).
2. **Large displacements are underestimated.** Lucas–Kanade follows small motions best. When
   nuclei move several pixels per frame, every mode underestimates. Shorter frame intervals help.
3. **Axial features are experimental.** In shallow stacks (fewer slices than the spatial kernel,
   19 with `xyzSig = 3`), upstream pads with the edge slices; axial velocities in the top and
   bottom slices are biased by 20–30 %. With no true axial motion, mean |vz| still has a noise
   floor (about 0.02 slices/frame on the synthetic demo), which dominates |vz| features of slowly
   moving samples once scaled to µm/min.
4. **Fields of view within a repeat are not independent.** Fields of view imaged on the same day
   share the same culture, staining and microscope state. A separation between conditions in the
   PCA or UMAP is not evidence that a treatment changes migration. The FOV-level randomization
   screen is exploratory. Only the paired test on biological-repeat means (3 or more repeats) says
   whether an effect repeats.
5. **Time points are not replicates.** Each field of view contributes one time-averaged profile.
6. **Orientation-dependent features are never readouts.** `vx_mean`, `vy_mean`, `vz_mean` and
   `xy_dominant_direction_deg` change with how the sample lies in the image.
7. **The foreground matters.** A threshold that is too low includes background (spurious,
   unreliable velocities); one that is too high keeps only bright nuclear cores. Check the
   foreground outlines in the [QC figures](qc.md#qc-figures). Whole-image measurement is
   exploratory.
8. **Reliability mode.** With `percentile`, the threshold adapts to each frame, so a fixed
   fraction of the foreground is always kept, even when the whole frame is unreliable. With
   `absolute`, one value applies to every field of view, which keeps the criterion identical
   across conditions.
9. **Undefined is not zero.** An empty cell means the value does not exist (for example no
   region with enough voxels, or 3D speed without a full calibration). The reason is in
   `undefined_features`. Never fill empty cells with 0 before your own analysis.
10. **Brightness correction is a choice.** `global_mean` and `histogram_match` reduce spurious
    motion from brightness changes, but they change the input of the optical flow. Use the same
    choice for every condition you compare (runs with different settings cannot be combined).

## A worked reading

Suppose the report shows that `drug` has a higher `coherence_xy_global` than `ctrl` (Cohen's d
large, higher in every biological repeat, paired test significant) and a similar
`speed_xy_median`. A careful reading:

1. Check QC: `qc_reliable_fraction`, `qc_object_mean_voxels` and `qc_brightness_change_per_frame`
   are similar in both conditions. Good.
2. Check the per-frame table: the coherence is high in every time point, not in one frame only.
3. Look at the QC flow figures of a few fields of view: vectors point the same way in `drug`.
4. Conclusion: nuclei move more collectively in `drug`, at a similar optical-flow speed. Report it
   as motion of the nuclear signal measured by optical flow, not as tracked cell migration.
