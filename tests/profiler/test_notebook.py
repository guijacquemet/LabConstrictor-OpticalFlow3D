"""Notebook smoke tests: the notebook runs in a kernel, and every step works end to end."""

import json
from pathlib import Path

import matplotlib
import pytest
import tifffile

matplotlib.use("Agg")

from opticalflow3d_profiler.notebook_analysis_ui import build  # noqa: E402
from opticalflow3d_profiler.synthetic import SyntheticMovie, render  # noqa: E402

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
    for step in ("load", "flow", "features", "compare", "export"):
        assert any(f'app["{step}"]' in s for s in sources)
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
    for step in ("load", "flow", "features", "compare", "export"):
        app[step].widget()

    load = app["load"]
    load.path.value = str(rows[0])
    load.inspect()
    assert load.axes.value == "TZYX" and load.cal["x"].value == "0.65"
    assert load.cal["t"].value == ""  # no frame interval in the header: left empty
    load.cal["t"].value = "30"
    load.time_unit.value = "s"
    load.confirm()
    assert app["session"].spec.calibration.frame_interval == 0.5

    flow = app["flow"]
    flow.parent.value = str(tmp_path / "results")
    flow.experiment.value = str(tmp_path / "experiment")
    flow.estimate()
    flow.run()
    assert len(flow.fov.options) == 4
    flow.fov.value = flow.fov.options[0]
    flow.show()

    features = app["features"]
    features.channel_name.value = "H2B"
    features.fg_mode.value = "threshold"
    features.threshold.value = "300"
    features.rel_value.value = "0.001"
    features.region.value = 24
    features.extract()
    run = app["session"].run_dir
    assert (run / "features" / "features_per_fov.csv").exists()

    compare = app["compare"]
    compare.pca()
    compare.control.value = "ctrl"
    compare.compare()
    export = app["export"]
    export.export()
    out = run / "analysis" / "analysis-1"
    assert (out / "pca_scores.csv").exists() and (out / "condition_tests.csv").exists()
    assert (out / "figures" / "pca_pc1_pc2.png").exists()
    with pytest.raises(Exception, match="exists"):
        export.export()
