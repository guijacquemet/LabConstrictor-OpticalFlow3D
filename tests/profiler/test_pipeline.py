"""End-to-end: synthetic experiment -> optical flow -> features -> MorphoCoverage report."""

import json

import pandas as pd
import pytest
import tifffile
from opticalflow3d_profiler.analysis import load_runs
from opticalflow3d_profiler.config import (
    Calibration,
    FeatureSettings,
    FlowParameters,
    ForegroundSpec,
)
from opticalflow3d_profiler.experiment import read_experiment_folder
from opticalflow3d_profiler.pipeline import RunSettings, run_experiment
from opticalflow3d_profiler.results import create_run
from opticalflow3d_profiler.synthetic import SyntheticMovie, render
from opticalflow3d_profiler.validation import InputError

CAL = Calibration(0.65, 0.65, 2.0, 0.5, source="user")
SPEED = "Nuclei__speed_xy_median"


def settings(**changes):
    base = dict(
        axes="TZYX",
        channel=None,
        calibration=CAL,
        features=FeatureSettings(reliability_value=1e-3, region_size_px=24, min_region_voxels=20),
        foreground=ForegroundSpec(mode="threshold", threshold=300.0),
        object_set="Nuclei",
    )
    base.update(changes)
    return RunSettings(**base)


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp")
    rows = []
    for condition, speed in (("ctrl", 0.2), ("drug", 0.6)):
        for rep in ("r1", "r2", "r3"):
            seed = len(rows)
            movie = SyntheticMovie(
                shape=(9, 11, 48, 48),
                n_nuclei=6,
                velocity=(0.0, 0.1, speed),
                seed=seed,
                noise_sd=5.0,
            )
            path = root / "experiment" / condition / rep / "pos1.tif"  # MorphoBricks layout
            path.parent.mkdir(parents=True, exist_ok=True)
            tifffile.imwrite(path, render(movie), imagej=True, metadata={"axes": "TZYX"})
            rows.append(path)
    (root / "experiment" / "ctrl" / "r1" / "broken.tif").write_bytes(b"not a TIFF")
    metadata = read_experiment_folder(root / "experiment")
    run = create_run(root / "results", "run1")
    manifest = run_experiment(metadata, settings(), run)
    return root, metadata, run, manifest


def test_failures_are_recorded_not_skipped(experiment):
    _, _, run, manifest = experiment
    fovs = pd.read_csv(run / "fovs.csv")
    assert len(fovs) == 7
    failed = fovs[fovs["status"] == "failed"]
    assert list(failed["position_id"]) == ["broken"]
    assert set(fovs["technical_repeat"]) == {"single"}  # missing level, MorphoBricks
    assert sum(f["status"] == "complete" for f in manifest["fovs"]) == 6


def test_tables_and_provenance(experiment):
    _, metadata, run, manifest = experiment
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    assert len(per_fov) == 6 and per_fov["fov_uid"].is_unique
    assert sorted(frames["t"].unique()) == [3, 4, 5]
    assert (frames["time_min"] == frames["t"] * 0.5).all()
    for column in ("condition", "biological_repeat", "technical_repeat", "position_id"):
        assert column in frames.columns and column in per_fov.columns
    assert SPEED in frames.columns and SPEED in per_fov.columns
    first = frames[frames["fov_uid"] == per_fov["fov_uid"].iloc[0]]
    assert per_fov[SPEED].iloc[0] == pytest.approx(first[SPEED].mean())  # time average
    assert frames.groupby("fov_uid").size().eq(3).all()
    dictionary = json.loads((run / "features" / "feature_dictionary.json").read_text())
    assert dictionary["units"] == {"lateral": "µm/min", "axial": "µm/min", "time": "min"}
    names = {d["name"] for d in dictionary["fov_features"]}
    assert names <= set(per_fov.columns)
    assert dictionary["column_naming"]["object_set"] == "Nuclei"
    assert manifest["upstream"]["commit"].startswith("6b88604")
    assert manifest["settings"]["foreground"]["threshold"] == 300.0
    assert manifest["settings"]["calibration"]["pixel_size_z"] == 2.0
    assert "numpy" in manifest["environment"]
    assert (run / "logs" / "run.log").read_text().count("failed") >= 1


