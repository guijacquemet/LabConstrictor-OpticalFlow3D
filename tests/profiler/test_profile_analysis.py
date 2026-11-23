import numpy as np
import pandas as pd
import pytest
from opticalflow3d_profiler.comparison import compare, hedges_g, replicate_means
from opticalflow3d_profiler.feature_dictionary import FeatureDef
from opticalflow3d_profiler.profile_analysis import PcaSettings, prepare_matrix, run_pca


def fdef(name, applicability="biological", family="magnitude"):
    return FeatureDef(name, family, "", "", "1", "fov", "", applicability, "")


DEFS = [
    fdef("a"),
    fdef("b"),
    fdef("c"),
    fdef("const"),
    fdef("gap"),
    fdef("qc_x", "qc", "quality"),
    fdef("z", "experimental_axial", "components"),
    fdef("dir", "orientation", "collective"),
]
META = ["fov_uid", "condition", "biological_repeat", "batch"]


def table(n=8, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "fov_uid": [f"f{i}" for i in range(n)],
            "condition": ["c", "d"] * (n // 2),
            "biological_repeat": [f"r{i // 2}" for i in range(n)],
            "batch": "b",
            "a": rng.normal(size=n),
            "b": rng.normal(size=n),
            "c": rng.normal(size=n),
            "const": 1.0,
            "gap": [np.nan] + list(rng.normal(size=n - 1)),
            "qc_x": rng.normal(size=n),
            "z": rng.normal(size=n),
            "dir": rng.normal(size=n),
        }
    )


def test_metadata_qc_orientation_and_axial_are_not_inputs_by_default():
    prepared = prepare_matrix(table(), META, DEFS, PcaSettings(selection="families"))
    assert list(prepared.matrix.columns) == ["a", "b", "c"]
    reasons = {e["feature"]: e["reason"] for e in prepared.excluded_features}
    assert reasons["const"] == "constant across fields of view"
    assert reasons["gap"].startswith("missing in 1")
    assert "qc" in reasons["qc_x"] and "orientation" in reasons["dir"]
    assert "experimental_axial" in reasons["z"]
    with_axial = prepare_matrix(
        table(), META, DEFS, PcaSettings(selection="families", include_axial=True)
    )
    assert "z" in with_axial.matrix.columns


def test_drop_fovs_policy_reports_removed_fovs():
    prepared = prepare_matrix(
        table(), META, DEFS, PcaSettings(selection="families", missing="drop_fovs")
    )
    assert "gap" in prepared.matrix.columns and "f0" not in prepared.matrix.index
    assert prepared.excluded_fovs == [
        {"fov_uid": "f0", "reason": "missing value in a selected feature"}
    ]


def test_family_selection():
    prepared = prepare_matrix(
        table(),
        META,
        DEFS,
        PcaSettings(selection="families", families=("components",), include_axial=True),
    )
    assert list(prepared.matrix.columns) == ["z"]


def test_few_repeats_warning_and_pca_output():
    few = prepare_matrix(
        table(4), META, DEFS, PcaSettings(selection="families")
    )  # 2 repeats per condition
    assert any("Fewer than 3 independent" in w for w in few.warnings)
    prepared = prepare_matrix(table(), META, DEFS, PcaSettings(selection="families"))
    assert not any("Fewer than 3" in w for w in prepared.warnings)
    result = run_pca(prepared, 2)
    assert list(result.scores.columns) == [*META, "PC1", "PC2"]
    assert result.scores["fov_uid"].tolist() == sorted(table()["fov_uid"])
    assert sum(result.explained_variance_ratio) <= 1.0
    assert set(result.loadings["feature"]) == {"a", "b", "c"}


def test_duplicate_fov_is_refused():
    t = table()
    t.loc[1, "fov_uid"] = "f0"
    with pytest.raises(ValueError, match="once"):
        prepare_matrix(t, META, DEFS, PcaSettings(selection="families"))


