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
    assert codes(check_channel("TZYX", (15, 11, 8, 8), 1)) == {"channel_out_of_range"}


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
