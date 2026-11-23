# Response to the adversarial feature audit (commit 11787e9)

> **Historical.** Since this response the condition statistics, the PCA and their tests
> (Hedges' g, pairing, degenerate tests, `profile_analysis`) were removed: MorphoCoverage now
> does the comparison (`coverage.py`). The feature-extraction rows still apply.

The audit was an external review (ChatGPT) of `main` at commit `11787e9`. Each finding was
checked against the code, and every confirmed defect has a regression test in `tests/profiler/`.

## Confirmed defects: fixed

| Finding | Fix | Test |
|---|---|---|
| Incompatible runs could be combined | `analysis.load_runs` compares the optical-flow, feature and foreground settings in each `run_manifest.json`, and refuses runs that differ (it names the differing settings) | `test_runs_with_different_settings_are_not_combined` |
| Uncalibrated px/frame and slice/frame treated as one unit | `VelocityScale.consistent` now requires µm/min on all axes. Without full calibration, 3D speed, 3D coherence and the axial/lateral ratio are NaN, with the reason | `test_uncalibrated_3d_features_are_undefined_not_pixel_slice_mixtures` |
| Undefined 3D speed became a zero moving fraction (NaN → 0) | Regional speed features take the undefined-speed reason and stay NaN. XY regional coherence stays defined | `test_undefined_3d_speed_never_becomes_a_zero_moving_fraction` |
| A NaN reliability value invalidated a percentile frame | Thresholds and reliability statistics use finite reliability values only. Non-finite reliability is never "reliable" and is counted in the new column `qc_invalid_reliability_fraction` | `test_non_finite_reliability_never_sets_the_threshold` |
| Repeats merged across runs when labels are reused | Combined tables carry `repeat_id`: by default `<run>/<label>`, or the bare label when the user declares labels shared. Comparisons, figures and warnings use it | `test_repeat_labels_are_scoped_to_their_run_unless_shared`, `test_repeat_identity_column_is_used` |
| A third condition broke a valid paired comparison | Pairing considers only the two compared conditions | `test_unrelated_conditions_do_not_break_pairing` |
| Missing pairs disappeared silently | `repeats_excluded`, `n_fovs_used` and `n_fovs_missing` are reported. Repeats without a counterpart are refused; repeats whose values are all missing are left out and listed | `test_missing_pairs_are_recorded` |
| Degenerate t-tests reported as performed | Zero variance, or a non-finite statistic, gives "not interpretable" with the reason. Hedges' g carries `hedges_g_note` | `test_degenerate_tests_are_flagged`, `test_hedges_g` |
| Signed `vz_mean` could enter the PCA | `vz_mean` is now classified as orientation-dependent, like `vx_mean` and `vy_mean` | `test_core_selection_and_signed_vz_never_enter_pca` |
| Shallow-Z warning discarded | Validation warnings, including the shallow Z stack, go into the warnings of each field of view in `fovs.csv` and the manifest | `test_shallow_z_warning_is_recorded_per_fov` |
| Feature settings checked only after the optical flow | `validation.check_feature_settings` runs before any computation. It checks the reliability value and percentile range, region, window and bin sizes, and the threshold value | `test_feature_settings_are_checked_before_any_computation` |

## Design concerns: what changed

| Concern | Decision |
|---|---|
| Near-zero vectors weigh as much as large ones in angular features; one vector looks perfectly aligned | New settings: `min_direction_speed` (default 0, so only exact zeros are excluded until a value is validated on real data) and `min_direction_vectors` (default 20; below it the angular features are NaN). Speeds are never changed |
| Binned entropy depends on image orientation | One bin is centred on the dominant direction, so rotating the image does not change the entropy (`test_angular_entropy_does_not_depend_on_image_orientation`) |
| Local coherence biased upwards in sparse windows | New setting `min_local_vectors` (default 5): sparser windows are undefined (`test_sparse_windows_have_no_local_coherence`) |
| Edge regions are discarded | New QC column `qc_region_grid_coverage` reports the fraction of the image covered by full regions. Regions are not treated as independent samples |
| Correlated PCA inputs; FOV weighting | The default PCA input is a **core** set of 12 interpretable features (`profile_analysis.CORE_FEATURES`); `selection="families"` keeps the old behaviour. A warning appears when repeats have different numbers of FOVs |
| Whole-image "foreground intensity" | `qc_foreground_intensity_mean` is NaN without a foreground |
| Overflow in sum of squares | Speeds are computed with `numpy.hypot` |
| Brightness-dependent absolute reliability | Kept as a predeclared setting, applied identically to every field of view. The README and notebook already ask users to compare the intensity, reliability and reliable-fraction QC columns between conditions, and to use percentile mode as a sensitivity check. Runs with different reliability settings can no longer be combined |
| Short, overlapping temporal series | Slopes stay descriptive. The core PCA set includes only two temporal SDs |
| Anisotropic Z | Axial features stay excluded from the PCA by default. The synthetic demo measures the axial noise floor (`docs/validation.md`) |
