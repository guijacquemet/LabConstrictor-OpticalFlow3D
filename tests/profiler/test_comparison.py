"""MorphoCoverage-rule statistics: FOV as observation, biological repeat as replicate."""

import numpy as np
import pandas as pd
import pytest
from opticalflow3d_profiler import statistics as st
from opticalflow3d_profiler.comparison import ComparisonSettings, compare_conditions
from opticalflow3d_profiler.feature_dictionary import FeatureDef


def fdef(name, applicability="biological"):
    return FeatureDef(name, "magnitude", "", "", "1", "fov", "", applicability, "")


def experiment(effect=1.0, repeats=3, fovs=4, seed=0, conditions=("ctrl", "drug")):
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(repeats):
        shift = rng.normal(0, 0.1)
        for c in conditions:
            for f in range(fovs):
                value = 5 + shift + (effect if c != "ctrl" else 0) + rng.normal(0, 0.3)
                rows.append(
                    {"condition": c, "biological_repeat": f"r{r}", "fov_uid": f"{c}{r}{f}",
                     "whole__speed": value, "qc_reliable_fraction": rng.uniform(0.5, 1)}
                )  # fmt: skip
    return pd.DataFrame(rows)


DEFS = [fdef("whole__speed"), fdef("qc_reliable_fraction", "qc")]
FAST = ComparisonSettings("ctrl", permutations=999, balanced_permutations=199)


def test_cohen_d_matches_plot_and_stats():
    a, b = np.array([1.0, 2.0, 3.0]), np.array([2.0, 3.0, 4.0])
    assert st.cohen_d(b, a) == pytest.approx(1.0)
    assert np.isnan(st.cohen_d(a[:1], b))
    assert np.isnan(st.cohen_d(np.ones(3), np.ones(3)))


def test_randomization_p_floor_and_calibration():
    rng = np.random.default_rng(1)
    d, p = st.randomization(np.arange(5.0) + 10, np.arange(5.0), 999, rng)
    assert d > 0 and p == pytest.approx(2 / 252, abs=0.008)  # exact: 2 of C(10, 5) labellings
    rejections = [
        st.randomization(rng.normal(size=8), rng.normal(size=8), 199, rng)[1] <= 0.05
        for _ in range(300)
    ]
    assert 0.01 < np.mean(rejections) < 0.10  # about 5% without an effect


def test_balanced_test_is_calibrated_and_detects_effects():
    rng = np.random.default_rng(2)
    null = [
        st.balanced([rng.normal(size=n) for n in (6, 9)], [rng.normal(size=6) for _ in range(2)],
                    99, rng)[1] <= 0.05
        for _ in range(150)
    ]  # fmt: skip
    assert np.mean(null) < 0.12
    d, p, keep_t, keep_c = st.balanced(
        [rng.normal(2, 1, 6), rng.normal(2, 1, 9)], [rng.normal(0, 1, 6), rng.normal(0, 1, 7)],
        199, rng,
    )  # fmt: skip
    assert d > 1 and p < 0.05 and (keep_t, keep_c) == (6, 6)


def test_benjamini_hochberg_and_nan():
    q = st.benjamini_hochberg(np.array([0.01, 0.04, np.nan, 0.03]))
    assert np.isnan(q[2]) and q == pytest.approx([0.03, 0.04, np.nan, 0.04], nan_ok=True)


def test_paired_scale_log_ratio_and_minimum_repeats():
    assert st.paired_scale(np.array([1.0, 2.0])) == "log ratio"
    assert st.paired_scale(np.array([-1.0, 2.0])) == "difference"
    change, p, note = st.paired_repeats(np.array([2.0, 2.2]), np.array([1.0, 1.0]), "log ratio")
    assert np.isnan(p) and "fewer than 3" in note
    change, p, _ = st.paired_repeats(
        np.array([2.0, 2.2, 1.9]), np.array([1.0, 1.05, 1.0]), "log ratio"
    )
    assert change == pytest.approx(np.mean(np.log([2.0, 2.2 / 1.05, 1.9]))) and p < 0.01


def test_sign_flip_only_from_six_repeats():
    assert np.isnan(st.sign_flip(np.ones(5)))
    assert st.sign_flip(np.ones(6)) == pytest.approx(2 / 64)


def test_chance_without_effect_formula():
    assert st.chance_without_effect(30, 0.0) == pytest.approx(0.05)
    assert st.chance_without_effect(30, 0.25) == pytest.approx(0.16, abs=0.01)
    assert st.chance_without_effect(30, 0.5) == pytest.approx(0.37, abs=0.01)


def test_comparison_reads_fovs_and_repeats():
    tests, per_repeat = compare_conditions(experiment(), DEFS, FAST)
    row = tests[tests["family"] == "features"].iloc[0]
    assert row["fovs"] == 12 and row["control_fovs"] == 12 and row["repeats_paired"] == 3
    assert row["d_fovs"] > 1 and row["q_screen"] <= 0.05 and row["q_repeats"] <= 0.05
    assert row["verdict"] == "significant across repeats"
    assert row["paired_scale"] == "log ratio" and row["change"] > 1
    assert row["direction_per_repeat"] == "+++"
    assert row["screen_test"] == "p_fovs_normalised"  # balanced repeats: no balanced test
    assert len(per_repeat[per_repeat["feature"] == "whole__speed"]) == 3
    assert set(tests["family"]) == {"features", "qc"}


def test_two_repeats_give_candidates_only():
    tests, _ = compare_conditions(experiment(repeats=2, fovs=6), DEFS, FAST)
    row = tests.iloc[0]
    assert np.isnan(row["p_repeats"]) and "fewer than 3" in row["repeats_note"]
    assert row["verdict"] == "candidate (exploratory FOV-level screen only)"


def test_unbalanced_repeats_get_the_balanced_test():
    table = experiment(fovs=6)
    table = table.drop(table[(table["biological_repeat"] == "r0")].index[:1])  # 5 vs 6
    table = pd.concat([table, experiment(fovs=6, seed=3).assign(biological_repeat="r9")])
    table = table[~((table["biological_repeat"] == "r9") & (table.index % 2 == 0))]
    tests, _ = compare_conditions(table, DEFS, FAST)
    row = tests.iloc[0]
    assert bool(row["unbalanced"])
    assert row["screen_test"].startswith("p_balanced") or row["sparse_repeats"]


def test_control_from_other_repeats_withholds_the_test_as_provided():
    table = experiment()
    extra = experiment(seed=5).query("condition == 'ctrl'").assign(biological_repeat="rX")
    tests, _ = compare_conditions(pd.concat([table, extra]), DEFS, FAST)
    row = tests.iloc[0]
    assert np.isnan(row["p_fovs"]) and row["other_control_repeats"] == "rX"
    assert np.isfinite(row["p_fovs_normalised"])


def test_seeded_results_are_reproducible_and_order_free():
    a, _ = compare_conditions(experiment(conditions=("ctrl", "drug", "x")), DEFS, FAST)
    b, _ = compare_conditions(experiment(conditions=("ctrl", "drug", "x")).iloc[::-1], DEFS, FAST)
    key = ["feature", "condition"]
    a, b = a.sort_values(key).reset_index(drop=True), b.sort_values(key).reset_index(drop=True)
    assert np.allclose(a["p_fovs"], b["p_fovs"], equal_nan=True)


def test_unknown_control_is_refused():
    with pytest.raises(ValueError, match="not a condition"):
        compare_conditions(experiment(), DEFS, ComparisonSettings("none"))
