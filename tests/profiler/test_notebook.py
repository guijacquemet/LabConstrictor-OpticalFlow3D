"""Notebook smoke tests: the notebook runs in a kernel, and every step works end to end."""

import json
from pathlib import Path

import matplotlib
import pytest
import tifffile

matplotlib.use("Agg")

from opticalflow3d_profiler.notebook_analysis_ui import build  # noqa: E402
from opticalflow3d_profiler.synthetic import SyntheticMovie, render  # noqa: E402
from opticalflow3d_profiler.validation import InputError  # noqa: E402

NOTEBOOK = (
    Path(__file__).resolve().parents[2]
    / "notebooks"
    / "OpticalFlow3D_Profiler"
    / "OpticalFlow3D_Profiler.ipynb"
)


def test_notebook_structure():
    nb = json.loads(NOTEBOOK.read_text())
    first = "".join(nb["cells"][0]["source"])
    assert 'notebook_name = "OpticalFlow3D_Profiler"' in first
    sources = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    for step in ("load", "settings", "process", "results", "design", "report", "demo"):
        assert any(f'app["{step}"]' in s for s in sources)
    assert "drive.mount" in sources[2] and "pip install" in sources[1]
    # The notebook stays thin: no numerical code in the cells.
    assert not any("numpy" in s or "calc_flow" in s for s in sources[1:])


def test_notebook_executes_in_a_kernel():
    nbclient = pytest.importorskip("nbclient")
    nbformat = pytest.importorskip("nbformat")
    nb = nbformat.read(NOTEBOOK, as_version=4)
    src = str(Path(__file__).resolve().parents[2] / "src")
    nb.cells.insert(0, nbformat.v4.new_code_cell(f"import sys; sys.path.insert(0, {src!r})"))
    nbclient.NotebookClient(nb, timeout=120, kernel_name="python3").execute()
    errors = [o for c in nb.cells for o in c.get("outputs", []) if o["output_type"] == "error"]
    assert not errors


def write_movie(path, speed, seed):
    movie = SyntheticMovie(
        shape=(9, 11, 48, 48), n_nuclei=6, velocity=(0.0, 0.0, speed), seed=seed, noise_sd=5.0
    )
    tifffile.imwrite(
        path,
        render(movie),
        imagej=True,
        metadata={"axes": "TZYX", "spacing": 2.0, "unit": "um"},
        resolution=(1 / 0.65, 1 / 0.65),
    )


def refused_settings_keep_the_run_name(settings, process, run):
    """A refused setting raises before the run folder exists, so its name stays free."""
    settings.rel_value.value = ""
    with pytest.raises((InputError, ValueError)):
        process.process()
    assert not run.exists()
    settings.rel_value.value = "0.001"


def test_all_steps_drive_end_to_end(tmp_path):
    rows = []
    for i, (condition, rep, speed) in enumerate(
        [("ctrl", "r1", 0.2), ("ctrl", "r2", 0.25), ("drug", "r1", 0.6), ("drug", "r2", 0.7)]
    ):
        path = tmp_path / "experiment" / condition / rep / "p1.tif"  # MorphoBricks layout
        path.parent.mkdir(parents=True)
        write_movie(path, speed, i)
        rows.append(path)
    app = build()
    for step in ("load", "settings", "process", "results", "design", "report", "demo"):
        app[step].widget()

    load = app["load"]
    load.experiment.value = str(tmp_path / "experiment")
    load.results.value = str(tmp_path / "results")
    load.load()
    assert load.axes.value == "TZYX" and load.cal["x"].value == "0.65"
    assert load.cal["t"].value == ""  # no frame interval in the header: left empty
    load.cal["t"].value = "30"
    load.time_unit.value = "s"
    load.confirm()
    assert app["session"].spec.calibration.frame_interval == 0.5

    settings = app["settings"]
    settings.threshold.value = "300"
    settings.rel_value.value = "0.001"
    settings.region.value = 24
    settings.tsig.value = 1e308  # re-validation M8: OverflowError escaped the guarded display
    with pytest.raises(InputError, match="sigma_too_large|at most"):
        settings.estimate()
    settings.tsig.value = 1.0
    settings.estimate()
    settings.process_example()
    assert list((tmp_path / "results" / "examples").glob("*/features/features_per_fov.csv"))

    process = app["process"]
    process.run_name.value = "run1"
    process.qc.value = False
    refused_settings_keep_the_run_name(settings, process, tmp_path / "results" / "run1")
    process.process()
    run = app["session"].run_dir
    assert (run / "features" / "features_per_fov.csv").exists()

    app["results"].load()
    design = app["design"]
    design.refresh()
    design.control.value = "ctrl"
    design.paired.value = True
    design.confirm()
    report = app["report"]
    report.create()
    assert (run / "analysis" / "report-1" / "report.html").exists()
    with pytest.raises(Exception, match="never overwritten"):
        from opticalflow3d_profiler.coverage import run_report

        session = app["session"]
        run_report(
            session.analysis["features"], session.analysis["design"], run / "analysis" / "report-1"
        )
