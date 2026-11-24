# Response to the round-4 audit (PR #21 at `c82fd79`)

The round-4 audit reviewed PR #21 at `c82fd79`, against base `cbb400b`; its verdict was BLOCK.
The documentation commit `cf019a9`, pushed after `c82fd79`, had already corrected several of
the documentation points the audit lists:
- the run-startup text;
- the 4.7 GB figure in `getting_started.md` and `results.md`;
- the QC undefined conditions;
- the readout fallback;
- the absolute brightness change.

Each change below has a regression test in `tests/profiler/`.

| Gate | Disposition | Test |
|---|---|---|
| 1. Run and report names could leave their folder (`../experiment/rogue-run`) | Fixed. `results.contained` accepts one plain folder name only: no separator, no `..`, no absolute path, no outer spaces. The resolved destination, symbolic links included, must lie inside the parent. It is used by `create_run`, the notebook report step and `run_report`. Names are used as typed. | `test_run_and_report_names_never_lead_outside_their_folder` (seven escaping names, including a link) |
| 2a. An edited dictionary with its old hash was combined | Fixed. `load_runs` recomputes `definitions_sha256` from the dictionary's own definitions and refuses a mismatch, also for a single run. | `test_an_edited_dictionary_is_refused_even_with_its_old_hash` |
| 2b. The identity left out the velocity path | Fixed. `FEATURE_MODULES` adds `flow_backend`, `image_io`, `config`, `naming` and the vendored OpticalFlow3D code. `feature_implementation` also records the normalization identity, and all three values are compared. | `test_the_feature_identity_covers_the_velocity_code_and_normalization` |
| 3a. NaN thresholds read as an empty foreground or no moving region | Fixed. The notebook's `number()` refuses `nan`, `inf` and `-inf`. `check_feature_settings` refuses non-finite thresholds and cutoffs (`non_finite_setting`). | `test_nan_and_infinite_settings_are_refused_not_read_as_empty` |
| 3b. Calibration underflow to 0; a `Calibration` built in Python; header conversions | Fixed. Conversions refuse underflow. `calibration_issues` runs before a run folder is claimed. Header suggestions drop values that overflow or underflow when converted. | `test_calibration_underflow_and_direct_objects_are_refused` |
| 4a. Brightness QC identity left out `flow_window` | Fixed. Brightness QC is recorded and checked with `correction_identity`, which includes `flow_window`. | `test_reusing_flow_after_a_change_of_flow_window_leaves_brightness_qc_empty` (a real reuse cycle) |
| 4b. A manifest published after the claim's second check could be replaced | Fixed. The run manifest is written with `write_json_new`: a temporary file, then a hard link, which fails if the file exists. So a manifest published in the meantime is never replaced. | `test_a_manifest_published_meanwhile_is_never_replaced` |
| 4c. `chmod 0o755` widened permissions under a restrictive umask | Fixed. The temporary folder is created with `mkdir` under a unique name. `mkdir` is exclusive and follows the process umask; there is no chmod. | `test_flow_folders_follow_the_process_umask` (umask 077) |
| 5. Documentation | `validation.md`: 5.4 GB with float32. `theory.md`: the measured rotation errors (1.5e-7 in our tests, 2.5e-7 in the independent sweep), stated as sampled maxima below the 1e-6 tolerance, not proven bounds. Run and report name rules, plus the new messages, added to `workflow.md`. | — |
| 6. Tests | The pin test also checks the lock files (one locked version per specified package) and `tools/requirements-checks.txt`. The named-axis test fails instead of skipping if tifffile reads an axis string differently. | — |
| 7. Deployment | Not run here: the installer build, Colab and the installed desktop app. | — |

## Smaller findings

| Finding | Disposition |
|---|---|
| `estimate_resources(tSig=1e300)` | Refused (`check_sigmas`). |
| `angular_entropy([])`, `[NaN]` returned 0.15 | Refused (`ValueError`). |
| `frame_features` with `angle_bins=361` and few vectors | Refused at the start of `frame_features`. |
| Estimates are array payloads, not TIFF sizes | Documented as approximate. The TIFF header overhead is a few kB per file. |
| Windows and case-insensitive file systems | Not tested here. |
