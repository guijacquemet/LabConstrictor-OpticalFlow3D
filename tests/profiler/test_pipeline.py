"""End-to-end: synthetic experiment -> optical flow -> features -> PCA and comparisons."""

import json

import numpy as np
import pandas as pd
import pytest
import tifffile
from opticalflow3d_profiler.analysis import (
    compare_conditions,
    export_analysis,
    load_runs,
)
from opticalflow3d_profiler.config import (
    Calibration,
    FeatureSettings,
    FlowParameters,
    ForegroundSpec,
)
from opticalflow3d_profiler.experiment import read_metadata
from opticalflow3d_profiler.figures import condition_plot, pca_scatter, save
from opticalflow3d_profiler.pipeline import RunSettings, run_experiment
from opticalflow3d_profiler.profile_analysis import PcaSettings, prepare_matrix, run_pca
from opticalflow3d_profiler.results import create_run
from opticalflow3d_profiler.synthetic import SyntheticMovie, render
from opticalflow3d_profiler.validation import InputError

CAL = Calibration(0.65, 0.65, 2.0, 0.5, source="user")


def settings(**changes):
    base = dict(
        axes="TZYX",
        channel=None,
        calibration=CAL,
        features=FeatureSettings(reliability_value=1e-3, region_size_px=24, min_region_voxels=20),
        foreground=ForegroundSpec(mode="threshold", threshold=300.0),
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
            path = root / "images" / f"{condition}_{rep}.tif"
            path.parent.mkdir(exist_ok=True)
            tifffile.imwrite(path, render(movie), imagej=True, metadata={"axes": "TZYX"})
            rows.append(
                {
                    "sample_id": f"{condition}-{rep}",
                    "position_id": "pos1",
                    "condition": condition,
                    "biological_repeat": rep,
                    "technical_repeat": "t1",
                    "batch": "b1",
                    "input_path": f"images/{condition}_{rep}.tif",
                }
            )
    rows.append({**rows[0], "sample_id": "missing", "input_path": "images/missing.tif"})
    pd.DataFrame(rows).to_csv(root / "metadata.csv", index=False)
    metadata = read_metadata(root / "metadata.csv")
    run = create_run(root / "results", "run1")
    manifest = run_experiment(metadata, settings(), run)
    return root, metadata, run, manifest


def test_failures_are_recorded_not_skipped(experiment):
    _, _, run, manifest = experiment
    fovs = pd.read_csv(run / "fovs.csv")
    assert len(fovs) == 7
    failed = fovs[fovs["status"] == "failed"]
    assert list(failed["sample_id"]) == ["missing"]
    assert "does not exist" in failed["message"].iloc[0]
    assert sum(f["status"] == "complete" for f in manifest["fovs"]) == 6


def test_tables_and_provenance(experiment):
    _, metadata, run, manifest = experiment
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    assert len(per_fov) == 6 and per_fov["fov_uid"].is_unique
    assert sorted(frames["source_frame"].unique()) == [3, 4, 5]
    assert (frames["time_min"] == frames["source_frame"] * 0.5).all()
    assert frames.groupby("fov_uid").size().eq(3).all()
    dictionary = json.loads((run / "features" / "feature_dictionary.json").read_text())
    assert dictionary["units"] == {"lateral": "µm/min", "axial": "µm/min", "time": "min"}
    names = {d["name"] for d in dictionary["fov_features"]}
    assert names <= set(per_fov.columns)
    assert manifest["upstream"]["commit"].startswith("6b88604")
    assert manifest["settings"]["foreground"]["threshold"] == 300.0
    assert manifest["settings"]["calibration"]["pixel_size_z"] == 2.0
    assert "numpy" in manifest["environment"]
    assert (run / "logs" / "run.log").read_text().count("failed") >= 1


def test_faster_condition_has_higher_speed(experiment):
    _, _, run, _ = experiment
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    speed = per_fov.groupby("condition")["speed_xy_median__tmean"].mean()
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
        metadata.iloc[:1], settings(flow=FlowParameters(w_sig=2)), new, reuse_from=run
    )
    assert manifest["fovs"][0]["status"] == "failed"
    assert "cannot be reused" in manifest["fovs"][0]["message"]


def test_pca_and_comparison_export(experiment):
    root, _, run, _ = experiment
    features = load_runs([run])
    pca_settings = PcaSettings()
    prepared = prepare_matrix(
        features.table,
        [
            "run",
            "fov_uid",
            "sample_id",
            "position_id",
            "condition",
            "biological_repeat",
            "technical_repeat",
            "batch",
            "input_path",
            "undefined_features",
        ],
        features.fov_defs,
        pca_settings,
    )
    assert not any(c.startswith("qc_") for c in prepared.matrix.columns)
    result = run_pca(prepared, 3)
    comparison = compare_conditions(features, "ctrl", "drug")
    out = run / "analysis"
    export_analysis(out, features, pca_settings, result, comparison)
    scores = pd.read_csv(out / "pca_scores.csv")
    assert set(scores["condition"]) == {"ctrl", "drug"} and "PC1" in scores
    settings_json = json.loads((out / "analysis_settings.json").read_text())
    assert any("not a significance test" in w for w in settings_json["warnings"])
    median = comparison[comparison["readout"] == "median motion magnitude"].iloc[0]
    assert median["n_repeats_control"] == 3 and median["test"].startswith("Welch")
    assert median["difference"] > 0
    assert (comparison["role"] == "potential confounder").any()
    save(pca_scatter(result.scores, result.explained_variance_ratio), out / "figures/pca.png")
    save(
        condition_plot(features.table, "speed_xy_median__tmean", "median"),
        out / "figures/median.png",
    )
    assert (out / "figures" / "pca.png").stat().st_size > 1000


def test_mask_foreground_must_match_image(experiment, tmp_path):
    root, metadata, _, _ = experiment
    mask = tmp_path / "mask.tif"
    tifffile.imwrite(mask, np.ones((11, 48, 40), np.uint8))
    run = create_run(tmp_path, "m")
    fg = ForegroundSpec(mode="mask", mask_path=mask, mask_axes="ZYX")
    manifest = run_experiment(metadata.iloc[:1], settings(foreground=fg), run)
    assert "source image coordinates" in manifest["fovs"][0]["message"]
