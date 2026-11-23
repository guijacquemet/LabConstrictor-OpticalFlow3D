"""Shared fixtures of the OpticalFlow3D Profiler tests (small generated images only)."""

import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from opticalflow3d_profiler.synthetic import SyntheticMovie, render  # noqa: E402


@pytest.fixture
def moving_movie():
    """A short synthetic movie moving in +x and +y."""
    movie = SyntheticMovie(shape=(9, 11, 64, 64), n_nuclei=10, velocity=(0.0, 0.3, 0.5))
    return movie, render(movie)


@pytest.fixture
def imagej_file(tmp_path, moving_movie):
    """A single-channel ImageJ hyperstack TZYX with calibration."""
    _, stack = moving_movie
    path = tmp_path / "fov.tif"
    tifffile.imwrite(
        path,
        stack,
        imagej=True,
        metadata={"axes": "TZYX", "spacing": 2.0, "unit": "um"},
        resolution=(1 / 0.65, 1 / 0.65),
    )
    return path, stack


@pytest.fixture
def multichannel_file(tmp_path, moving_movie):
    """A two-channel ImageJ hyperstack TZCYX (refused: single-channel videos only)."""
    _, data = moving_movie
    noise = np.random.default_rng(3).integers(0, 50, data.shape, dtype=np.uint16)
    stack = np.stack([noise, data], axis=2)
    path = tmp_path / "two_channels.tif"
    tifffile.imwrite(
        path,
        stack,
        imagej=True,
        metadata={"axes": "TZCYX", "spacing": 2.0, "unit": "um"},
        resolution=(1 / 0.65, 1 / 0.65),
    )
    return path, stack