def design(paired_complete=True):
    rows = []
    for rep in ("r1", "r2", "r3"):
        for fov in range(3):
            rows.append({"condition": "ctrl", "biological_repeat": rep, "v": 1.0 + fov * 0.1})
            if paired_complete or rep != "r3":
                rows.append({"condition": "drug", "biological_repeat": rep, "v": 2.0 + fov * 0.1})
    return pd.DataFrame(rows)


def test_fovs_are_averaged_within_repeats():
    reps = replicate_means(design(), "v")
    assert len(reps) == 6 and (reps["n_fovs"] == 3).all()
    out = compare(design(), "v", "ctrl", "drug")
    assert out["n_repeats_control"] == 3  # not 9 FOVs
    assert out["difference"] == pytest.approx(1.0)


def test_tests_need_three_repeats_and_complete_pairs():
    small = design()[design()["biological_repeat"] != "r3"]
    assert compare(small, "v", "ctrl", "drug")["test"] == "not run"
    with pytest.raises(ValueError, match="lack one of the two"):
        compare(design(paired_complete=False), "v", "ctrl", "drug", paired=True)
    noisy = design()
    noisy.loc[noisy["biological_repeat"] == "r2", "v"] += 0.3
    assert compare(noisy, "v", "ctrl", "drug", paired=True)["test"].startswith("paired")


def test_hedges_g():
    a, b = np.array([1.0, 2.0, 3.0]), np.array([2.0, 3.0, 4.0])
    assert hedges_g(a, b)[0] == pytest.approx(1.0 * (1 - 3 / (4 * 6 - 9)))
    assert np.isnan(hedges_g(a[:1], b)[0])
    g, note = hedges_g(np.ones(3), np.full(3, 2.0))
    assert np.isnan(g) and "no variation" in note


def test_unrelated_conditions_do_not_break_pairing():
    t = pd.concat(
        [design(), pd.DataFrame([{"condition": "other", "biological_repeat": "r9", "v": 5.0}])]
    )
    assert compare(t, "v", "ctrl", "drug", paired=True)["n_repeats_control"] == 3


def test_missing_pairs_are_recorded():
    t = pd.concat(
        [
            design(),
            pd.DataFrame(
                [{"condition": c, "biological_repeat": "r4", "v": np.nan} for c in ("ctrl", "drug")]
            ),
        ]
    )
    out = compare(t, "v", "ctrl", "drug", paired=True)
    assert "ctrl/r4" in out["repeats_excluded"] and "drug/r4" in out["repeats_excluded"]
    assert out["n_fovs_missing"] == 2


def test_degenerate_tests_are_flagged():
    flat = pd.DataFrame(
        [
            {"condition": c, "biological_repeat": f"r{i}", "v": float(v)}
            for c, v in (("ctrl", 1), ("drug", 2))
            for i in range(3)
        ]
    )
    out = compare(flat, "v", "ctrl", "drug")
    assert "not interpretable" in out["test"] and np.isnan(out["p_value"])
    assert "no variation" in out["hedges_g_note"]


def test_repeat_identity_column_is_used():
    t = design()
    t["repeat_id"] = t["biological_repeat"] + "-" + t.index.astype(str)  # every FOV its own
    assert compare(t, "v", "ctrl", "drug")["n_repeats_control"] == 9


def test_core_selection_and_signed_vz_never_enter_pca():
    from opticalflow3d_profiler.feature_dictionary import frame_dictionary
    from opticalflow3d_profiler.temporal_features import fov_dictionary

    defs = fov_dictionary(frame_dictionary("xy"), "min")
    names = [d.name for d in defs]
    t = pd.DataFrame(np.random.default_rng(0).normal(size=(6, len(names))), columns=names)
    t.insert(0, "fov_uid", [f"f{i}" for i in range(6)])
    core = prepare_matrix(t, ["fov_uid"], defs, PcaSettings(include_axial=True))
    assert "speed_xy_median__tmean" in core.matrix.columns and len(core.matrix.columns) <= 15
    wide = prepare_matrix(
        t, ["fov_uid"], defs, PcaSettings(selection="families", include_axial=True)
    )
    assert "vz_abs_mean__tmean" in wide.matrix.columns
    assert not any(c.startswith("vz_mean") for c in wide.matrix.columns)