def test_faster_condition_has_higher_speed(experiment):
    _, _, run, _ = experiment
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    speed = per_fov.groupby("condition")[SPEED].mean()
    assert speed["drug"] > 2 * speed["ctrl"]


def test_run_folder_is_never_overwritten(experiment):
    root, *_ = experiment
    with pytest.raises(InputError, match="never overwritten"):
        create_run(root / "results", "run1")


def test_features_recomputed_from_verified_flow(experiment):
    root, metadata, run, _ = experiment
    new = create_run(root / "results", "run2")
    other = settings(features=FeatureSettings(reliability_mode="none", region_size_px=24))
    manifest = run_experiment(metadata, other, new, reuse_from=run)
    reused = [f for f in manifest["fovs"] if f["status"] == "complete"]
    assert len(reused) == 6 and all(f["flow_origin"].startswith("reused") for f in reused)
    assert not any((new / "flow").iterdir())  # nothing recomputed


def test_flow_with_other_parameters_is_not_reused(experiment):
    root, metadata, run, _ = experiment
    new = create_run(root / "results", "run3")
    manifest = run_experiment(
        metadata[metadata["position_id"] != "broken"].iloc[:1],
        settings(flow=FlowParameters(mode="xyz", w_sig=2)),
        new,
        reuse_from=run,
    )
    assert manifest["fovs"][0]["status"] == "failed"
    assert "cannot be reused" in manifest["fovs"][0]["message"]


def test_morphocoverage_report_from_the_per_fov_table(experiment):
    from opticalflow3d_profiler.coverage import Design, coverage_input, run_report

    _, _, run, _ = experiment
    features = load_runs([run])
    with pytest.raises(InputError, match="Confirm that each biological-repeat label"):
        coverage_input(features, Design("ctrl", SPEED, repeats_paired=False))
    data = coverage_input(features, Design("ctrl", SPEED, repeats_paired=True))
    assert len(data.objects) == 6 and not any(c.startswith("qc_") for c in data.features)
    assert (data.fovs["repeat_group"] == data.fovs["biological_repeat"]).all()
    assert data.fovs["biological_repeat"].str.startswith("run1/").all()  # run-scoped repeats
    out = run / "analysis" / "report-1"
    path, result, _ = run_report(features, Design("ctrl", SPEED, repeats_paired=True), out)
    assert path == out / "report.html" and path.stat().st_size > 100_000
    row = result.discovery.tests.set_index("feature").loc[SPEED]
    assert row["observations"] == 3 and row["repeats"] == 3 and row["d"] > 0
    assert (out / "morphocoverage_objects.csv").is_file()
    with pytest.raises(InputError, match="never overwritten"):
        run_report(features, Design("ctrl", SPEED, repeats_paired=True), out)


def test_features_from_a_real_upstream_process_flow_folder(tmp_path):
    from opticalflow3d_profiler._upstream.calc_flow import process_flow
    from opticalflow3d_profiler.external import external_features

    movie = SyntheticMovie(shape=(8, 11, 40, 40), n_nuclei=4, velocity=(0, 0, 0.5))
    tifffile.imwrite(tmp_path / "exp.tif", render(movie), imagej=True, metadata={"axes": "TZYX"})
    process_flow(str(tmp_path), "exp", "OneTif", 3)
    folder = tmp_path / "OpticalFlow3D" / "exp"
    row = {
        "position_id": "p",
        "condition": "c",
        "biological_repeat": "r",
        "technical_repeat": "t",
        "image_path": "exp.tif",
    }
    run = create_run(tmp_path, "ext")
    manifest = external_features(folder, "exp", row, settings(foreground=ForegroundSpec()), run)
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    assert sorted(frames["t"]) == [3, 4]
    assert "whole__speed_xy_median" in frames.columns  # no foreground: whole image
    assert manifest["fovs"][0]["flow_origin"].startswith("external, not verified")
    assert "qc_foreground_intensity_mean" not in frames.columns  # intensity QC is opt-in
    with pytest.raises(InputError, match="needs the original image"):
        external_features(folder, "exp", row, settings(), create_run(tmp_path, "ext2"))


