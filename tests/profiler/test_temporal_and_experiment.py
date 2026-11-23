import numpy as np
import pandas as pd
import pytest
from opticalflow3d_profiler.experiment import fov_uid, validate_metadata
from opticalflow3d_profiler.feature_dictionary import BIOLOGICAL, QC, frame_dictionary
from opticalflow3d_profiler.temporal_features import aggregate_fov, fov_dictionary
from opticalflow3d_profiler.validation import InputError


def test_time_average_of_a_known_series():
    defs = frame_dictionary("xy")
    frames = [
        {"speed_xy_median": v, "xy_dominant_direction_deg": d}
        for v, d in [(1.0, 170.0), (2.0, -170.0), (3.0, 180.0)]
    ]
    values, undefined = aggregate_fov(frames, defs)
    assert values["speed_xy_median"] == 2.0  # same column name as the per-frame table
    assert abs(values["xy_dominant_direction_deg"]) == pytest.approx(180.0)  # circular mean
    assert values["n_flow_frames"] == 3
    assert "0 defined frame(s) of 3" in undefined["coherence_xy_global"]
    assert not any("_time_" in k for k in values)


def test_undefined_frames_are_left_out_never_zero():
    defs = frame_dictionary("xy")
    values, undefined = aggregate_fov([{"speed_xy_mean": 1.0}, {"speed_xy_mean": np.nan}], defs)
    assert values["speed_xy_mean"] == 1.0 and "speed_xy_mean" not in undefined


def test_fov_dictionary_mirrors_the_frame_dictionary():
    for mode in ("xy", "xyz"):
        frame_defs = frame_dictionary(mode)
        fov_defs = fov_dictionary(frame_defs)
        assert [d.name for d in fov_defs] == [d.name for d in frame_defs]
        assert all(d.level == "fov" and d.undefined and d.formula for d in fov_defs)
        assert len([d for d in fov_defs if d.applicability == BIOLOGICAL]) >= (
            20 if mode == "xy" else 12
        )
    assert 30 <= len([d for d in frame_dictionary("xy") if d.applicability != QC]) <= 40


def metadata(**changes):
    row = {
        "position_id": "p1",
        "condition": "ctrl",
        "biological_repeat": "r1",
        "technical_repeat": "t1",
        "image_path": "/data/a.tif",
    }
    row.update(changes)
    return row


def test_same_position_in_different_conditions_gets_different_ids():
    a, b = fov_uid(metadata()), fov_uid(metadata(condition="drug"))
    assert a != b and a == fov_uid(metadata())
    assert fov_uid(metadata(condition="a b")) != fov_uid(metadata(condition="a-b"))


def test_metadata_validation():
    table = pd.DataFrame([metadata(), metadata(condition="drug", image_path="/data/b.tif")])
    out = validate_metadata(table)
    assert list(out.columns[:5]) == [
        "fov_uid", "condition", "biological_repeat", "technical_repeat", "position_id"
    ]  # fmt: skip
    assert out["fov_uid"].is_unique
    with pytest.raises(InputError, match="lacks the columns: technical_repeat"):
        validate_metadata(table.drop(columns="technical_repeat"))
    with pytest.raises(InputError, match="same condition, repeats"):
        validate_metadata(pd.DataFrame([metadata(), metadata(image_path="/x.tif")]))
    with pytest.raises(InputError, match="more than once"):
        validate_metadata(pd.DataFrame([metadata(), metadata(position_id="p2")]))
    with pytest.raises(InputError, match="empty"):
        validate_metadata(pd.DataFrame([metadata(condition=" ")]))
    with pytest.raises(InputError, match="invalid_name"):
        validate_metadata(pd.DataFrame([metadata(condition="NA")]))


def test_intensity_columns_are_opt_in_in_the_dictionary():
    names = {d.name for d in frame_dictionary("xy")}
    assert "qc_foreground_intensity_mean" not in names
    assert "qc_foreground_intensity_mean" in {d.name for d in frame_dictionary("xy", True)}


def test_metadata_identity_whitespace_is_refused_not_trimmed():
    with pytest.raises(InputError, match="invalid_name"):
        validate_metadata(pd.DataFrame([metadata(condition="ctrl ")]))


def test_image_paths_are_kept_literally():
    # Re-validation m1: an image path is never trimmed (a file name may end with a space).
    table = validate_metadata(pd.DataFrame([metadata(image_path=" /data/a.tif ")]))
    assert table["image_path"].iloc[0] == " /data/a.tif "
    with pytest.raises(InputError, match="empty"):
        validate_metadata(pd.DataFrame([metadata(image_path="  ")]))
