# Installation

[:arrow_left: Documentation index](index.md)

There are three ways to run the OpticalFlow3D Profiler. They all run the same notebook,
`OpticalFlow3D_Profiler.ipynb`, with the same package and the same pinned dependencies.

| Option | Best for | Platforms |
|---|---|---|
| [Desktop app (installer)](#option-1-desktop-app-labconstrictor-installer) | Everyday use on your own computer, offline after installation | **Linux x86-64 only** is built and tested |
| [Google Colab](#option-2-google-colab) | Trying the app without installing anything | Any browser |
| [Python from the repository](#option-3-python-from-the-repository) | Developers, servers, other operating systems | Python 3.11 |

## Requirements

- **Memory:** the optical flow is memory hungry. Plan about **11–12 GB of RAM** for an
  1840 × 1840 × 11 Z-stack (measured on a 4-vCPU machine). The notebook estimates memory, disk and
  time for your own images before you process them ([Workflow](workflow.md#estimate-resources)).
- **Disk:** about 9.4 GB of float64 optical-flow output per 1840 × 1840 × 11 × 15 field of view
  (4.7 GB if you choose float32).
- **No GPU** is used, and none is needed.

## Option 1: desktop app (LabConstrictor installer)

The app is packaged with [LabConstrictor](https://doi.org/10.48550/arXiv.2603.10704) as a
desktop installer that sets up Python, JupyterLab and every dependency.

1. Download the installer from the
   [Releases page](https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D/releases) of the
   repository, once a release is published. Step-by-step instructions are in
   [Install the app locally](../.tools/docs/download_executable.md).
2. **Linux x86-64:** run the downloaded `.sh` file in a terminal:
   ```bash
   bash "OpticalFlow3D Profiler-<version>-Linux-x86_64.sh"
   ```
   and follow the prompts. The installer downloads the Python packages during installation.
   After that, the app works offline.
3. Start **OpticalFlow3D Profiler** from your applications menu. A terminal window opens and keeps
   JupyterLab running: leave it open. JupyterLab opens in your browser with the **Welcome
   notebook**.
4. Run the Welcome notebook's cell and click **Open the notebook** next to
   `OpticalFlow3D_Profiler`. More detail: [Open and use an app](../.tools/docs/notebook_usage.md).

> **Platforms.** Only the Linux x86-64 installer is built and tested (`distribution.platforms:
> [linux-x86_64]` in `labconstrictor-app.yaml`). The code is pure Python and should run on
> Windows and macOS, but those installers are not built. On those systems, use
> [Google Colab](#option-2-google-colab) or [Python](#option-3-python-from-the-repository).

In the installed app, the notebook's first cell (**check this notebook's version**) shows a link
to the Welcome notebook, which tells you whether a newer notebook version exists.

## Option 2: Google Colab

1. Open `notebooks/OpticalFlow3D_Profiler/OpticalFlow3D_Profiler.ipynb` from the repository in
   [Google Colab](https://colab.research.google.com/) (File → Open notebook → GitHub).
2. *(Optional)* The first cell checks the notebook's version: give the repository URL
   (`https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D`) and click **Test Connection**.
3. Run **Section 0 → Install**. On Colab it installs the app from GitHub together with the
   pinned versions of MorphoCoverage, morphobricks-normalization and tqdm (a minute or two):
   ```
   pip install "git+https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D" \
     "morphocoverage @ git+https://github.com/CellMigrationLab/MorphoCoverage@209b9be40a14aef5a5e244a8d031a4828f1e96ef" \
     "tqdm==4.70.1" \
     "morphobricks-normalization @ git+https://github.com/CellMigrationLab/morphobricks-normalization@f2aa7321b24ab49ffe9059154c54eb659741162a"
   ```
   It ends by printing `Ready.`
4. *(Optional)* Run **Mount Google Drive (Colab only)** to reach your images. Your Drive then
   appears under `/content/gdrive/MyDrive`; use paths below it for the experiment and results
   folders.

Colab notes:
- Choose a results folder **on your Drive**. Files written elsewhere in the Colab machine are lost
  when the session ends.
- Free Colab machines have limited memory. Check the resource estimate in section 2 before you
  process large stacks.
- The MorphoCoverage report opens through Colab's own proxy in a new window
  ([Workflow, section 4c](workflow.md#4c-html-report)).

## Option 3: Python from the repository

The package needs **Python 3.11** (`python_requires=">=3.11"`; the app is built and tested with
Python 3.11.13). The exact dependency list is `requirements.txt`, generated from
`notebooks/OpticalFlow3D_Profiler/requirements.yaml`; `requirements.lock.txt` pins every package
the installer installs.

```bash
git clone https://github.com/guijacquemet/LabConstrictor-OpticalFlow3D
cd LabConstrictor-OpticalFlow3D
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt   # pinned dependencies, incl. MorphoCoverage from GitHub
python -m pip install .                     # the opticalflow3d_profiler package (src/)
python -m pip install jupyterlab
jupyter lab notebooks/OpticalFlow3D_Profiler/OpticalFlow3D_Profiler.ipynb
```

`requirements.txt` is needed because MorphoCoverage and morphobricks-normalization are installed
from pinned Git commits, which the package metadata alone does not install.

Then run the notebook from Section 0. Outside Colab, the **Install** cell only prints
`Local Jupyter: the packages come with the installed app.` and loads the widgets.

### Check the installation

- In the notebook: run the optional [synthetic demo](workflow.md#optional-synthetic-demo).
- From a terminal, in the repository folder:
  ```bash
  python tools/demo_synthetic.py /path/to/new/empty/folder --small
  ```
  It writes a synthetic experiment, runs every step and writes `demo_report.md` with PASS or FAIL
  for each expectation. It exits with code 1 if an expectation fails.
- Developers: `python tools/check_profiler.py` runs Ruff, the code-size rules and the test suite.

## Pinned versions

| Component | Pinned version |
|---|---|
| OpticalFlow3D (vendored, unchanged) | commit `6b88604` of aicjanelia/OpticalFlow3D; the app refuses to run if the file's SHA-256 differs |
| MorphoCoverage | commit `209b9be40a14aef5a5e244a8d031a4828f1e96ef` |
| morphobricks-normalization | commit `f2aa7321b24ab49ffe9059154c54eb659741162a` |
| Python | 3.11.13 |

Every run records the versions it actually used (Python, platform, each dependency with its Git
commit when installed from Git) in `run_manifest.json` ([Outputs](outputs.md#run_manifestjson)).
