# Response to the round-3 audit (PR #17 `3b3b327`, PR #18 `a3960f5`)

The round-3 audit reviewed PR #17 (`3b3b327`), and PR #18 (`a3960f5`) separately. Its verdict was
BLOCK. Each finding was checked against the code. Every change below has a regression test in
`tests/profiler/`.

## Release gates

| Gate | Disposition | Test |
|---|---|---|
| 1. Named non-time axes (`EZYX`, `HZYX`, `AZYX`, `RZYX`, `0ZYX`) were accepted as `TZYX` | Fixed. Only tifffile's unknown axes (`Q`, `I`) are now the user's to confirm. Any other letter the header names is a dimension the app does not analyse, and the file is refused. Tested with real TIFFs. | `test_other_named_axes_are_refused_not_read_as_time`, `test_unknown_axes_remain_the_users_to_confirm` |
| 2. Runs with other feature definitions or code could be combined (old binned and new kernel entropy; the `vx_*`/`vy_*` reclassification) | Fixed. `feature_dictionary.json` records `feature_implementation`: the SHA-256 of every definition and of the modules that decide feature values. Runs are combined only when both are equal. An older run without the identity can be loaded alone but not combined. A dictionary that describes a column twice is refused. | `test_runs_with_other_feature_definitions_or_code_are_never_combined` (other code, other definition, older run), `test_a_dictionary_describing_a_feature_twice_is_refused` |
| 3. The kernel entropy's 2^16 grid did not resolve fine kernels (errors of about 3e-4 at 10,000 bins; negative densities beyond) | Fixed by a bound. Measured on the grid, the 1e-6 tolerance holds up to `angle_bins` = 360 (a 1° kernel): a single direction at any grid phase is at most 8.4e-7 from 0, and rotation changes the value by at most 1.5e-7. Values above 360 are refused (`angle_bins_too_large`). | `test_angular_entropy_holds_its_tolerance_up_to_the_finest_resolution` (36 and 360: grid phases, rotations, density non-negativity), `test_angular_entropy_refuses_unresolved_resolutions` |
| 4. Normalization PR #115 not integrated | Already done: PR #19 (`1a9fbe1`) pins `26112a5` in every installation path. The post-merge conda install test and the profiler checks passed. The `v0.8.0` tag still has to be created on `26112a5`. | `test_dependency_pins.py` |
| 5a. Refusing a finished run older than the claim wrote an empty `run_started.json` into it | Fixed. The manifest is checked before claiming, and a claim made just before a manifest appeared is removed. The concurrency test now starts its eight claims together (barrier). | `test_refusing_a_finished_run_never_writes_into_it` |
| 5b. The temporary flow folder was named by PID only | Fixed. It is created exclusively with a unique name (`tempfile.mkdtemp`, readable permissions as before), so the cleanup can only remove its own folder. | `test_each_flow_run_owns_its_temporary_folder` |
| 5c. Changing `flow_window` kept a cached corrected flow; reused flow carried brightness QC of another implementation | Fixed. The correction identity includes the SHA-256 of `flow_window`'s source. Flow manifests record `brightness_qc`. Reused flow with QC from another brightness implementation keeps its velocities, but reports the brightness QC as undefined with the reason, plus a "Brightness QC not reused" warning. | `test_correction_code_identity_invalidates_cached_corrected_flow`, `test_reused_flow_keeps_its_velocities_but_not_stale_brightness_qc` |
| 6a. The per-slice output estimate assumed 4-byte reliability (`calc_flow2D` returns float64) | Fixed. `output_bytes_per_voxel` follows the arrays `compute_frame` returns. | `test_output_estimate_matches_the_arrays_actually_returned` (both modes, both output types) |
| 6b. `xyzSig=1e308` raised `OverflowError`; `tSig=0` claimed the run folder | Fixed. `check_sigmas` requires positive, finite sigmas of at most 1e4. It runs before any window or kernel size is computed, and in `checked_settings` before a run folder is claimed. | `test_sigmas_must_be_positive_so_a_window_has_three_frames`, `test_invalid_sigmas_are_refused_before_a_run_folder_is_claimed` |
| 6c. Non-finite calibration accepted (`inf`; `1e308` mm overflowing) | Fixed. Calibration input and the converted value must both be finite. | `test_calibration_must_be_finite_before_and_after_conversion` |
| 7. Deployment tests | Not run here: the installer build, Colab and the installed desktop app remain release checks. | — |

## Other findings

| Finding | Disposition |
|---|---|
| M6: a changed list entry was reported as `(long value)` | The changed entry (`frame_map[10].source_frame: 13 → 99`) or a changed length is now named. |
| m1: the notebook trimmed typed folder and run paths | Paths are used as typed; blank lines are still ignored. |
| C2: `run_labels([p, p])` and symbolic-link aliases were collapsed silently | Both are refused as the same run folder. |
| R2: only the Colab cell's own version pins were compared | Every version pin of `requirements.yaml` must also be the same in `requirements.txt` and `requirements_gpu.txt`. |
| Regional features depend on how the XY grid lies on the sample | They stay readouts. Their definitions and the docs now say that the grid moves with image rotation, so samples should be imaged in a similar orientation. |
| ULP test moved one ULP twice | Fixed: one ULP, then two. |
| E24 hard links | Accepted as documented path-based behaviour. A hard link inside the report folder is a file in that folder. |
| Entropy memory (about 374 MiB transient for 10^7 directions) | Noted. It is linear and below the optical flow's own peak. |

## Documentation audit of PR #18 (`a3960f5`)

The documentation audit's verdict was "not ready, documentation corrections required". Several
of its points were code defects already fixed above: named axes, combining runs, the entropy
bound and the per-slice estimate. The other corrections are listed below.

| Point | Disposition |
|---|---|
| QC undefined conditions were generic | Fixed in `feature_dictionary.py`, so the glossary and every future `feature_dictionary.json` carry them. Each QC column has its own condition. Counts and grid coverage are never undefined. `qc_foreground_fraction` is 0 for an empty foreground. Brightness QC is measured on the whole raw window. |
| `speed_3d_*`, regional denominators, the 1e-12 resultant threshold, undefined-speed propagation | Added to the definitions. 3D speed is in µm/min. `regional_moving_fraction` is a fraction of eligible regions, and one region is enough. |
| X/Y component statistics; local coherence and regional grid orientation | The glossary family texts and `results.md` now distinguish global, orientation-independent statistics from spatial measurements fixed to the image grid. |
| Default readout could fall back to `vz_sd` | Code fixed: after the median speeds, the mean lateral speed, then the first lateral feature. Tested. |
| Section 1 calibration comparison omitted Y | Code fixed. Tested with a Y-only difference. |
| The run-name statement, the orientation-descriptor list, the readout fallback, the percentile reliability wording, brightness flagged on its absolute value, the `auto` ratio (Z / X), the manifest versus `design.json`, global versus per-field-of-view checks, "another example" possibly the same image, temporary folders after a hard crash | Corrected in the pages. |
| Disk figures | Corrected from the arrays actually written: 9.4 GB (float64), 5.4 GB (float32) in 3D; 8.0 GB or 5.4 GB per slice. |
| "Built and tested" platform claims | Now "built for Linux x86-64 only; release 0.1.0 was installed and run on Linux; each release is tested before publication", in the README, the docs and the App Centre limitation. |
| First reliability threshold | A short procedure was added to `workflow.md`: explore with `none`, read the reliability QC, choose one absolute threshold. |
