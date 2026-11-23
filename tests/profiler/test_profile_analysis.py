import numpy as np
import pandas as pd
import pytest
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


def test_core_selection_and_signed_vz_never_enter_pca():
    from opticalflow3d_profiler.feature_dictionary import frame_dictionary
    from opticalflow3d_profiler.temporal_features import fov_dictionary

    defs = fov_dictionary(frame_dictionary("xy"))
    names = [d.name for d in defs]
    t = pd.DataFrame(np.random.default_rng(0).normal(size=(6, len(names))), columns=names)
    t.insert(0, "fov_uid", [f"f{i}" for i in range(6)])
    core = prepare_matrix(t, ["fov_uid"], defs, PcaSettings(include_axial=True))
    assert "speed_xy_median" in core.matrix.columns and len(core.matrix.columns) <= 15
    wide = prepare_matrix(
        t, ["fov_uid"], defs, PcaSettings(selection="families", include_axial=True)
    )
    assert "vz_abs_mean" in wide.matrix.columns
    assert not any(c.startswith("vz_mean") for c in wide.matrix.columns)
