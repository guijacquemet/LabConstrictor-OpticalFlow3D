"""Phase 1 scientific validation of the upstream algorithm on synthetic nuclei.

These tests document measured behaviour (README "Validation"): the expected ranges are
the ones observed, not a claim that the gain is 1.
"""

import numpy as np
import pytest
from opticalflow3d_profiler._upstream.calc_flow import calc_flow2D, calc_flow3D
from opticalflow3d_profiler.synthetic import SyntheticMovie, nuclear_interior, render

SHAPE = (7, 11, 80, 80)


def recovered(velocity, **kwargs):
    movie = SyntheticMovie(shape=SHAPE, n_nuclei=14, velocity=velocity, **kwargs)
    data = render(movie, dtype="float64")
    vx, vy, vz, rel = calc_flow3D(data)
    mask = nuclear_interior(movie, data[3])
    mask[:2] = mask[-2:] = False  # avoid the top and bottom slices
    return data, mask, vx, vy, vz, rel


def test_static_nuclei_give_zero_velocity():
    _, mask, vx, vy, vz, _ = recovered((0.0, 0.0, 0.0))
    for v in (vx, vy, vz):
        assert np.abs(v).max() < 1e-9


def test_lateral_translation_direction_and_gain():
    _, mask, vx, vy, vz, _ = recovered((0.0, 0.3, 0.5))
    gain_x, gain_y = np.median(vx[mask]) / 0.5, np.median(vy[mask]) / 0.3
    assert 0.4 < gain_x < 0.9 and 0.4 < gain_y < 0.9  # measured ~0.55: biased low in 3D
    assert abs(np.median(vz[mask])) < 0.02


def test_lateral_response_is_linear_in_speed():
    gains = []
    for speed in (0.25, 1.0):
        _, mask, vx, *_ = recovered((0.0, 0.0, speed))
        gains.append(np.median(vx[mask]) / speed)
    assert gains[0] == pytest.approx(gains[1], rel=0.15)


def test_axial_translation_is_recovered_inside_the_stack():
    _, mask, vx, vy, vz, _ = recovered((0.3, 0.0, 0.0))
    gain_z = np.median(vz[mask]) / 0.3
    assert 0.8 < gain_z < 1.3
    assert abs(np.median(vx[mask])) < 0.03


def test_2d_mid_plane_is_closer_to_truth_than_3d():
    data, mask, vx, *_ = recovered((0.0, 0.0, 0.5))
    vx2, _, _ = calc_flow2D(data[:, 5])
    plane = mask[5]
    assert np.median(vx2[plane]) / 0.5 > np.median(vx[5][plane]) / 0.5 + 0.2


def test_reliability_separates_signal_from_empty_background():
    data, mask, vx, _, _, rel = recovered((0.0, 0.0, 0.5))
    background = data[3] < 101
    assert np.median(rel[mask]) > 100 * max(np.median(rel[background]), 1e-12)


def test_noise_on_static_nuclei_is_small_compared_with_motion():
    _, mask, vx, vy, _, _ = recovered((0.0, 0.0, 0.0), noise_sd=20.0)
    _, mask_m, vx_m, vy_m, _, _ = recovered((0.0, 0.0, 0.5), noise_sd=20.0)
    static = np.median(np.hypot(vx, vy)[mask])
    moving = np.median(np.hypot(vx_m, vy_m)[mask_m])
    assert static < 0.25 * moving
