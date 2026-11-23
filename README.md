# OpticalFlow3D Profiler

**Status: experimental.** A LabConstrictor desktop app that quantifies nuclear motion in 3D
fluorescence time-lapses. It runs the original [OpticalFlow3D](https://github.com/aicjanelia/OpticalFlow3D)
algorithm (HHMI Janelia, BSD-3-Clause, unchanged copy pinned at commit `6b88604`), turns the
velocity fields into motion profiles per field of view, and compares experimental conditions.

## Install

The installer appears on the [Releases page](https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D/releases)
once a release is published ([download instructions](.tools/docs/download_executable.md)).
**Only the Linux x86-64 installer is built and tested** (`distribution.platforms` in
`labconstrictor-app.yaml`). The code is pure Python and should run on Windows and macOS, but those
installers are untested; add the platforms there to build them.

The installer downloads the Python packages during installation. After that, the app works offline.

## What it does

1. **Load images:** TIFF / OME-TIFF, one field of view per file. You confirm the axes, the nuclear
   channel and the calibration. Nothing is guessed, and missing calibration stays missing.
2. **Optical flow:** runs upstream `calc_flow3D` one time window at a time and saves `vx`, `vy`, `vz`
   and `rel` in the upstream file layout, with a manifest of SHA-256 hashes. The app estimates memory,
   disk and time before running.
3. **Motion features:** computed per optical-flow time point inside the foreground (mask or a fixed
   intensity threshold) and the reliability filter. The families are magnitude, velocity components,
   collective motion, spatial heterogeneity and QC. The time points are then aggregated per field of
   view (temporal mean, SD and slope; circular statistics for direction).
4. **Compare experiments:** PCA of selected feature families (QC never included), and comparison
   of conditions at the biological-repeat level with effect sizes. Potential confounders are
   compared alongside the readouts.
5. **Export:** feature tables, feature dictionary, PCA, comparison, figures and full provenance.

Previously calculated upstream `process_flow` results can also be analysed. They are marked as
unverified.

## Check an installation with synthetic data

The notebook's optional **synthetic demo** step, or `python tools/demo_synthetic.py <new folder>`,
writes a synthetic experiment with a known answer:
- `ctrl` nuclei move slowly in random directions;
- `drug` nuclei move twice as fast, all in the same direction.

It runs every step and checks the results against the ground truth. The checks cover the speed
ratio, coherence, direction, axial drift and noise floor, PCA separation, recording of a failing
file, and verified reuse of the optical flow.

It keeps every intermediate file:
- images and ground-truth masks;
- optical-flow TIFFs and their manifests;
- feature tables;
- QC figures (`<run>/qc/`);
- the PCA and comparison exports.

`demo_report.md` lists each expectation as PASS or FAIL. In step 3, **Save QC figures** writes
the same input, foreground and flow figures for your own data.

## Interpretation safeguards

- Optical flow measures the motion of **intensity patterns**. It is not nuclear tracking, and it
  gives no single-cell trajectories.
- On synthetic nuclei, the 3D algorithm **underestimates XY speed (×0.5–0.85) and overestimates Z
  speed (up to ×1.7)**. The bias depends on nuclear size ([docs/validation.md](docs/validation.md)),
  so speeds are relative. Check the QC confounders: nuclear object size and Z extent, intensity,
  occupancy and reliability.
- Z-dependent features are **experimental** and are excluded from the PCA unless you choose them.
- Fields of view from one biological repeat are not independent. A PCA separation is not evidence
  that a treatment changes migration. The FOV-level randomization test is exploratory; only the
  paired test on repeat means (3 or more biological repeats) says whether an effect repeats.

## Resources

For an 1840 × 1840 × 11 × 15 field of view: about **11–12 GB of RAM**, about **15 min** of
processing (measured on a 4-vCPU machine), and 9.4 GB of float64 output per field of view
(4.7 GB if you choose float32). The app has no tiling, GPU or multiprocessing, and never downsamples.

## Run folder

```
<run>/run_manifest.json   inputs, calibration, settings, versions, per-FOV status
<run>/experiments.csv     validated metadata with fov_uid
<run>/fovs.csv            status of every field of view (failures included)
<run>/flow/<fov_uid>/     <fov_uid>_{vx,vy,vz,rel}_tNNNN.tiff + flow_manifest.json
<run>/features/           features_per_frame.csv (every time point t), features_per_fov.csv
                          (time averages), feature_dictionary.json
<run>/analysis/<name>/    pca_*.csv, condition_tests.csv, condition_tests_per_repeat.csv,
                          analysis_settings.json, figures/
<run>/logs/run.log
```

Input: a MorphoBricks experiment folder, `<root>/<condition>/<biological repeat>/<technical
repeat>/<image>.tif`. Every level is optional, and a missing level is recorded as `single`.
Masks go in a separate masks folder. A metadata CSV with `condition, biological_repeat,
technical_repeat, position_id, image_path` (optional `mask_path`) also works. Feature columns
are named `<channel>__<foreground or whole>__<feature>`. The comparison follows the MorphoCoverage
rules, with the field of view as the observation. See [docs/morphobricks.md](docs/morphobricks.md).

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

and [LabConstrictor](https://doi.org/10.48550/arXiv.2603.10704).
