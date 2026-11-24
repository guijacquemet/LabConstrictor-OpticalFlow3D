import numpy as np
import pytest
from opticalflow3d_profiler.config import Calibration, FeatureSettings
from opticalflow3d_profiler.flow_features import (
    angular_entropy,
    frame_features,
    local_coherence_map,
    velocity_scale,
)

SHAPE = (3, 32, 32)
NONE = FeatureSettings(reliability_mode="none", region_size_px=16, min_region_voxels=10)


def flow(vx=0.0, vy=0.0, vz=0.0, rel=1.0):
    def full(v):
        return np.broadcast_to(np.asarray(v, dtype=float), SHAPE).copy()

    return {"vx": full(vx), "vy": full(vy), "vz": full(vz), "rel": full(rel)}


def features(f, settings=NONE, foreground=None, calibration=None, intensity=None):
    return frame_features(f, foreground, intensity, calibration or Calibration(), settings)


def test_zero_field_keeps_zero_and_explains_undefined():
    row = features(flow())
    assert row.values["speed_xy_mean"] == 0.0 and row.values["speed_xy_max"] == 0.0
    assert np.isnan(row.values["speed_xy_cv"]) and "zero" in row.undefined["speed_xy_cv"]
    assert np.isnan(row.values["coherence_xy_global"])
    assert "fewer than 20" in row.undefined["xy_angular_entropy"]
    assert row.values["qc_n_analysed_voxels"] == np.prod(SHAPE)


def test_uniform_motion():
    row = features(flow(vx=2.0))
    assert row.values["speed_xy_median"] == pytest.approx(2.0)
    assert row.values["speed_xy_sd"] == pytest.approx(0.0)
    assert row.values["coherence_xy_global"] == pytest.approx(1.0)
    assert row.values["coherence_xy_local"] == pytest.approx(1.0)
    assert row.values["xy_angular_entropy"] == pytest.approx(0.0)
    assert row.values["xy_angular_dispersion"] == pytest.approx(0.0, abs=1e-12)
    assert row.values["xy_aligned_fraction"] == 1.0
    assert row.values["xy_dominant_direction_deg"] == pytest.approx(0.0)


def test_opposing_halves_are_globally_incoherent_but_locally_coherent():
    vx = np.ones(SHAPE)
    vx[:, :, 16:] = -1.0
    f = flow()
    f["vx"] = vx
    row = features(f)
    assert row.values["coherence_xy_global"] == pytest.approx(0.0, abs=1e-12)
    local = local_coherence_map(vx, np.zeros(SHAPE), np.ones(SHAPE, bool), 5)
    assert np.nanmedian(local) == pytest.approx(1.0)
    assert row.values["xy_angular_dispersion"] == pytest.approx(1.0)
    assert np.isnan(row.values["xy_aligned_fraction"])  # no dominant direction


def test_3d_coherence_and_known_magnitudes():
    settings = FeatureSettings(speed_mode="xyz", reliability_mode="none")
    row = features(flow(vx=3.0, vz=4.0), settings, calibration=Calibration(1.0, 1.0, 1.0, 1.0))
    assert row.values["speed_3d_mean"] == pytest.approx(5.0)
    assert row.values["lateral_speed_mean"] == pytest.approx(3.0)
    assert row.values["coherence_3d_global"] == pytest.approx(1.0)
    assert row.values["axial_lateral_ratio"] == pytest.approx(4.0 / 3.0)


def test_physical_calibration_per_axis():
    cal = Calibration(0.5, 0.25, 2.0, 2.0)
    scale = velocity_scale(cal)
    assert (scale.x, scale.y, scale.z) == (0.25, 0.125, 1.0)
    assert scale.lateral_unit == scale.axial_unit == "µm/min"
    row = features(flow(vx=1.0), calibration=cal)
    assert row.values["speed_xy_mean"] == pytest.approx(0.25)


