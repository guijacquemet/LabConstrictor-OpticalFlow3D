# OpticalFlow3D Profiler

**Status: experimental.** A LabConstrictor desktop app that quantifies nuclear motion in 3D
fluorescence time-lapses. It runs the original [OpticalFlow3D](https://github.com/aicjanelia/OpticalFlow3D)
algorithm (HHMI Janelia, BSD-3-Clause, unchanged copy pinned at commit `6b88604`), turns the
velocity fields into motion profiles per field of view, and compares experimental conditions
with [MorphoCoverage](https://github.com/CellMigrationLab/MorphoCoverage) (a pinned dependency).

**Documentation:** [docs/index.md](docs/index.md): installation, data preparation, the notebook
step by step, how it works, every feature explained ([feature glossary](docs/features.md)),
quality control, outputs, limitations and troubleshooting.

## Install

The installer appears on the [Releases page](https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D/releases)
once a release is published ([download instructions](.tools/docs/download_executable.md)).
**Only the Linux x86-64 installer is built and tested** (`distribution.platforms` in
`labconstrictor-app.yaml`). The code is pure Python and should run on Windows and macOS, but those
installers are untested; add the platforms there to build them.

The installer downloads the Python packages during installation. After that, the app works offline.

## What it does

1. **Load images:** single-channel TIFF / OME-TIFF videos, one field of view per file, in a
   MorphoBricks experiment folder. You confirm the axes and the calibration. Nothing is guessed,
   and missing calibration stays missing.
2. **Optical flow:** runs upstream `calc_flow3D`, or `calc_flow2D` slice per slice for anisotropic
   stacks, one time window at a time, and saves `vx`, `vy`, `vz` and `rel` in the upstream file
   layout with a manifest of SHA-256 hashes. The app estimates memory, disk and time before running,
   processes one example first, and shows progress bars with the time left.
3. **Motion features:** computed per optical-flow time point inside the foreground (a fixed
   intensity threshold, or the whole image) and the reliability filter. The families are magnitude,
   velocity components, collective motion, spatial heterogeneity and QC. Every time point is kept in
   `features_per_frame.csv`, and `features_per_fov.csv` holds the time average per field of view
   (circular mean for direction).
4. **Compare conditions:** you choose the control and the readout and confirm that repeat labels
   pair across conditions. [MorphoCoverage](https://github.com/CellMigrationLab/MorphoCoverage)
   then compares every condition with the control, with the field of view as the observation. It
   reports Cohen's d, the exploratory FOV-level randomization screen and the paired test on repeat
   means, along with the PCA/UMAP and per-feature figures. Its full HTML report opens from a link
   in a new tab. `qc_*` columns are never given to it as features.

## Check an installation with synthetic data

The notebook's optional **synthetic demo** step, or `python tools/demo_synthetic.py <new folder>`,
writes a synthetic experiment with a known answer:
- `ctrl` nuclei move slowly in random directions;
- `drug` nuclei move twice as fast, all in the same direction.

It runs every step and checks the results against the ground truth. The checks cover the speed
ratio, coherence, direction, axial drift and noise floor, the MorphoCoverage verdict on coherence,
recording of a failing file, and verified reuse of the optical flow.

It keeps every intermediate file:
- the experiment folder of synthetic images;
- optical-flow TIFFs and their manifests;
- feature tables;
- QC figures (`<run>/qc/`);
- the MorphoCoverage report (`<run>/analysis/demo/report.html`).

`demo_report.md` lists each expectation as PASS or FAIL. Section 3 saves the same input, foreground
and flow figures for your own data.

## Interpretation safeguards

- Optical flow measures the motion of **intensity patterns**. It is not nuclear tracking, and it
  gives no single-cell trajectories.
- On synthetic nuclei, the 3D algorithm **underestimates XY speed (×0.5–0.85) and overestimates Z
  speed (up to ×1.7)**. The bias depends on nuclear size ([docs/validation.md](docs/validation.md)),
  so speeds are relative. Check the QC confounders: nuclear object size and Z extent, intensity,
  occupancy and reliability.
- Z-dependent features are **experimental** and are given to MorphoCoverage only when you choose
  them (an axial readout is always included).
- Fields of view from one biological repeat are not independent. A separation in the PCA or UMAP is
  not evidence that a treatment changes migration. MorphoCoverage's FOV-level randomization screen
  is exploratory; only its paired test on repeat means (3 or more biological repeats) says whether
  an effect repeats.

## Resources

For an 1840 × 1840 × 11 × 15 field of view: about **11–12 GB of RAM**, about **15 min** of
processing (measured on a 4-vCPU machine), and 9.4 GB of float64 output per field of view
(4.7 GB if you choose float32). The app has no tiling, GPU or multiprocessing, and never downsamples.

## Run folder

```
<run>/run_started.json    the run's claim: a folder holds one run, never entered again
<run>/run_manifest.json   inputs, calibration, settings, versions, profiler source hash,
                          per-FOV status
<run>/experiments.csv     validated metadata with fov_uid
<run>/fovs.csv            status of every field of view (failures included)
<run>/flow/<fov_uid>/     <fov_uid>_{vx,vy,vz,rel}_tNNNN.tiff + flow_manifest.json
<run>/features/           features_per_frame.csv (every time point t), features_per_fov.csv
                          (time averages), feature_dictionary.json
<run>/analysis/<name>/    MorphoCoverage report.html with its figures and data, design.json,
                          morphocoverage_objects.csv, morphocoverage_fovs.csv
<run>/logs/run.log
```

Input: a MorphoBricks experiment folder, `<root>/<condition>/<biological repeat>/<technical
repeat>/<image>.tif`. Every level is optional, and a missing level is recorded as `single`.
Videos have a single channel. Feature columns are named `<foreground name or whole>__<feature>`.
See [docs/morphobricks.md](docs/morphobricks.md).

## Development

- The package is in `src/opticalflow3d_profiler/`, tests in `tests/profiler/`, and the notebook in
  `notebooks/OpticalFlow3D_Profiler/`. See [AGENTS.md](AGENTS.md).
- `python tools/check_profiler.py` runs Ruff, the code-size rules and pytest.
  `python tools/benchmark_flow.py` measures time and memory.
- LabConstrictor guides: [.tools/docs](.tools/docs/README.md).

## Licence and citation

The vendored OpticalFlow3D code keeps its BSD-3-Clause licence
(`src/opticalflow3d_profiler/_upstream/LICENSE`). If you use this app, please cite the OpticalFlow3D
paper:

> Lee, R. M., Eisenman, L. R., Hobson, C. M., Aaron, J. S. and Chew, T.-L. (2026). OpticalFlow3D –
> a tool for measuring amorphous motion in three-dimensional fluorescence microscopy images.
> *J. Cell Sci.* 139(21), jcs264851. https://doi.org/10.1242/jcs.264851

and [LabConstrictor](https://doi.org/10.48550/arXiv.2603.10704). The condition statistics and the
report are MorphoCoverage's (CellMigrationLab, MIT licence).
