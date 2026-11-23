import numpy as np
import pandas as pd
import pytest
from opticalflow3d_profiler.experiment import fov_uid, read_metadata, validate_metadata
from opticalflow3d_profiler.feature_dictionary import BIOLOGICAL, QC, frame_dictionary
from opticalflow3d_profiler.temporal_features import aggregate_fov, fov_dictionary
from opticalflow3d_profiler.validation import InputError


def test_aggregates_of_a_known_series():
    defs = frame_dictionary("xy")
    frames = [
        {"speed_xy_median": v, "xy_dominant_direction_deg": d}
        for v, d in [(1.0, 170.0), (2.0, -170.0), (3.0, 180.0)]
    ]
    values, undefined = aggregate_fov(frames, [3, 4, 5], defs, frame_interval=0.5)
    assert values["speed_xy_median__tmean"] == 2.0
    assert values["speed_xy_median__tsd"] == pytest.approx(1.0)
    assert values["speed_xy_median__tmin"] == 1.0 and values["speed_xy_median__tmax"] == 3.0
    assert values["speed_xy_median__tslope"] == pytest.approx(2.0)  # 1 per 0.5 min
    assert abs(values["xy_dominant_direction_deg__tcircmean"]) == pytest.approx(180.0)
    assert values["xy_dominant_direction_deg__tcircsd"] < 10
    assert values["n_flow_frames"] == 3
    assert "0 defined frame(s) of 3" in undefined["coherence_xy_global__tmean"]


def test_slope_needs_three_frames_and_sd_two():
    defs = frame_dictionary("xy")
    values, undefined = aggregate_fov(
        [{"speed_xy_mean": 1.0}, {"speed_xy_mean": np.nan}], [3, 4], defs, None
    )
    assert values["speed_xy_mean__tmean"] == 1.0
    assert np.isnan(values["speed_xy_mean__tsd"]) and np.isnan(values["speed_xy_mean__tslope"])
    assert "1 defined frame(s) of 2" in undefined["speed_xy_mean__tslope"]


def test_fov_feature_count_is_in_the_planned_range():
    for mode in ("xy", "xyz"):
        fov_defs = fov_dictionary(frame_dictionary(mode), "min")
        usable = [d for d in fov_defs if d.applicability != QC]
        biological = [d for d in fov_defs if d.applicability == BIOLOGICAL]
        assert 100 <= len(usable) <= 150, (mode, len(usable))
        assert len(biological) >= (60 if mode == "xy" else 45)  # 3D speed is axial
        assert all(d.undefined and d.formula and d.unit for d in fov_defs)
    frame_defs = frame_dictionary("xy")
    assert 30 <= len([d for d in frame_defs if d.applicability != QC]) <= 40


def metadata(**changes):
    row = {
        "sample_id": "s1",
        "position_id": "p1",
        "condition": "ctrl",
        "biological_repeat": "r1",
        "technical_repeat": "t1",
        "batch": "b1",
        "input_path": "/data/a.tif",
    }
    row.update(changes)
    return row


def test_same_position_in_different_conditions_gets_different_ids():
    a, b = fov_uid(metadata()), fov_uid(metadata(condition="drug"))
    assert a != b and a == fov_uid(metadata())
    assert fov_uid(metadata(condition="a b")) != fov_uid(metadata(condition="a-b"))


def test_metadata_validation():
    table = pd.DataFrame([metadata(), metadata(condition="drug", input_path="/data/b.tif")])
    out = validate_metadata(table)
    assert list(out.columns[:2]) == ["fov_uid", "sample_id"]
    assert out["fov_uid"].is_unique
    with pytest.raises(InputError, match="lacks the columns: batch"):
        validate_metadata(table.drop(columns="batch"))
    with pytest.raises(InputError, match="same condition, repeats"):
        validate_metadata(pd.DataFrame([metadata(), metadata(input_path="/x.tif")]))
    with pytest.raises(InputError, match="more than once"):
        validate_metadata(pd.DataFrame([metadata(), metadata(position_id="p2")]))
    with pytest.raises(InputError, match="empty"):
        validate_metadata(pd.DataFrame([metadata(batch=" ")]))


def test_relative_paths_resolve_against_the_csv(tmp_path):
    pd.DataFrame([metadata(input_path="images/a.tif")]).to_csv(tmp_path / "m.csv", index=False)
    table = read_metadata(tmp_path / "m.csv")
    assert table.loc[0, "input_path"] == (tmp_path.resolve() / "images/a.tif").as_posix()
