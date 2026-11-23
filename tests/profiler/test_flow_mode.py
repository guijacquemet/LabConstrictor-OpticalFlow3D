import numpy as np
import pytest
from opticalflow3d_profiler._upstream.calc_flow import calc_flow2D
from opticalflow3d_profiler.config import Calibration, FlowParameters
from opticalflow3d_profiler.flow_backend import compute_frame
from opticalflow3d_profiler.synthetic import SyntheticMovie, nuclear_interior, render
from opticalflow3d_profiler.validation import InputError, resolve_flow_mode


def test_auto_mode_follows_anisotropy_and_never_guesses():
    auto = FlowParameters()
    assert auto.mode == "auto"
    assert resolve_flow_mode(auto, Calibration(0.25, 0.25, 5.0, 60.0)).mode == "xy_per_slice"
    assert resolve_flow_mode(auto, Calibration(0.5, 0.5, 1.0, 1.0)).mode == "xyz"
    with pytest.raises(InputError, match="needs the XY pixel size and the Z spacing"):
        resolve_flow_mode(auto, Calibration(0.25, 0.25, None, 60.0))
    explicit = FlowParameters(mode="xyz")
    assert resolve_flow_mode(explicit, Calibration()) is explicit


def test_per_slice_mode_is_upstream_2d_on_every_slice():
    data = render(SyntheticMovie(shape=(7, 5, 48, 48), n_nuclei=4, velocity=(0, 0, 0.5)))
    out = compute_frame(data, FlowParameters(mode="xy_per_slice"))
    assert set(out) == {"vx", "vy", "rel"}
    for z in (0, 2, 4):
        vx, vy, rel = calc_flow2D(data[:, z], 3, 1, 4)
        np.testing.assert_array_equal(out["vx"][z], vx)
        np.testing.assert_array_equal(out["rel"][z], rel)


def test_per_slice_mode_recovers_lateral_speed_of_shallow_nuclei_better_than_3d():
    movie = SyntheticMovie(
        shape=(7, 11, 120, 120),
        n_nuclei=12,
        velocity=(0, 0, 1.0),
        sigma_xy=8.0,
        sigma_z=0.7,
        noise_sd=10,
        seed=3,
    )
    data = render(movie, dtype="float64")
    mask = nuclear_interior(movie, data[3])
    mask[:2] = mask[-2:] = False
    gain_3d = np.median(compute_frame(data, FlowParameters(mode="xyz"))["vx"][mask])
    gain_2d = np.median(compute_frame(data, FlowParameters(mode="xy_per_slice"))["vx"][mask])
    assert gain_2d > 0.85 and gain_3d < 0.5  # measured 0.95 versus 0.41
