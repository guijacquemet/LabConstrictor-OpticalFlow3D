# Response to the re-validation of the second audit's fixes (main `1ce386a`)

The re-validation reviewed profiler `main` at `1ce386a` (PR #16) against `01bc749`,
morphobricks-normalization at `f2aa732` and MorphoCoverage `209b9be`. Its verdict was BLOCK.
Each finding was checked against the code. Every change below has a regression test in
`tests/profiler/`, or, for R5, in morphobricks-normalization's `tests/test_time_series.py`.

## Highest priority

| Finding | Disposition | Test |
|---|---|---|
| R1 / C4 Angular entropy not rotation-invariant at bin edges; discontinuous at the anchor threshold; undefined for a prime `angle_bins` | Fixed by redefining the feature (owner decision). Any fixed-bin histogram jumps at its edges, and no bin anchor is both orientation-free and continuous. `xy_angular_entropy` is now the normalised entropy of a wrapped-normal kernel density of the directions, with a standard deviation of 360°/`angle_bins` and the scale `(H − H_kernel) / (log 2π − H_kernel)`: 0 is one direction and 1 is uniform. There are no bins or anchor. **Values differ from earlier runs**, and the run manifest's profiler source hash tells the two apart. | `test_angular_entropy_is_rotation_invariant_on_and_near_bin_edges` covers rotations by 10°, 180°, half a bin, 1e-9° and 1–2 ULPs. Also `test_angular_entropy_is_continuous_and_bounded` and `test_angular_entropy_is_defined_for_a_prime_resolution`. |
| R2 Desktop requirements and lock files pinned normalization `b3a8104` | Already corrected on `main`: the post-merge "Updates on notebook change" workflow regenerated the four files at `f2aa732` as `284e960`, after the audited `1ce386a`. Drift now fails CI: every git pin of `requirements.yaml` must match in the four files, `tools/requirements-checks.txt` and the Colab cell, and the Colab cell's version pins must match the specification. | `test_dependency_pins.py`, which fails on `1ce386a`'s `requirements.txt` |
| R3 / C1 Axes named by a header without T (`ZCYX`), or with unknown axes (`QZYX`), could be reinterpreted | Fixed. Every position whose header letter is T, Z, C, Y or X must be confirmed with that letter (`named_axis_conflicts`). Only tifffile's unknown positions (Q, I) are left to the user. | `test_axes_named_without_t_cannot_be_read_as_time`, `test_known_axes_keep_their_role_when_others_are_unknown` |
| R4 / C2 A generated run label could equal another run's folder name | Fixed. Every label is `<folder name>-<16 hex of the SHA-256 of the resolved path>`, the same for a run whatever else is loaded. Two runs with one label are refused. | `test_a_run_label_never_equals_another_runs_folder_name` (the three-path case) |

With **shared repeat labels** ticked, the results step now explains what the box asserts. It names
every label that appears in several runs and is counted as one repeat. The software cannot check
this assertion (`test_shared_repeat_labels_are_named_for_the_user`).

## Provenance, immutability and recovery

| Finding | Disposition | Test |
|---|---|---|
| C3 / startup not atomic: an interrupted run could be re-entered, and two processes could start in one folder | Fixed. `run_started.json` is created exclusively (`O_CREAT \| O_EXCL`) after the settings checks and before anything is written. A claimed folder is refused, whether its run finished, is still running or was interrupted. | `test_an_interrupted_or_concurrent_run_is_never_entered_again` (8 concurrent claims, exactly one succeeds) |
| No profiler identity for numerical changes | Fixed. `run_manifest.json` records `profiler.version` and `profiler.source_sha256`, a SHA-256 of every module of the package. | `test_the_manifest_identifies_the_profiler_source` |
| M2 Corrected-flow identity omitted the adapter; the install commit split identical code | Fixed. The identity is the normalization version plus the SHA-256 of `time_series.py` and of `brightness.py`. The commit is not part of it; the commits of git-installed dependencies are recorded in the manifest's environment. | `test_correction_code_identity_invalidates_cached_corrected_flow` (real byte edits of either module) |
| M7 The partial flow folder stayed after a failure writing the manifest or in `os.replace` | Fixed. The cleanup covers computation, manifest and publication, and removes only the folder the call created. | `test_a_failure_up_to_publication_removes_only_the_partial_folder` (TIFF, manifest, publish), which fails on `1ce386a` |

## Numerical validation and smaller findings

| Finding | Disposition |
|---|---|
| R5 `equalise_brightness` factor underflow returned a black frame; the finiteness check allocated a whole-window boolean array | Fixed in morphobricks-normalization PR #115 (release v0.8.0). A factor that is not finite or not above 0 is refused, and finiteness is checked one time point at a time. Finite results are unchanged bit for bit. |
| M8 / m4 `tSig=1e308` raised `OverflowError` in the resource estimate | Fixed. `check_time_and_depth` compares `6·tSig + 1` with the frame count before computing the window, `window_length` raises a named error, and the notebook's estimate runs the check first (validation test and notebook Estimate test). |
| M6 A mismatch was recorded as a generic "parameters" difference | Fixed. Every differing value is named, for example `parameters.w_sig: 4 → 2`. |
| m1 `image_path` was trimmed | Fixed. Paths are kept literally (`test_image_paths_are_kept_literally`). |
| m3 `qc_x` beside `Nuclei__qc_x`, and repeated CSV headers renamed `x.1` by pandas, escaped the duplicate check | Fixed. Both are refused (`test_repeated_or_shadowed_feature_columns_are_refused`). |
| m6 A brightness change recorded as null was given the central-frame reason | Fixed. It now says the cause is not recorded (`test_an_undefined_brightness_change_gets_the_reason_its_record_supports`). |
| E24 A symbolic link inside the report folder served a file outside it | Fixed. Paths resolving outside the folder give 404 (`test_the_report_server_serves_only_files_inside_its_folder`). The printed note says the 127.0.0.1 link opens on the user's own computer, so on a remote Jupyter server the file browser is the way to open the report. |
| Feature dictionary lacked the no-anchor condition | Superseded: the anchor is gone, and the dictionary describes the kernel-density definition. |
| M4 test gap | The OME default-unit note is asserted in `header_summary`, the table section 1 shows before confirmation. |

## Not executed here

The desktop installer build, a run on real Colab and a run of the installed desktop app remain
release checks.