def test_mixed_units_make_axial_ratio_undefined():
    cal = Calibration(0.5, 0.5, None, 1.0)
    row = features(flow(vx=1.0, vz=1.0), calibration=cal)
    assert np.isnan(row.values["axial_lateral_ratio"])
    assert "physical unit" in row.undefined["axial_lateral_ratio"]
    settings = FeatureSettings(speed_mode="xyz", reliability_mode="none")
    row = features(flow(vx=1.0, vz=1.0), settings, calibration=cal)
    assert np.isnan(row.values["speed_3d_mean"])


def test_non_finite_velocities_are_excluded_and_counted_never_zeroed():
    f = flow(vx=1.0)
    f["vx"][0, 0, :4] = np.nan
    f["vy"][0, 1, :4] = np.inf
    row = features(f)
    n = np.prod(SHAPE)
    assert row.values["qc_n_analysed_voxels"] == n - 8
    assert row.values["speed_xy_p10"] == pytest.approx(1.0)
    assert row.values["qc_invalid_velocity_fraction"] == pytest.approx(8 / n)


def test_reliability_modes():
    f = flow(vx=1.0)
    f["rel"] = np.arange(np.prod(SHAPE), dtype=float).reshape(SHAPE)
    absolute = features(f, FeatureSettings(reliability_value=1000.0))
    assert absolute.values["qc_n_analysed_voxels"] == np.prod(SHAPE) - 1000
    assert absolute.values["qc_reliability_threshold"] == 1000.0
    pct = features(f, FeatureSettings(reliability_mode="percentile", reliability_value=75))
    assert pct.values["qc_reliable_fraction"] == pytest.approx(0.25, abs=0.01)
    with pytest.raises(ValueError, match="reliability value"):
        features(f, FeatureSettings(reliability_value=None))


def test_foreground_restricts_measurement_and_reports_occupancy():
    f = flow(vx=1.0)
    f["vx"][:, :, 16:] = 5.0
    fg = np.zeros(SHAPE, bool)
    fg[:, :, :16] = True
    with_intensity = FeatureSettings(
        reliability_mode="none", region_size_px=16, min_region_voxels=10, intensity_features=True
    )
    row = features(f, with_intensity, foreground=fg, intensity=np.full(SHAPE, 7.0))
    assert row.values["speed_xy_max"] == pytest.approx(1.0)
    assert row.values["qc_foreground_fraction"] == pytest.approx(0.5)
    assert row.values["qc_foreground_intensity_mean"] == 7.0
    assert row.values["qc_n_objects"] == 1.0
    assert row.values["qc_object_mean_z_extent"] == 3.0
    empty = features(f, foreground=np.zeros(SHAPE, bool))
    assert np.isnan(empty.values["speed_xy_mean"])
    assert "no analysed" in empty.undefined["speed_xy_mean"]


def test_regional_heterogeneity():
    f = flow(vx=1.0)
    f["vx"][:, :, 16:] = 3.0  # 2x2 grid of 16-px regions: speeds 1, 3, 1, 3
    settings = FeatureSettings(
        reliability_mode="none", region_size_px=16, min_region_voxels=10, motion_threshold=2.0
    )
    row = features(f, settings)
    assert row.values["qc_n_regions_analysed"] == 4
    assert row.values["regional_speed_cv"] == pytest.approx(0.5)
    assert row.values["regional_speed_spread"] == pytest.approx(1.0)  # (P90 3 - P10 1) / median 2
    assert row.values["regional_moving_fraction"] == 0.5
    assert row.values["regional_coherence_sd"] == pytest.approx(0.0)
    no_threshold = features(f, NONE)
    assert "threshold" in no_threshold.undefined["regional_moving_fraction"]


def test_uncalibrated_3d_features_are_undefined_not_pixel_slice_mixtures():
    settings = FeatureSettings(speed_mode="xyz", reliability_mode="none")
    row = features(flow(vx=3.0, vz=4.0), settings)  # px/frame and slice/frame
    for name in ("speed_3d_mean", "coherence_3d_global", "axial_lateral_ratio"):
        assert np.isnan(row.values[name]), name
    assert "calibration" in row.undefined["speed_3d_mean"]


