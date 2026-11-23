# AGENTS.md — OpticalFlow3D Profiler

Guidance for AI agents and people changing this repository.

## Layout

- `src/opticalflow3d_profiler/`: the package. One job per module:
  - **pure:** `config`, `validation`, `flow_features`, `feature_dictionary`, `temporal_features`,
    `experiment`, `naming`, `brightness`, `foreground`, `synthetic`;
  - **I/O:** `image_io`, `discovery`, `experiment_check`, `flow_backend`, `flow_store`, `results`,
    `analysis`, `coverage` (MorphoCoverage input and report), `figures`, `qc_export`;
  - **orchestration:** `pipeline`, `demo`;
  - **UI:** `notebook_ui` (sections 1-2), `notebook_analysis_ui` (sections 3-4 and the demo),
    `progress` (tqdm bars), `report_link` (opens the report in a new tab).
- `src/opticalflow3d_profiler/_upstream/calc_flow.py`: an **unchanged** copy of OpticalFlow3D at
  commit `6b88604`. Never edit it: `flow_backend.upstream_identity` checks its SHA-256. To update
  it, replace the file, change the pin and hash in `_upstream/__init__.py` and `README.md`, and
  rerun the parity and validation tests.
- `notebooks/OpticalFlow3D_Profiler/`: the single user notebook and its `requirements.yaml`
  (exact pins). The template merges these pins into `requirements.txt`. The cells only call
  `notebook_analysis_ui.build()`.
- `tests/profiler/`, `tools/check_profiler.py`, `tools/benchmark_flow.py`, `docs/validation.md`.
- Condition statistics and the report are MorphoCoverage's, and the brightness measurement and
  corrections are morphobricks-normalization's `time_series` (both dependencies pinned to a commit
  in `requirements.yaml`, the Colab install cell and `tools/requirements-checks.txt`); never
  reimplement them here (`brightness.py` only applies them to a flow window). The folder layout and the column names follow MorphoBricks
  (`docs/morphobricks.md`). Keep the FOV identity (`condition`, `biological_repeat`,
  `technical_repeat`, `position_id`), the `{object_set}__{feature}` names (single-channel
  videos; `qc_*` columns are metadata) and the field of view as the observation.
- Everything else (`.tools`, `.github/workflows` except `profiler_checks.yml`, `app/`,
  `construct.yaml`) belongs to the LabConstrictor template. Do not edit it by hand, except
  the app images: `app/logo/` is drawn by `tools/draw_icon.py` and referenced by the image keys
  and icon `extra_files` of `construct.yaml` and the icons of `app/menuinst/notebook_launcher.json`.

## Rules (MorphoBricks spec §9 conventions)

- Python 3.11. Ruff (`src/ruff.toml`), 100 columns, NumPy docstrings, annotations, and
  `from __future__ import annotations`.
- At most 600 lines per module, 60 executable lines per function, complexity 15, and 8 parameters.
- Never guess axes, channels, calibration, conditions or replicates. Never replace NaN or invalid
  velocities with zero. Never normalise intensities. Never project Z. Never modify inputs.
  Never overwrite a run.
- Any value that changes a number belongs in a `config` dataclass, so it is recorded in the run
  manifest. Reuse of cached optical flow requires an identical identity and identical file hashes.
- Every new feature needs a `feature_dictionary` entry with its applicability and the reason it
  can be undefined.
- Out of scope for V1: tiling, GPU, multiprocessing, segmentation, masks, tracking, OME-Zarr,
  Fiji/napari/QuPath bridges, and parameter optimisation.

## Checks

`python tools/check_profiler.py` must pass before a pull request (the CI workflow `Profiler checks`
runs it). Report the tests you actually ran. Real-data claims need real data.
