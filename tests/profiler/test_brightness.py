import json

import numpy as np
import pandas as pd
import pytest
import tifffile
from opticalflow3d_profiler._upstream.calc_flow import calc_flow3D
from opticalflow3d_profiler.brightness import brightness_change, equalise_window, window_means
from opticalflow3d_profiler.config import (
    Calibration,
    FeatureSettings,
    FlowParameters,
    ForegroundSpec,
    ImageSpec,
)
from opticalflow3d_profiler.experiment import validate_metadata
from opticalflow3d_profiler.flow_backend import flow_identity, flow_window, run_flow
from opticalflow3d_profiler.image_io import file_identity, inspect_tiff
from opticalflow3d_profiler.pipeline import RunSettings, run_experiment
from opticalflow3d_profiler.results import create_run
from opticalflow3d_profiler.synthetic import SyntheticMovie, nuclear_interior, render


def test_brightness_change_of_a_known_ramp():
    means = 100.0 * (1 + 0.05 * (np.arange(7) - 3))
    assert brightness_change(means) == pytest.approx(0.05)
    assert brightness_change(np.full(7, 50.0)) == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(brightness_change(np.zeros(7)))


def test_equalisation_matches_the_central_frame_and_keeps_the_input():
    window = np.stack([np.full((2, 3, 3), v, np.uint16) for v in (50, 100, 200)])
    scaled, factors = equalise_window(window, window_means(window))
    assert factors == pytest.approx([2.0, 1.0, 0.5])
    assert np.allclose(window_means(scaled), 100.0)
    assert window[0, 0, 0, 0] == 50  # input untouched
    with pytest.raises(ValueError, match="non-positive"):
        equalise_window(window, np.array([0.0, 1.0, 1.0]))


def test_brightness_ramp_is_read_as_motion_unless_equalised():
    movie = SyntheticMovie(shape=(7, 11, 80, 80), n_nuclei=12, brightness_ramp=0.08)
    data = render(movie, dtype="float64")
    interior = nuclear_interior(movie, data[3])
    raw, record = flow_window(data, FlowParameters())
    fixed, fixed_record = flow_window(data, FlowParameters(brightness_equalisation="global_mean"))
    assert record["brightness_change_per_frame"] == pytest.approx(0.08, rel=0.1)
    assert record["equalisation_factors"] is None
    raw_speed = np.median(np.sqrt(raw["vx"] ** 2 + raw["vy"] ** 2 + raw["vz"] ** 2)[interior])
    fixed_speed = np.median(
        np.sqrt(fixed["vx"] ** 2 + fixed["vy"] ** 2 + fixed["vz"] ** 2)[interior]
    )
    assert raw_speed > 0.05  # static nuclei appear to move
    assert fixed_speed < 0.01 * raw_speed + 1e-9  # nearly all of it removed
    assert len(fixed_record["equalisation_factors"]) == 7


def test_equalised_run_is_upstream_on_the_scaled_window_and_changes_identity(tmp_path):
    movie = SyntheticMovie(shape=(7, 11, 48, 48), n_nuclei=5, brightness_ramp=0.05)
    data = render(movie)
    path = tmp_path / "ramp.tif"
    tifffile.imwrite(path, data, imagej=True, metadata={"axes": "TZYX"})
    spec, header = ImageSpec(path, "TZYX"), inspect_tiff(path)
    params = FlowParameters(brightness_equalisation="global_mean")
    manifest = run_flow(spec, header, params, tmp_path / "flow", "f")
    output = manifest["outputs"][0]
    scaled, _ = equalise_window(data, window_means(data))
    expected = calc_flow3D(scaled, 3, 1, 4)[0]
    saved = tifffile.imread(tmp_path / "flow" / output["files"]["vx"]["name"])
    np.testing.assert_array_equal(saved, expected)
    assert manifest["identity"]["parameters"]["brightness_equalisation"] == "global_mean"
    source = file_identity(path)
    assert flow_identity(spec, header, FlowParameters(), source) != manifest["identity"]


def test_brightness_qc_column_and_warning(tmp_path):
    movie = SyntheticMovie(shape=(7, 11, 48, 48), n_nuclei=5, brightness_ramp=0.05, noise_sd=2.0)
    path = tmp_path / "ramp.tif"
    tifffile.imwrite(path, render(movie), imagej=True, metadata={"axes": "TZYX"})
    metadata = validate_metadata(
        pd.DataFrame(
            [
                {
                    "sample_id": "s",
                    "position_id": "p",
                    "condition": "c",
                    "biological_repeat": "r",
                    "technical_repeat": "t",
                    "batch": "b",
                    "input_path": str(path),
                }
            ]
        )
    )
    settings = RunSettings(
        "TZYX",
        None,
        Calibration(),
        features=FeatureSettings(reliability_value=1e-3, region_size_px=16, min_region_voxels=10),
        foreground=ForegroundSpec("threshold", 300.0),
    )
    run = create_run(tmp_path, "run")
    manifest = run_experiment(metadata, settings, run)
    assert "brightness changes by up to" in manifest["fovs"][0]["warnings"]
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    assert frames["qc_brightness_change_per_frame"].iloc[0] == pytest.approx(0.05, rel=0.15)
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    assert "qc_brightness_change_per_frame__tmax" in per_fov.columns
    flow_manifest = json.loads(
        next((run / "flow").iterdir()).joinpath("flow_manifest.json").read_text()
    )
    assert "window_mean_intensity" in flow_manifest["outputs"][0]


def test_histogram_matching_maps_each_frame_onto_the_central_histogram():
    from opticalflow3d_profiler.brightness import match_histograms_window

    rng = np.random.default_rng(0)
    base = rng.gamma(2.0, 100.0, (3, 3, 20, 20))
    window = np.stack([base[0] * 0.5, base[1], base[2] ** 1.2]).astype(np.uint16)
    matched = match_histograms_window(window)
    np.testing.assert_array_equal(matched[1], window[1])  # reference frame unchanged
    q = [10, 50, 90]
    for t in (0, 2):
        assert np.percentile(matched[t], q) == pytest.approx(np.percentile(window[1], q), rel=0.05)
        order = np.argsort(window[t], axis=None)
        assert np.all(np.diff(matched[t].ravel()[order]) >= 0)  # monotonic mapping
    assert window[0].max() < 2000  # input untouched


def test_histogram_matching_also_removes_a_brightness_ramp():
    movie = SyntheticMovie(shape=(7, 11, 80, 80), n_nuclei=12, brightness_ramp=0.08)
    data = render(movie)
    interior = nuclear_interior(movie, data[3])
    raw, _ = flow_window(data, FlowParameters())
    matched, record = flow_window(data, FlowParameters(brightness_equalisation="histogram_match"))
    assert record["histogram_matched_to_frame"] == 3

    def speed(f):
        return np.median(np.sqrt(f["vx"] ** 2 + f["vy"] ** 2 + f["vz"] ** 2)[interior])

    assert speed(matched) < 0.1 * speed(raw)