def test_undefined_3d_speed_never_becomes_a_zero_moving_fraction():
    settings = FeatureSettings(
        speed_mode="xyz",
        reliability_mode="none",
        region_size_px=16,
        min_region_voxels=10,
        motion_threshold=0.1,
    )
    row = features(flow(vx=1.0), settings, calibration=Calibration(0.5, 0.5, None, 1.0))
    for name in ("regional_moving_fraction", "regional_speed_cv", "regional_speed_spread"):
        assert np.isnan(row.values[name]) and "calibration" in row.undefined[name], name
    assert row.values["regional_coherence_sd"] == pytest.approx(0.0)  # XY-only stays defined


def test_non_finite_reliability_never_sets_the_threshold():
    f = flow(vx=1.0)
    f["rel"] = np.arange(np.prod(SHAPE), dtype=float).reshape(SHAPE)
    f["rel"][0, 0, :5] = np.nan
    f["rel"][0, 1, :5] = np.inf
    row = features(f, FeatureSettings(reliability_mode="percentile", reliability_value=50))
    assert np.isfinite(row.values["qc_reliability_threshold"])
    assert row.values["qc_n_analysed_voxels"] > 0.4 * np.prod(SHAPE)
    assert np.isfinite(row.values["qc_reliability_median"])
    assert row.values["qc_invalid_reliability_fraction"] == pytest.approx(10 / np.prod(SHAPE))


def test_angular_entropy_does_not_depend_on_image_orientation():
    rng = np.random.default_rng(0)
    angles = np.deg2rad(rng.normal(0, 4, np.prod(SHAPE))).reshape(SHAPE)
    values = []
    for rotation in (0.0, 5.0, 37.0, 181.0):
        f = flow()
        f["vx"], f["vy"] = (
            np.cos(angles + np.deg2rad(rotation)),
            np.sin(angles + np.deg2rad(rotation)),
        )
        values.append(features(f).values["xy_angular_entropy"])
    assert max(values) - min(values) < 1e-6


def test_angular_features_need_enough_directed_vectors():
    f = flow()
    f["vx"][0, 0, :3] = 1.0  # three moving vectors only
    row = features(f)
    assert np.isnan(row.values["xy_aligned_fraction"])
    assert "fewer than 20" in row.undefined["xy_aligned_fraction"]
    slow = flow(vx=0.01)
    row = features(slow, FeatureSettings(reliability_mode="none", min_direction_speed=0.1))
    assert np.isnan(row.values["xy_angular_entropy"])
    assert row.values["speed_xy_mean"] == pytest.approx(0.01)  # speeds are unchanged


def test_sparse_windows_have_no_local_coherence():
    vx = np.zeros(SHAPE)
    vx[1, 10, 10] = 1.0
    mask = np.ones(SHAPE, bool)
    sparse = local_coherence_map(vx, np.zeros(SHAPE), mask, 5, min_vectors=5)
    assert np.isnan(sparse).all()
    assert np.nanmax(local_coherence_map(vx, np.zeros(SHAPE), mask, 5, min_vectors=1)) == 1.0


def test_intensity_qc_is_opt_in_and_needs_a_foreground():
    assert "qc_foreground_intensity_mean" not in features(flow(vx=1.0)).values
    settings = FeatureSettings(reliability_mode="none", intensity_features=True)
    row = features(flow(vx=1.0), settings, intensity=np.full(SHAPE, 7.0))
    assert np.isnan(row.values["qc_foreground_intensity_mean"])
    assert "no foreground" in row.undefined["qc_foreground_intensity_mean"]
    assert features(flow(vx=1.0)).values["qc_region_grid_coverage"] == 1.0


TWO_STREAMS = np.deg2rad(np.r_[np.full(20, -5.0), np.full(20, 5.0)])  # bin edges at 36 bins


