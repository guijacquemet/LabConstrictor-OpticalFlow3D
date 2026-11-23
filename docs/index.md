# OpticalFlow3D Profiler documentation

The OpticalFlow3D Profiler measures how nuclei move in 3D fluorescence time-lapses. It runs the
original [OpticalFlow3D](https://github.com/aicjanelia/OpticalFlow3D) algorithm on every field of
view, turns the velocity fields into motion features, and compares your experimental conditions
with [MorphoCoverage](https://github.com/CellMigrationLab/MorphoCoverage).

> **Status: experimental.** Speeds are optical-flow speeds of intensity patterns, with a
> size-dependent gain bias. They are not tracked nuclear displacements. Read
> [Limitations](limitations.md) before you interpret a result.

## Choose your path

### I am a biologist running the app

1. **Install it:** [Installation](installation.md) (desktop app, Google Colab or Python).
2. **Organise your images:** [Preparing your data](data_preparation.md).
3. **Run the notebook, section by section:** [Workflow](workflow.md).
4. **Check the quality before you compare:** [Quality control](qc.md).
5. **Something went wrong?** [Troubleshooting](troubleshooting.md).

New installation? Run the optional **synthetic demo** at the end of the notebook first. It checks
every step against a known answer ([Workflow → synthetic demo](workflow.md#optional-synthetic-demo)).

### I am an analyst reading the results

1. **What was measured, in brief:** [Overview](overview.md).
2. **What each feature means:** [Feature glossary](features.md) (every column, generated from the
   code).
3. **How to interpret it, and the traps:** [Interpreting results](concepts.md).
4. **Where everything is saved, and how to trace a number back:** [Outputs and run folder](outputs.md).
5. **Is the comparison fair?** [Quality control](qc.md).

### I am a developer or I want the calculations

1. [Overview](overview.md), then [How it works](theory.md) (the algorithm and every formula).
2. [MorphoBricks conventions](morphobricks.md) (folder layout, column names, pinned sources).
3. [Validation of the optical-flow engine](validation.md) (synthetic accuracy, gain bias,
   brightness artefact, resources).
4. The repository's `AGENTS.md` (coding and scientific rules) and `README.md`.

## Reading order

If you want the full picture, read in this order:

1. **[overview.md](overview.md)**: purpose, how it works in one list, the data you need, and what
   the app does not do.
2. **[theory.md](theory.md)**: the OpticalFlow3D calculation, the 3D and per-slice modes, units,
   masks, every feature family with its formula, time averaging, brightness correction and where
   the statistics come from.
3. **[concepts.md](concepts.md)**: practical interpretation: readouts versus orientation and QC
   columns, comparability, pitfalls.
4. **[workflow.md](workflow.md)**: the notebook step by step, every setting with its default.
5. **[features.md](features.md)**: look up columns here as you go; no need to read it front to
   back.

## Full documentation map

**Getting started**
- [Overview](overview.md)
- [Installation](installation.md)
- [Preparing your data](data_preparation.md)
- [Workflow (the notebook)](workflow.md)

**Understanding the results**
- [How it works (theory)](theory.md)
- [Interpreting results (concepts)](concepts.md)
- [Feature glossary](features.md)
- [Quality control](qc.md)
- [Outputs and run folder](outputs.md)

**Reference**
- [Limitations](limitations.md)
- [Troubleshooting](troubleshooting.md)
- [MorphoBricks conventions](morphobricks.md)
- [Validation of the optical-flow engine](validation.md)

**History** (dated records of reviews; not a description of the current behaviour)
- [Deployment validation](deployment_validation.md)
- [Audit response](audit_response.md), [second audit response](audit_response_2.md),
  [third audit response](audit_response_3.md)

## Citation

If you use this app, please cite the OpticalFlow3D paper:

> Lee, R. M., Eisenman, L. R., Hobson, C. M., Aaron, J. S. and Chew, T.-L. (2026). OpticalFlow3D –
> a tool for measuring amorphous motion in three-dimensional fluorescence microscopy images.
> *J. Cell Sci.* 139(21), jcs264851. https://doi.org/10.1242/jcs.264851

and [LabConstrictor](https://doi.org/10.48550/arXiv.2603.10704). The condition statistics and
the report are MorphoCoverage's (CellMigrationLab, MIT licence).
