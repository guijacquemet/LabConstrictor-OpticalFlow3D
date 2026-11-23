# MorphoBricks conventions in the OpticalFlow3D Profiler

[:arrow_left: Documentation index](index.md)

The profiler follows the MorphoBricks experiment folder layout and feature column names
(reimplemented from the sources below), and hands the condition statistics and the report to
**MorphoCoverage, a dependency** pinned to a commit (all MIT licence, CellMigrationLab).

| Convention | Source | Commit | Profiler module |
|---|---|---|---|
| Folder layout, labels, `position_id` | morphobricks-preprocessing `docs/contract.md` §1, `discovery.py`, `image_names.py` | `7cfe8e4` (2026-11-22) | `discovery.py` |
| Image headers: axes, shape, pixel type, physical sizes; experiment-wide header checks | morphobricks-preprocessing `inspect_tiff`, `header_axes`, `check_metadata(files, allow_z=True)` (contract §20), **imported** | `957158a` (2026-11-23) | `image_io.py`, `experiment_check.py` |
| Feature column names | MorphoFeature `src/morphofeature/naming.py` (decision D09) | `7537a06` (2026-11-22) | `naming.py` |
| Condition statistics and report | MorphoCoverage (`report`, `html_report`), **imported** | `209b9be` (2026-11-18) | `coverage.py` |
| Brightness trend and corrections | morphobricks-normalization `time_series` (contract §3.7, plan N72), **imported** | `26112a5`, the v0.8.0 release commit (2026-11-23) | `brightness.py` (central frame of each flow window as the reference) |

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

From Python, a metadata table with the same columns plus `image_path` is accepted by
`experiment.validate_metadata` (a pandas DataFrame); the notebook reads experiment folders only.

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

## Statistics and report: MorphoCoverage

`coverage.py` turns the per-FOV table into MorphoCoverage's two input tables and its `Setup`,
then runs its `report()` and its full `html_report()`. Nothing statistical is computed here.

- **Observation:** the field of view (`observation_unit="fov"`), its time-averaged profile from
  `features_per_fov.csv`. Time points are never replicates.
- **Features:** the biological features (and the experimental axial ones on request; an axial
  readout is always included). `qc_*` columns, directions and features undefined in every field
  of view are not declared; the last are listed.
- **Repeats:** MorphoCoverage pairs biological repeats across conditions only by a confirmed
  `repeat_group`. The design step asks the user to confirm that a biological-repeat label is the
  same repeat in every condition. The repeat identity (the folder label for one run or for runs
  whose labels are declared shared, `<run>/<label>` otherwise) becomes both `biological_repeat`
  and `repeat_group`, so the field-of-view key stays unique across runs. A design in which no
  repeat holds both the control and another condition is refused.
- **Design:** the control, the readout and the seed are chosen in the notebook. Each report
  folder holds `report.html` with its figures and data, `morphocoverage_objects.csv`,
  `morphocoverage_fovs.csv` and `design.json` (the design, the declared features, the runs and the
  MorphoCoverage version and commit).

What the report contains is described in MorphoCoverage's own documentation
(`docs/report/conditions.md`): Cohen's d on the fields of view, the exploratory FOV-level
randomization screen, the paired t-test on the repeat means, Benjamini-Hochberg correction, the
PCA/UMAP and each feature's figure.
