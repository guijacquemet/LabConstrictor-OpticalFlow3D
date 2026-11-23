# Quality control

[:arrow_left: Documentation index](index.md)

Optical flow always returns a number, even where there is nothing to measure. Before you trust a
comparison, check that the flow was reliable, that the foreground selected the nuclei, and that
the conditions were measured alike. This page lists the tools the app gives you: QC columns,
warnings and figures.

---

## Quick checklist

1. **Status:** every field of view is `complete` in `fovs.csv`; failures are understood.
2. **Warnings:** read the `warnings` column of `fovs.csv` (brightness change, calibration,
   shallow Z, whole-image measurement).
3. **Foreground:** the outlines in `qc/<fov_uid>/foreground_t*.png` follow the nuclei.
4. **Flow:** in `qc/<fov_uid>/flow_t*.png`, coloured (reliable) vectors sit on the nuclei and
   point in plausible directions; grey (unreliable) vectors are mostly in the background.
5. **Reliability and coverage:** `qc_reliable_fraction` and `qc_n_analysed_voxels` are not tiny,
   and similar between conditions.
6. **Confounders:** `qc_object_mean_voxels`, `qc_object_mean_z_extent`, `qc_foreground_fraction`
   and `qc_brightness_change_per_frame` are similar between conditions.
7. **Time course:** `qc/<fov_uid>/features_over_time.png` shows no single aberrant time point
   driving the average.

---

## QC columns

