# MorphoBricks conventions in the OpticalFlow3D Profiler

The profiler follows three MorphoBricks conventions: the experiment folder layout, the feature
column names and the MorphoCoverage statistics. It **imports no MorphoBricks package**. The
rules were reimplemented from the sources below (all MIT licence, CellMigrationLab).

| Convention | Source | Commit | Profiler module |
|---|---|---|---|
| Folder layout, labels, `position_id` | morphobricks-preprocessing `docs/contract.md` §1, `discovery.py`, `image_names.py` | `7cfe8e4` (2026-11-22) | `discovery.py` |
| Feature column names | MorphoFeature `src/morphofeature/naming.py` (decision D09) | `7537a06` (2026-11-22) | `naming.py` |
| Condition statistics | MorphoCoverage `docs/report/conditions.md`, `statistics.cohen_d`, `sampling_unit/contrast_cells.py`, `sampling_unit/_balanced.py`, `sampling_unit/_cell_chance.py` | `209b9be` (2026-11-18) | `statistics.py`, `comparison.py` |

## Experiment folder

```
<experiment root>/<condition>/<biological repeat>/<technical repeat>/<image>.tif
```

- Only images in leaf folders are fields of view. A folder that holds both images and
  subfolders is refused (`tiff_outside_leaf`).
- Every level is optional. A missing level is recorded as `single`. A single folder of images
  gives `single/single/single`. A folder named `single` is accepted only in lower case and only
  when it is the only folder in its place.
- `position_id` is the image name without `.tif`/`.tiff`, including a preceding `.ome`. A field
  of view is identified by `condition`, `biological_repeat`, `technical_repeat` and
  `position_id`.
- These are refused:
  - names with outer spaces, or names a table reader would read as missing (`NA`, `nan` and so
    on);
  - two labels of one level that differ only in case;
  - two images of one leaf with the same `position_id`;
  - an image named as a mask of another image (`f1_mask.tif` beside `f1.tif`);
  - more than three folder levels;
  - links that leave the experiment folder;
  - OME-Zarr images.
- These are ignored: dot-files, `Thumbs.db`, `desktop.ini` and `__MACOSX`.
- Videos have a single channel (a C axis of length 1 is accepted; more channels are refused).
- Masks are not used: there is no masks folder and no `mask_path`. The foreground is an
  intensity threshold, or none (whole image).
- The MorphoBricks description files (`morphobricks.toml`, `experiment_design.csv`) are not
  read.

A metadata CSV with the same columns plus `image_path` is still accepted.

## Feature tables and column names

- `features_per_frame.csv`: the full table, one row per field of view and optical-flow time
  point. It has the four identity columns, `t` (the source time point, 0-based) and `time_min`.
- `features_per_fov.csv`: each feature **averaged over time** per field of view, under the same
  column names (the circular mean for directions; undefined frames are left out, never set to 0).
- Feature columns follow the MorphoBricks scheme for single-channel data,
  `{object_set}__{feature}`, for example `Nuclei__speed_xy_median`:
  - with an intensity-threshold foreground, the object-set token is the foreground name
    (default `Nuclei`);
  - without a foreground it is the MorphoBricks compartment `whole` (`whole__speed_xy_median`).
- `qc_*` columns are observation metadata and keep their plain names.
- Nothing is averaged per biological repeat in a saved table.

## Statistics (MorphoCoverage rules, FOV as observation)

`comparison.compare_conditions` compares every condition with the declared control on every
biological feature. QC confounders are compared as a separate family.

1. **Cohen's d** on the fields of view, pooled and per repeat (`condition_tests_per_repeat.csv`).
2. **The FOV-level randomization test** on Cohen's d. Labels are shuffled over the fields of view,
   and `p = (extreme + 1) / (B + 1)` with 9999 shuffles.
   - It is reported on raw values and on values divided by the mean of the control **of the same
     biological repeat**.
   - The test on raw values is withheld when the control pools repeats that the condition was not
     imaged in.
   - The repeats are **unbalanced** when one repeat has more than 25% more FOVs than another, or
     when the control pools other repeats. In that case the **balanced permutation test** is also
     given: the median d over 100 draws, each taking the same number of FOVs from every repeat,
     with labels shuffled within each repeat (999 labellings).
   - A repeat with fewer than 5 FOVs, or with less than a quarter of the median repeat's FOVs, is
     left out of the balanced test.
   - The screen reads the normalised version, or the balanced one when the repeats are unbalanced.
   - This test is **exploratory**: it treats fields of view as independent. `chance_low` and
     `chance_high` give its false-positive rate when the effect varies between repeats by 0.25 to
     0.5 SD, `2 P(Z > 1.96 / sqrt(1 + n s² / 2))`.
3. **The paired t-test on the repeat means**, from 3 biological repeats that hold both the
   condition and the control.
   - It uses log ratios when every observation of the feature is positive, and differences
     otherwise. The scale is chosen once per feature.
   - The exact sign-flip test is added from 6 repeats.

Benjamini-Hochberg q-values are computed per p column, over every feature and condition of a
family. A test at `p ≤ 0.05` is rerun with `max(B, ceil(K / 0.05))` shuffles, so that its q can
fall below 0.05. Every shuffle is seeded from the seed and the test's identity, so results do
not depend on the order of rows or tests.

Verdicts:

| Verdict | Condition |
|---|---|
| significant across repeats | `q_screen ≤ 0.05` and `q_repeats ≤ 0.05` |
| candidate (exploratory FOV-level screen only) | screen only |
| consistent across repeats (paired test only) | paired test only |
| no difference detected | neither |
| not tested | no test could be run |

Not reimplemented:
- several controls and the contrast table;
- within-repeat tests over technical repeats;
- the population, novelty and "did I image enough" analyses.
