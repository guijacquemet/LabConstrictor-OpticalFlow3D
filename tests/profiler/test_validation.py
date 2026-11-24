import pytest
from opticalflow3d_profiler.config import Calibration, FlowParameters
from opticalflow3d_profiler.validation import (
    InputError,
    check_axes,
    check_calibration,
    check_channel,
    check_time_and_depth,
    output_frame_map,
    raise_for_errors,
    to_micrometres,
    to_minutes,
)


def codes(issues):
    return {i.code for i in issues if i.severity == "error"}


def test_default_window_gives_nine_outputs_from_fifteen_frames():
    params = FlowParameters(mode="xyz")
    assert params.window_length == 7
    assert output_frame_map(15, params) == list(range(3, 12))
    assert output_frame_map(6, params) == []


def test_window_length_for_other_t_sig():
    assert FlowParameters(mode="xyz", t_sig=2).window_length == 13
    assert FlowParameters(mode="xyz", t_sig=1.5).window_length == 11  # ceil(9)+1=10, made odd


@pytest.mark.parametrize(
    "axes,shape,expected",
    [
        ("", (15, 11, 8, 8), {"axes_unconfirmed"}),
        ("TZYX", (15, 11, 2, 8, 8), {"axes_length"}),
        ("TZQYX", (15, 11, 2, 8, 8), {"axes_unknown"}),
        ("TTYX", (15, 11, 8, 8), {"axes_repeated", "axes_missing_z"}),
        ("TYX", (15, 8, 8), {"axes_missing_z"}),
    ],
)
def test_bad_axes_are_refused(axes, shape, expected):
    assert expected <= codes(check_axes(axes, shape))


def test_valid_axes_pass():
    assert not codes(check_axes("tzcyx", (15, 11, 2, 8, 8)))


def test_only_single_channel_videos_are_accepted():
    assert codes(check_channel("TZCYX", (15, 11, 2, 8, 8))) == {"multi_channel_not_supported"}
    assert not check_channel("TZCYX", (15, 11, 1, 8, 8))  # a C axis of length 1 is fine
    assert not check_channel("TZYX", (15, 11, 8, 8))


def test_too_few_frames_and_single_z():
    params = FlowParameters(mode="xyz")
    assert codes(check_time_and_depth(6, 11, params)) == {"too_few_frames"}
    assert codes(check_time_and_depth(15, 1, params)) == {"single_z"}
    warnings = {i.code for i in check_time_and_depth(15, 11, params)}
    assert "shallow_z" in warnings  # 11 slices < 19-tap kernel of xyzSig=3


def test_raise_for_errors_lists_messages():
    with pytest.raises(InputError, match="no Z axis"):
        raise_for_errors(check_axes("TYX", (5, 8, 8)))


def test_unit_conversion_and_missing_values():
    assert to_micrometres(650, "nm") == pytest.approx(0.65)
    assert to_minutes(30, "s") == pytest.approx(0.5)
    assert to_minutes(None, "s") is None
    with pytest.raises(InputError):
        to_micrometres(1, "pixel")
    with pytest.raises(InputError):
        to_minutes(0, "s")


def test_missing_calibration_is_reported_not_guessed():
    found = {i.code for i in check_calibration(Calibration())}
    assert found == {"calibration_lateral_missing", "calibration_z_missing"}
    assert not Calibration().lateral_known
    assert Calibration(0.5, 0.5, 2.0, 1.0).complete


def test_sigmas_must_be_positive_so_a_window_has_three_frames():
    for bad in (
        FlowParameters(t_sig=0),
        FlowParameters(xyz_sig=-1),
        FlowParameters(w_sig=float("nan")),
    ):
        assert codes(check_time_and_depth(15, 11, bad)) == {"invalid_sigma"}
    assert FlowParameters(t_sig=0.1).window_length >= 3
    huge = FlowParameters(t_sig=1e308)  # finite and positive, but 6 * tSig overflows
    assert codes(check_time_and_depth(15, 11, huge)) == {"sigma_too_large"}
    with pytest.raises(ValueError, match="too large"):
        _ = huge.window_length
    assert codes(check_time_and_depth(15, 11, FlowParameters(t_sig=0.1))) == set()
    for name in ("xyz_sig", "w_sig", "t_sig"):  # round 3: xyzSig=1e308 overflowed math.ceil
        huge_spatial = FlowParameters(**{name: 1e308})
        assert codes(check_time_and_depth(15, 11, huge_spatial)) == {"sigma_too_large"}


def test_calibration_must_be_finite_before_and_after_conversion():
    # Round 3: infinity was accepted and 1e308 mm overflowed to infinity in µm.
    from opticalflow3d_profiler.validation import InputError, to_micrometres, to_minutes

    with pytest.raises(InputError, match="positive finite"):
        to_micrometres(float("inf"), "µm")
    with pytest.raises(InputError, match="too large to convert"):
        to_micrometres(1e308, "mm")
    with pytest.raises(InputError, match="positive finite"):
        to_minutes(float("nan"), "s")
    assert to_micrometres(650, "nm") == pytest.approx(0.65)


def test_nan_and_infinite_settings_are_refused_not_read_as_empty():
    # Round 4: a NaN foreground or motion threshold selected nothing and reported 0.
    from opticalflow3d_profiler.config import FeatureSettings, ForegroundSpec
    from opticalflow3d_profiler.notebook_ui import number
    from opticalflow3d_profiler.validation import InputError, check_feature_settings

    for text in ("nan", "inf", "-inf", " NaN "):
        with pytest.raises(InputError, match="not a finite number"):
            number(text)
    assert number(" 2.5 ") == 2.5 and number("") is None
    cases = [
        (FeatureSettings(reliability_mode="absolute", reliability_value=float("nan")),
         ForegroundSpec()),
        (FeatureSettings(reliability_mode="none", motion_threshold=float("nan")), ForegroundSpec()),
        (FeatureSettings(reliability_mode="none"), ForegroundSpec("threshold", float("inf"))),
    ]  # fmt: skip
    for features, foreground in cases:
        assert "non_finite_setting" in codes(check_feature_settings(features, foreground))


def test_calibration_underflow_and_direct_objects_are_refused():
    from opticalflow3d_profiler.validation import (
        InputError,
        calibration_issues,
        to_micrometres,
        to_minutes,
    )

    with pytest.raises(InputError, match="too small to convert"):
        to_minutes(1e-320, "ms")
    with pytest.raises(InputError, match="too small to convert"):
        to_micrometres(5e-324, "nm")
    bad = Calibration(pixel_size_x=float("inf"), pixel_size_y=0.65, pixel_size_z=2.0,
                      frame_interval=1.0)  # fmt: skip
    assert codes(calibration_issues(bad)) == {"invalid_calibration"}
    assert calibration_issues(Calibration(0.65, 0.65, 2.0, 1.0)) == []
    assert calibration_issues(Calibration()) == []  # unknown values are allowed, never guessed


def test_resource_estimates_refuse_absurd_sigmas(tmp_path):
    from opticalflow3d_profiler.flow_backend import estimate_resources
    from opticalflow3d_profiler.validation import InputError

    with pytest.raises(InputError, match="sigma_too_large|at most"):
        estimate_resources({"T": 15, "Z": 11, "Y": 64, "X": 64}, 2,
                           FlowParameters(mode="xyz", t_sig=1e300), tmp_path)  # fmt: skip