@pytest.mark.parametrize("rotation_deg", [10.0, 180.0, 5.0, 2.5, 1e-9, 37.0, -90.0])
def test_angular_entropy_is_rotation_invariant_on_and_near_bin_edges(rotation_deg):
    # Re-validation R1: -5° and +5° gave 0.193, the same streams turned by 10° gave 0.
    reference = angular_entropy(TWO_STREAMS, 36)
    assert 0 < reference < 1
    turned = TWO_STREAMS + np.deg2rad(rotation_deg)
    assert angular_entropy(turned, 36) == pytest.approx(reference, abs=1e-6)
    nudged = turned
    for _ in range(2):  # one, then two ULPs off the rotated positions
        nudged = np.nextafter(nudged, np.inf)
        assert angular_entropy(nudged, 36) == pytest.approx(reference, abs=1e-6)


def test_angular_entropy_is_continuous_and_bounded():
    half = np.deg2rad([-25.0, -14, -10, 0, 4, 6, 12, 17, 26, 40])
    balanced = np.r_[half, half + np.pi]  # mean resultant 0
    nudged = balanced.copy()
    nudged[-1] += 3e-11  # moved the resultant across the old 1e-12 threshold
    assert angular_entropy(nudged, 36) == pytest.approx(angular_entropy(balanced, 36), abs=1e-9)
    assert angular_entropy(np.deg2rad(np.full(30, 12.3456)), 36) == pytest.approx(0.0, abs=1e-6)
    uniform = np.linspace(-np.pi, np.pi, 3600, endpoint=False)
    assert angular_entropy(uniform, 36) == pytest.approx(1.0, abs=1e-9)
    narrow, wide = (np.deg2rad(np.linspace(-s, s, 50)) for s in (10.0, 60.0))
    assert angular_entropy(narrow, 36) < angular_entropy(wide, 36)


def test_angular_entropy_is_defined_for_a_prime_resolution():
    # Re-validation: 37 bins and two opposite streams gave no anchor, so NaN.
    streams = np.deg2rad(np.r_[np.full(30, 10.0), np.full(30, 190.0)])
    value = angular_entropy(streams, 37)
    assert 0 < value < 1
    assert angular_entropy(streams + 0.123, 37) == pytest.approx(value, abs=1e-6)


@pytest.mark.parametrize("bins", [36, 360])
def test_angular_entropy_holds_its_tolerance_up_to_the_finest_resolution(bins):
    # Round 3: at 10,000 bins the 2**16 grid no longer resolved the kernel (errors ~3e-4).
    from opticalflow3d_profiler import flow_features

    step = 2 * np.pi / flow_features.ENTROPY_GRID
    for phase in (0.0, 0.25, 0.5):  # one direction on, near and halfway between grid points
        assert angular_entropy(np.full(40, phase * step), bins) == pytest.approx(0.0, abs=1e-6)
    reference = angular_entropy(TWO_STREAMS, bins)
    for turn in np.random.default_rng(3).uniform(0, 2 * np.pi, 20):
        assert angular_entropy(TWO_STREAMS + turn, bins) == pytest.approx(reference, abs=1e-6)
    sigma = 2 * np.pi / bins
    order = np.arange(flow_features.ENTROPY_GRID // 2 + 1)
    mass = flow_features._grid_mass(np.full(1, 0.5 * step))
    spectrum = np.fft.rfft(mass) * np.exp(-0.5 * (order * sigma) ** 2)
    assert np.fft.irfft(spectrum, flow_features.ENTROPY_GRID).min() > -1e-12  # round-off only


def test_angular_entropy_refuses_unresolved_resolutions():
    from opticalflow3d_profiler.config import ForegroundSpec
    from opticalflow3d_profiler.validation import check_feature_settings

    with pytest.raises(ValueError, match="outside 2..360"):
        angular_entropy(TWO_STREAMS, 361)
    issues = check_feature_settings(FeatureSettings(angle_bins=10_000), ForegroundSpec())
    assert "angle_bins_too_large" in {i.code for i in issues}


def test_angular_entropy_refuses_empty_or_non_finite_directions():
    # Round 4: [] and [NaN] returned a plausible-looking 0.15.
    for bad in (np.array([]), np.array([np.nan]), np.array([0.1, np.inf])):
        with pytest.raises(ValueError, match="finite direction"):
            angular_entropy(bad, 36)
    with pytest.raises(ValueError, match="outside 2..360"):
        features(flow(), FeatureSettings(reliability_mode="none", angle_bins=361))