All QC columns are in both feature tables, with plain names (`qc_*`, no foreground prefix). They
are metadata: **never** given to MorphoCoverage as features. Full definitions:
[Feature glossary → Quality control](features.md#quality-control).

| Question | Columns | What to look for |
|---|---|---|
| Was the flow reliable where I measured? | `qc_reliable_fraction`, `qc_reliability_median`, `qc_reliability_p10`, `qc_reliability_p90`, `qc_reliability_threshold` | A low reliable fraction means most foreground voxels were excluded. With an absolute filter, compare the reliability distribution with your threshold. With a percentile filter, `qc_reliability_threshold` shows how the threshold moved between frames. |
| Were velocities valid? | `qc_invalid_velocity_fraction`, `qc_invalid_reliability_fraction` | Should be 0 or very small. Non-finite values are excluded, never replaced by 0. |
| How much was measured? | `qc_n_analysed_voxels`, `qc_foreground_fraction` | Tiny counts make every feature noisy. Occupancy differences between conditions change what the foreground holds. |
| Were the regional features well supported? | `qc_n_regions`, `qc_n_regions_analysed`, `qc_region_grid_coverage` | Regional features need at least 2 analysed regions; more is better. Coverage below 1 means partial edge regions were left out. |
| Are nuclei of similar size? | `qc_object_mean_voxels`, `qc_object_mean_z_extent`, `qc_n_objects` | The optical-flow gain depends on nuclear size and Z extent ([Validation](validation.md)). A size difference between conditions is a confounder of speed. Objects are 3D connected components of the foreground, so touching nuclei count as one object. |
| Did the brightness change? | `qc_brightness_change_per_frame` | The relative brightness slope per frame in each window (always measured, on raw intensities). Above 0.02 (2 %/frame) is flagged. |
| Similar intensity? (opt-in) | `qc_foreground_intensity_mean` | Only with *Also report intensity-based QC* ticked in section 2. |

In `features_per_fov.csv` the QC columns are time averages, like the features. Use
`features_per_frame.csv` to see them frame by frame.

### Undefined values

Empty cells are values that do not exist, never zeros. `undefined_features` gives the reason for
each one, for example `no analysed voxel (empty foreground or nothing passes the reliability
criterion)`, `no motion threshold was set`, `per-slice 2D optical flow has no axial component`, or
`3D speed needs X, Y, Z and time calibration (one physical unit)`. In `features_per_fov.csv` it
gives the count of defined frames, for example `0 defined frame(s) of 9`.

---

## Warnings

Warnings do not stop the run. They are printed after the example run (section 2) and in the
section 3 table, and stored in the `warnings` column of `fovs.csv` and in `run_manifest.json`.

| Warning (start of the text) | Cause | What to do |
|---|---|---|
| `The global brightness changes by up to X% per frame (optical flow reads part of it as motion; consider brightness equalisation)` | `qc_brightness_change_per_frame` above 0.02 in at least one window of the field of view. | Compare `qc_brightness_change_per_frame` between conditions. If it differs or is large, consider a [brightness correction](theory.md#7-brightness-change-and-optional-correction) (for every condition). |
| `... (brightness equalisation was applied to the optical-flow input)` | Same, with a correction switched on. | Check that the correction removed the artefact (speeds stable over time, `vz` near 0). |
| `The header states pixel_size_x=… but … was used.` | The image header's calibration differs by more than 1 % from the confirmed calibration. | Check which value is right. Images with different acquisition settings belong in separate runs. |
| `The Z stack (N slices) is shorter than the spatial derivative kernel …` | 3D mode with fewer slices than `2·ceil(3·xyzSig) + 1`. | Treat axial features as experimental, or use per-slice 2D flow. |
| `Whole-image measurement: background and nuclear occupancy may influence the features.` | Foreground set to *none*. | Prefer an intensity-threshold foreground for comparisons. |

Calibration issues are also shown when you confirm section 1 and recorded in
`run_manifest.json` (`calibration_issues`):
- `XY pixel size or frame interval is unknown: velocities stay in pixels/frame ...`
- `Z spacing is unknown: axial velocities stay in slices/frame ...`

---

## QC figures

With **Save QC figures of every FOV** ticked in section 3 (the default), the app saves figures in
`<run>/qc/` for every field of view whose optical flow completed. The figures only display saved
results; they compute no new numbers. If `<run>/qc` already exists, nothing is overwritten.

| File | What it shows | What to check |
|---|---|---|
| `qc/<fov_uid>/input_montage_z<z>.png` | The video at the middle Z slice, every time point, on one shared raw-intensity scale | Drift, focus loss, bleaching or brightening, frames that look different |
| `qc/<fov_uid>/foreground_t<NNNN>.png` | Raw slice and the foreground outline at each analysed time point, with the percentage of the slice in the foreground (only with a threshold foreground) | The outline follows the nuclei, without background or holes |
| `qc/<fov_uid>/flow_t<NNNN>.png` | Three panels at each analysed time point: the image with flow vectors (colour = direction, −180° to 180°, y down; **unreliable or out-of-foreground vectors in grey**), the XY speed map (px/frame), and log10 reliability | Reliable vectors on nuclei, plausible directions; no large speeds in empty regions counted as reliable |
| `qc/<fov_uid>/features_over_time.png` | Per-frame median speed, global XY coherence and `qc_reliable_fraction` | Stable values, or a smooth trend; one outlier frame can bias the average |
| `qc/feature_histograms.png` | Histograms of the same three columns over every frame of the run, with the number of undefined values | Outlier fields of view or frames |

The Z slice shown is the middle slice. Velocities in the figures are in upstream units
(pixels/frame). For flow reused from an earlier run, the figures read the flow from that run's
folder.

The example processed in section 2 shows the same flow panels (without the grey reliability
marking) and the per-frame plots, so you can adjust settings before processing everything.

---

## Before you trust a comparison

- [ ] QC columns are similar between conditions, or their differences are reported.
- [ ] The foreground and flow figures look right for a few fields of view of every condition.
- [ ] The effect holds in the per-frame table, not just in one time point.
- [ ] The effect is seen in each biological repeat, and the paired test on repeat means (3 or
      more repeats) supports it. A PCA/UMAP separation or the FOV-level screen alone is not
      enough.
- [ ] Axial features, if used, are treated as experimental.
- [ ] Speeds are described as relative optical-flow speeds, not calibrated displacements.

See [Interpreting results](concepts.md) for the reasoning behind each point.
