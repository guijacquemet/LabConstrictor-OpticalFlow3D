# Response to the second adversarial audit (main `01bc749`, normalization PR #113)

The audit reviewed profiler `main` at `01bc749`, the pending branch at `ef66779`, and
morphobricks-normalization PR #113 at `8814dc1`. It found 4 critical, 8 major and 6 minor
defects. Each was checked against the code. Every fix has a regression test in `tests/profiler/`,
or, for m5, in morphobricks-normalization's `tests/test_time_series.py`.

## Critical

| Finding | Disposition | Test |
|---|---|---|
| C1 Confirmed axes could reinterpret axes the header names (Z read as T, C read as Z) | Fixed. When the header names its axes (OME, ImageJ), the confirmed axes must equal them (`axes_contradict_header`). Section 1 checks this for every image. | `test_axes_named_by_the_header_cannot_be_reinterpreted` |
| C2 Runs with the same folder name shared repeat identities | Fixed. Run labels are unique (folder name plus a hash of the full path when two runs share a name), and the combined FOV key is checked for uniqueness before MorphoCoverage. | `test_runs_with_the_same_folder_name_are_never_paired` |
| C3 A second call on a flow-only run replaced its manifest and status | Fixed. A run folder that holds a `run_manifest.json` is refused, flow-only runs included. The demo now runs flow and features in one call. | `test_a_run_folder_is_never_run_twice` |
| C4 Angular entropy changed with rotation when there is no mean direction | Fixed. The bins are anchored on the first non-zero circular moment whose order divides `angle_bins`. If there is none, the entropy is undefined, with the reason. Values with a mean direction are unchanged. | `test_angular_entropy_is_rotation_invariant_without_a_dominant_direction` |

## Major

| Finding | Disposition |
|---|---|
| M1 Normalization not a declared dependency | Already fixed on `main` by #15, after the audited revision: pinned in `requirements.yaml`, the lock files and the Colab cell. Now pinned at `f2aa732`, which includes the m5 fix. |
| M2 Correction code not part of the flow cache identity | Fixed. With brightness correction, the identity includes the morphobricks-normalization version, commit and `time_series` module SHA-256 (`test_correction_code_identity_invalidates_cached_corrected_flow`). Identities without correction are unchanged. |
| M3 `construct.yaml` listed removed modules | The release workflow regenerates `extra_files` from `src/` with `bump_constructor.py` before building, so a release bundles the current modules. The committed file is now regenerated too. |
| M4 OME time increment without a unit read as seconds | Kept. The OME-XML schema defines seconds as the default `TimeIncrementUnit` and µm for `PhysicalSize`, and MorphoBricks preprocessing reads it the same way. Every value read with a default unit is now named in a header note, shown before the user confirms (`test_ome_values_without_units_are_flagged`). |
| M5 Default readout could be an all-NaN 3D speed | Fixed. The default is a feature with values (`test_default_readout_is_a_feature_with_values`). |
| M6 Mismatched earlier flow failed the FOV | Fixed. A mismatch is a cache miss: the flow is computed in the new run, the reason is recorded in `flow_origin`, and the earlier result is untouched (`test_flow_with_other_parameters_is_recomputed_not_reused`). |
| M7 Progress bars and partial folders left behind on errors | Fixed. Every stage closes in `finally`, and a failing flow run removes its own `.partial` folder (`test_a_failing_window_closes_progress_and_removes_the_partial_folder`). |
| M8 Preview-slider errors escaped as tracebacks | Fixed. The sliders go through the guarded error display, which now also catches widget `TraitError`. |

## Minor

| Finding | Disposition |
|---|---|
| m1 Metadata identities were trimmed | Fixed: outer spaces are refused, never trimmed (`test_metadata_identity_whitespace_is_refused_not_trimmed`). |
| m2 A manifest missing a planned output was accepted | Fixed: every planned output must be listed, in order, with all its components (`test_a_manifest_missing_a_planned_output_is_refused`). |
| m3 Two columns with one feature key accepted on load | Fixed: refused by `load_runs`. |
| m4 One-frame windows: old code raised, new returns NaN | No valid setting gives one frame: the sigmas must now be positive finite numbers, so a window has at least 3 frames (`test_sigmas_must_be_positive_so_a_window_has_three_frames`). |
| m5 Equalisation could return infinite pixels | Fixed in morphobricks-normalization PR #114, merged as `f2aa732`: factors or values that overflow float64 are refused. |
| m6 Undefined brightness trend given the "not recorded" reason | Fixed: a recorded but undefined trend gets its own reason. |

The report server (E24) no longer lists directories.

Not executed here: a desktop installer build, and runs on real Colab and on a local installed
app. These remain release checks.
