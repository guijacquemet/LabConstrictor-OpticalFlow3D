import numpy as np
import pytest
import tifffile
from opticalflow3d_profiler.config import ImageSpec
from opticalflow3d_profiler.image_io import file_identity, inspect_tiff, read_frames, validate_image
from opticalflow3d_profiler.validation import InputError


def test_imagej_header_and_calibration_suggestion(imagej_file):
    path, stack = imagej_file
    header = inspect_tiff(path)
    assert header.shape == stack.shape
    assert header.header_axes == "TZYX"
    assert header.format == "ImageJ TIFF"
    cal = header.calibration_suggestion
    assert cal.pixel_size_x == pytest.approx(0.65)
    assert cal.pixel_size_z == pytest.approx(2.0)
    assert cal.frame_interval is None  # no frame interval in the header: never invented


def test_imagej_frame_interval_without_unit_is_not_guessed(tmp_path):
    path = tmp_path / "t.tif"
    tifffile.imwrite(
        path,
        np.zeros((7, 3, 8, 8), np.uint16),
        imagej=True,
        metadata={"axes": "TZYX", "finterval": 30.0},
    )
    header = inspect_tiff(path)
    assert header.calibration_suggestion.frame_interval is None
    assert any("finterval" in n for n in header.notes)


def test_ome_calibration(tmp_path):
    path = tmp_path / "a.ome.tif"
    tifffile.imwrite(
        path,
        np.zeros((7, 3, 8, 8), np.uint16),
        ome=True,
        metadata={
            "axes": "TZYX",
            "PhysicalSizeX": 650,
            "PhysicalSizeXUnit": "nm",
            "PhysicalSizeY": 0.65,
            "PhysicalSizeZ": 2.0,
            "TimeIncrement": 30.0,
            "TimeIncrementUnit": "s",
        },
    )
    cal = inspect_tiff(path).calibration_suggestion
    assert (cal.pixel_size_x, cal.pixel_size_y, cal.pixel_size_z) == pytest.approx(
        (0.65,) * 2 + (2,)
    )
    assert cal.frame_interval == pytest.approx(0.5)
    assert cal.source == "header (OME)"


def test_plain_tiff_axes_are_ambiguous_and_refused_until_confirmed(tmp_path):
    path = tmp_path / "plain.tif"
    data = np.arange(7 * 3 * 4 * 5, dtype=np.uint16).reshape(7, 3, 4, 5)
    tifffile.imwrite(path, data, photometric="minisblack")
    header = inspect_tiff(path)
    assert header.axes_ambiguous
    with pytest.raises(InputError, match="not been confirmed"):
        read_frames(ImageSpec(path, ""), header, [0])
    out = read_frames(ImageSpec(path, "TZYX"), header, [2, 3])
    np.testing.assert_array_equal(out, data[2:4])


def test_multi_channel_videos_are_refused(multichannel_file):
    path, _ = multichannel_file
    with pytest.raises(InputError, match="single-channel videos"):
        read_frames(ImageSpec(path, "TZCYX"), inspect_tiff(path), [0])


def test_read_frames_keeps_dtype(imagej_file):
    path, stack = imagej_file
    out = read_frames(ImageSpec(path, "TZYX"), inspect_tiff(path), [4, 1])
    assert out.dtype == stack.dtype
    np.testing.assert_array_equal(out, stack[[4, 1]])


def test_other_axis_orders(tmp_path):
    data = np.random.default_rng(0).integers(0, 999, (3, 8, 1, 6, 7)).astype(np.uint16)
    path = tmp_path / "zt.tif"
    tifffile.imwrite(path, data)  # Z T C Y X stored order, a C axis of length 1
    header = inspect_tiff(path)
    out = read_frames(ImageSpec(path, "ZTCYX"), header, [5])
    np.testing.assert_array_equal(out[0], data[:, 5, 0])


def test_yx_must_be_last(tmp_path):
    path = tmp_path / "x.tif"
    tifffile.imwrite(path, np.zeros((7, 3, 8, 8), np.uint16), photometric="minisblack")
    with pytest.raises(InputError, match="last two axes"):
        read_frames(ImageSpec(path, "TYXZ"), inspect_tiff(path), [0])


def test_source_file_is_unchanged(imagej_file):
    path, _ = imagej_file
    before = file_identity(path)
    read_frames(ImageSpec(path, "TZYX"), inspect_tiff(path), [0, 1, 2])
    assert file_identity(path) == before


