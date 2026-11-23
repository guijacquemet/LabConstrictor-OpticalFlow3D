import numpy as np
import pytest
import tifffile
from opticalflow3d_profiler.config import ImageSpec
from opticalflow3d_profiler.image_io import file_identity, inspect_tiff, read_frames
from opticalflow3d_profiler.validation import InputError


def test_imagej_header_and_calibration_suggestion(imagej_file):
    path, stack = imagej_file
    header = inspect_tiff(path)
    assert header.shape == stack.shape
    assert header.header_axes == "TZCYX"
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


def test_read_frames_selects_channel_and_keeps_dtype(imagej_file):
    path, stack = imagej_file
    header = inspect_tiff(path)
    with pytest.raises(InputError, match="none was selected"):
        read_frames(ImageSpec(path, "TZCYX"), header, [0])
    out = read_frames(ImageSpec(path, "TZCYX", channel=1), header, [4, 1])
    assert out.dtype == stack.dtype
    np.testing.assert_array_equal(out, stack[[4, 1], :, 1])


def test_other_axis_orders(tmp_path):
    data = np.random.default_rng(0).integers(0, 999, (3, 8, 2, 6, 7)).astype(np.uint16)
    path = tmp_path / "zt.tif"
    tifffile.imwrite(path, data)  # Z T C Y X stored order
    header = inspect_tiff(path)
    out = read_frames(ImageSpec(path, "ZTCYX", channel=0), header, [5])
    np.testing.assert_array_equal(out[0], data[:, 5, 0])


def test_yx_must_be_last(tmp_path):
    path = tmp_path / "x.tif"
    tifffile.imwrite(path, np.zeros((7, 3, 8, 8), np.uint16), photometric="minisblack")
    with pytest.raises(InputError, match="last two axes"):
        read_frames(ImageSpec(path, "TYXZ"), inspect_tiff(path), [0])


def test_source_file_is_unchanged(imagej_file):
    path, _ = imagej_file
    before = file_identity(path)
    read_frames(ImageSpec(path, "TZCYX", channel=1), inspect_tiff(path), [0, 1, 2])
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
