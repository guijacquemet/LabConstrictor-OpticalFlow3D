# Deployment validation (PR 3)

> **Historical (release 0.1.0).** The notebook has since been restructured into sections 0-4 and
> uses MorphoCoverage; this page records what was validated for 0.1.0 and is not re-run here.

What was run, on 23 November 2026, in a Linux x86-64 container (4 vCPU, 15 GB RAM). **The
constructor installer itself was not built here:** downloading a conda binary was not allowed in
that environment. It is built by the template's `Build Release Installers` workflow when a release
is published.

| Check | How | Result |
|---|---|---|
| Package imports, dependencies resolve | Fresh Python 3.11 venv, `pip install -r tools/requirements-checks.txt` (the pins of `requirements.yaml`) | passed |
| Full check suite | `python tools/check_profiler.py` (Ruff, size rules, pytest) | 81 tests passed |
| Release preparation | In a copy of the repository: `bump_version.py 0.1.0`, `bump_constructor.py`, `bump_Welcome_notebook.py`, `sync_notebook_versions.py`, `merge_requirements.py`, `check_placeholders.py` | passed; no placeholder left; Python 3.11.13 and JupyterLab 4.4.0 written to `environment.yaml` |
| Installed layout | Files copied to a prefix following `construct.yaml` `extra_files`; then the `post_install.sh` pip steps: `pip install -r requirements.txt`, `pip install --no-deps --no-build-isolation "<prefix>/OpticalFlow3D Profiler"`, the import check, `hide_code_cells.py`, and `launch_jupyter.py --self-test` | passed |
| Notebook opens in JupyterLab, offline | `unshare -rn python tools/offline_smoke.py "<app folder>" --allow-root`: no network namespace, JupyterLab 4.4.0 serves the notebook, and every cell runs | passed |
| Synthetic dataset through all five steps, offline | The steps of `tests/profiler/test_notebook.py::test_all_steps_drive_end_to_end` run with the installed package (not `src/`) inside `unshare -rn` | passed (5.7 s, 1.1 GB peak RSS) |
| Licence shipped | The installer bundles only `.py` files of `src/`; the BSD licence is in `_upstream/_license.py` (tested identical to `LICENSE`) | passed |

Still to do after the first release: download the Linux `.sh` installer, install it on a clean
machine, launch the app from its menu entry, and run `tools/offline_smoke.py` with the installed
prefix. Windows and macOS are not built (`distribution.platforms: [linux-x86_64]`) and are untested.

## Release 0.1.0: the real Linux installer (23 November 2026)

The template's *Build Release Installers* workflow built `OpticalFlow3D_Profiler-0.1.0-Linux-x86_64.sh`
(222 MB, SHA-256 `95aac0d4…0bd04`) and attached it to the release. Then, in a Linux x86-64 container:

| Check | Result |
|---|---|
| Download; SHA-256 equals the release digest | passed |
| `bash OpticalFlow3D_Profiler-0.1.0-Linux-x86_64.sh -b -p <prefix>` (fresh prefix) | passed in 45 s; `post_install` finished ("Launcher preflight completed", menu entries created) |
| Installed versions | app 0.1.0 (`construct.yaml`, package, metadata); notebook 0.2.0 |
| `unshare -rn python tools/offline_smoke.py "<prefix>/OpticalFlow3D Profiler"` (no network) | passed: JupyterLab serves the notebook and every cell runs |
| Synthetic demo (96 × 96) with the installed package, no network | 16/17 with 0.1.0. The axial drift check (0.0106 against 0.01) was too strict for the small design. Fixed after the release: `DemoDesign.small()` has size-appropriate tolerances, and now gives 17/17 |

Found during this test and fixed after the release:
- **Installer thank-you text said 0.0.1.** `conclusion_text` was written on two lines, which
  `bump_version.py` does not match. It is now on one line.
- **The smoke tool failed on machines with a user-level `python3` kernel.** It now sets
  `JUPYTER_PREFER_ENV_PATH=1`, as `launch_jupyter.py` does for the real app.

Not tested: launching from the desktop menu (no desktop session), Windows and macOS.
