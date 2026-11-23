import numpy as np
import pytest
import tifffile
from opticalflow3d_profiler.config import ForegroundSpec
from opticalflow3d_profiler.foreground import check_mask, mask_frame, threshold_frame
from opticalflow3d_profiler.validation import InputError

DIMS = {"T": 5, "Z": 3, "Y": 8, "X": 9}


def write(tmp_path, data, name="m.tif"):
    path = tmp_path / name
    tifffile.imwrite(path, data, photometric="minisblack")
    return path


def test_time_dependent_mask_is_aligned_to_the_source_frame(tmp_path):
    data = np.zeros((5, 3, 8, 9), np.uint8)
    for t in range(5):
        data[t, :, t, :] = 1
    info = check_mask(
        ForegroundSpec("mask", mask_path=write(tmp_path, data), mask_axes="TZYX"), DIMS
    )
    frame = mask_frame(info, 3, DIMS)
    assert frame.shape == (3, 8, 9) and frame[:, 3].all() and frame.sum() == 27


def test_2d_mask_needs_the_explicit_plane_rule(tmp_path):
    path = write(tmp_path, np.ones((8, 9), np.uint8))
    with pytest.raises(InputError, match="never assumed"):
        check_mask(ForegroundSpec("mask", mask_path=path, mask_axes="YX"), DIMS)
    spec = ForegroundSpec(
        "mask", mask_path=path, mask_axes="YX", mask_plane_rule="same_mask_for_every_z"
    )
    assert mask_frame(check_mask(spec, DIMS), 0, DIMS).shape == (3, 8, 9)


def test_mask_shape_type_and_labels(tmp_path):
    with pytest.raises(InputError, match="source image coordinates"):
        check_mask(
            ForegroundSpec(
                "mask", mask_path=write(tmp_path, np.ones((2, 8, 9), np.uint8)), mask_axes="ZYX"
            ),
            DIMS,
        )
    with pytest.raises(InputError, match="integer or binary"):
        check_mask(
            ForegroundSpec(
                "mask",
                mask_path=write(tmp_path, np.ones((3, 8, 9), np.float32), "f.tif"),
                mask_axes="ZYX",
            ),
            DIMS,
        )
    labels = np.arange(3 * 8 * 9, dtype=np.uint16).reshape(3, 8, 9)
    info = check_mask(
        ForegroundSpec("mask", mask_path=write(tmp_path, labels, "l.tif"), mask_axes="ZYX"), DIMS
    )
    assert info.kind == "labels"
    with pytest.raises(InputError, match="Confirm the mask axes"):
        check_mask(ForegroundSpec("mask", mask_path=write(tmp_path, labels, "l2.tif")), DIMS)


def test_threshold_uses_raw_values():
    intensity = np.array([[[99, 100, 101]]], np.uint16)
    assert threshold_frame(intensity, 100).tolist() == [[[False, False, True]]]