def _copy_run(run, target, prefix, change=None):
    import shutil

    shutil.copytree(run, target)
    table = target / "features" / "features_per_fov.csv"
    data = pd.read_csv(table, dtype=str, keep_default_na=False)
    data["fov_uid"] = prefix + data["fov_uid"]
    data.to_csv(table, index=False)
    if change:
        manifest = json.loads((target / "run_manifest.json").read_text())
        manifest["settings"]["features"].update(change)
        (target / "run_manifest.json").write_text(json.dumps(manifest))
    return target


def test_runs_with_different_settings_are_not_combined(experiment, tmp_path):
    _, _, run, _ = experiment
    a = _copy_run(run, tmp_path / "a", "a-")
    b = _copy_run(run, tmp_path / "b", "b-", {"reliability_value": 0.1})
    with pytest.raises(InputError, match="features.reliability_value"):
        load_runs([a, b])


def test_repeat_labels_are_scoped_to_their_run_unless_shared(experiment, tmp_path):
    _, _, run, _ = experiment
    a = _copy_run(run, tmp_path / "a", "a-")
    b = _copy_run(run, tmp_path / "b", "b-")
    scoped = load_runs([a, b])
    assert scoped.table.groupby("condition")["repeat_id"].nunique().eq(6).all()
    assert scoped.table["repeat_id"].str.contains("/").all()
    shared = load_runs([a, b], shared_repeat_labels=True)
    assert shared.table.groupby("condition")["repeat_id"].nunique().eq(3).all()


def test_auto_mode_picks_per_slice_for_anisotropic_stacks(experiment):
    _, _, run, manifest = experiment
    assert manifest["settings"]["flow"]["mode"] == "xy_per_slice"  # Z 2.0 / XY 0.65 > 3
    fovs = pd.read_csv(run / "fovs.csv", keep_default_na=False)
    complete = fovs[fovs["status"] == "complete"]
    assert not complete["warnings"].str.contains("spatial derivative kernel").any()
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    assert frames["Nuclei__vz_mean"].isna().all()
    assert frames["undefined_features"].str.contains("no axial component").all()
    flow = next((run / "flow").iterdir())
    assert not list(flow.glob("*_vz_t*.tiff"))


def test_shallow_z_warning_is_recorded_per_fov_in_3d_mode(experiment, tmp_path):
    _, metadata, _, _ = experiment
    run = create_run(tmp_path, "xyz")
    manifest = run_experiment(
        metadata[metadata["position_id"] != "broken"].iloc[:1],
        settings(flow=FlowParameters(mode="xyz")),
        run,
    )
    assert "shorter than the spatial derivative kernel" in manifest["fovs"][0]["warnings"]


def test_3d_speed_is_refused_with_per_slice_flow(experiment, tmp_path):
    _, metadata, _, _ = experiment
    bad = settings(
        flow=FlowParameters(mode="xy_per_slice"),
        features=FeatureSettings(speed_mode="xyz", reliability_value=1e-3),
    )
    with pytest.raises(InputError, match="3D speed needs 3D optical flow"):
        run_experiment(
            metadata[metadata["position_id"] != "broken"].iloc[:1], bad, create_run(tmp_path, "bad")
        )


def test_feature_settings_are_checked_before_any_computation(experiment, tmp_path):
    _, metadata, _, _ = experiment
    run = create_run(tmp_path, "early")
    bad = settings(features=FeatureSettings(reliability_value=None))
    with pytest.raises(InputError, match="needs a value"):
        run_experiment(metadata, bad, run)
    assert not any((run / "flow").iterdir())