def test_missing_file(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        inspect_tiff(tmp_path / "nope.tif")


def test_rgb_samples_are_refused(tmp_path):
    path = tmp_path / "rgb.tif"
    tifffile.imwrite(
        path, np.zeros((7, 3, 8, 8), np.uint16), photometric="rgb", planarconfig="separate"
    )
    header = inspect_tiff(path)
    with pytest.raises(InputError, match="samples per pixel"):
        read_frames(ImageSpec(path, "TZYX"), header, [0])


def test_axes_named_by_the_header_cannot_be_reinterpreted(tmp_path):
    path = tmp_path / "tzyx.ome.tif"
    data = np.arange(11 * 7 * 4 * 4, dtype=np.uint16).reshape(11, 7, 4, 4)
    tifffile.imwrite(path, data, ome=True, photometric="minisblack", metadata={"axes": "TZYX"})
    header = inspect_tiff(path)
    assert header.header_axes == "TZYX" and not header.axes_ambiguous
    with pytest.raises(InputError, match="axes_contradict_header"):
        read_frames(ImageSpec(path, "ZTYX"), header, [0])  # Z planes would be read as time
    assert read_frames(ImageSpec(path, "TZYX"), header, [2]).shape == (1, 7, 4, 4)
    tcyx = tmp_path / "tcyx.tif"  # three channels, no Z
    tifffile.imwrite(
        tcyx, np.zeros((7, 3, 8, 8), np.uint16), imagej=True, metadata={"axes": "TCYX"}
    )
    with pytest.raises(InputError, match="axes_contradict_header"):
        validate_image(ImageSpec(tcyx, "TZYX"), inspect_tiff(tcyx))  # channels read as Z


def test_ome_values_without_units_are_flagged(tmp_path):
    path = tmp_path / "nounit.ome.tif"
    tifffile.imwrite(
        path,
        np.zeros((7, 3, 8, 8), np.uint16),
        ome=True,
        photometric="minisblack",
        metadata={"axes": "TZYX", "TimeIncrement": 30.0, "PhysicalSizeX": 0.5},
    )
    header = inspect_tiff(path)
    assert header.calibration_suggestion.frame_interval == pytest.approx(0.5)  # 30 s, OME default
    assert any("TimeIncrement (unit not stated: OME default s)" in n for n in header.notes)


@pytest.mark.parametrize(
    ("header_axes", "shape", "confirmed"),
    [("ZCYX", (7, 3, 8, 8), "TZYX"), ("ZCYX", (7, 1, 8, 8), "TZYX")],
)
def test_axes_named_without_t_cannot_be_read_as_time(tmp_path, header_axes, shape, confirmed):
    # Re-validation R3: a Z-stack with channels and no T was accepted as TZYX.
    path = tmp_path / "zstack.tif"
    tifffile.imwrite(path, np.zeros(shape, np.uint16), metadata={"axes": header_axes},
                     photometric="minisblack")  # fmt: skip
    header = inspect_tiff(path)
    assert header.header_axes == header_axes and header.axes_ambiguous
    with pytest.raises(InputError, match="axes_contradict_header"):
        validate_image(ImageSpec(path, confirmed), header)


def test_known_axes_keep_their_role_when_others_are_unknown():
    from opticalflow3d_profiler.image_io import named_axis_conflicts

    assert named_axis_conflicts("TZYX", "QZYX") == ""  # the unknown axis may be T
    assert "axis 2 is Z" in named_axis_conflicts("ZTYX", "QZYX")
    assert "axis 1 is Z" in named_axis_conflicts("TZYX", "ZCYX")
    assert named_axis_conflicts("TZYX", "IQYX") == ""


def test_ome_default_unit_notes_reach_the_section_1_summary(tmp_path):
    # Re-validation: the note must be in the table section 1 shows before confirmation.
    from opticalflow3d_profiler.experiment_check import header_summary

    path = tmp_path / "nounit.ome.tif"
    tifffile.imwrite(path, np.zeros((7, 3, 8, 8), np.uint16), ome=True, photometric="minisblack",
                     metadata={"axes": "TZYX", "TimeIncrement": 30.0})  # fmt: skip
    table = header_summary(inspect_tiff(path))
    notes = table.loc[table["field"] == "note", "value"]
    assert notes.str.contains("TimeIncrement (unit not stated: OME default s)", regex=False).any()


@pytest.mark.parametrize("header_axes", ["EZYX", "HZYX", "AZYX", "RZYX", "0ZYX"])
def test_other_named_axes_are_refused_not_read_as_time(tmp_path, header_axes):
    # Round 3: a named E (or H, A, R, 0) axis was user-confirmable and accepted as T.
    path = tmp_path / "named.tif"
    tifffile.imwrite(path, np.zeros((7, 3, 8, 8), np.uint16), metadata={"axes": header_axes},
                     photometric="minisblack")  # fmt: skip
    header = inspect_tiff(path)
    if header.header_axes != header_axes:
        pytest.skip(f"tifffile reads {header_axes} as {header.header_axes}")
    with pytest.raises(InputError, match="axes_contradict_header"):
        validate_image(ImageSpec(path, "TZYX"), header)


@pytest.mark.parametrize("header_axes", ["QZYX", "TQYX"])
def test_unknown_axes_remain_the_users_to_confirm(tmp_path, header_axes):
    path = tmp_path / "unknown.tif"
    tifffile.imwrite(path, np.zeros((7, 3, 8, 8), np.uint16), metadata={"axes": header_axes},
                     photometric="minisblack")  # fmt: skip
    header = inspect_tiff(path)
    assert header.header_axes == header_axes
    validate_image(ImageSpec(path, "TZYX"), header)  # no refusal
