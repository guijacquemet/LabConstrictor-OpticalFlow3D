"""Compare every condition with a declared control, following MorphoCoverage's rules (pure).

The observation is the field of view (its time-averaged profile, ``features_per_fov.csv``);
the biological repeat is the replicate. Each condition is compared with the control on every
selected feature, with MorphoCoverage's three answers (``docs/report/conditions.md``), on raw
and on normalised values (each value divided by the mean of the control of its own
biological repeat):

1. **Cohen's d** on the fields of view, pooled and per repeat (effect sizes, not tests);
2. **the FOV-level randomization test** on Cohen's d (labels shuffled over the fields of
   view), as provided and, when the repeats are unbalanced, the balanced permutation test.
   It is **exploratory**: it treats fields of view as independent, so when the effect varies
   between repeats it gives ``p <= 0.05`` without an effect more often than 5%
   (``chance_low``/``chance_high`` give that rate for 0.25-0.5 SD between repeats). Its
   passing features are candidates;
3. **the paired t-test on the repeat means** (log ratios when every observation of the
   feature is positive, else differences), from 3 biological repeats holding both the
   condition and the control; the exact sign-flip test is added from 6 repeats.

Benjamini-Hochberg q-values are computed per p column over every feature and condition (one
family per control); quality-control columns form their own family. Tests at ``p <= 0.05``
are rerun with enough shuffles that the smallest q can fall below 0.05, seeded from the
test's identity. A feature is *significant across repeats* when it passes the exploratory
screen (``q_screen <= 0.05``) and the paired test (``q_repeats <= 0.05``).

Fields of view are never averaged per biological repeat in a saved table: repeat means exist
only inside the paired test (and its per-repeat table), as MorphoCoverage computes them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import statistics as st
from .feature_dictionary import QC, FeatureDef
from .temporal_features import pca_eligible

IMBALANCE = 1.25
SPARSE = 0.25
MIN_BALANCED = 5
P_COLUMNS = ("p_fovs", "p_fovs_normalised", "p_balanced", "p_balanced_normalised", "p_repeats")
CONFOUNDERS = (
    "qc_foreground_intensity_mean",
    "qc_foreground_fraction",
    "qc_object_mean_voxels",
    "qc_object_mean_z_extent",
    "qc_reliable_fraction",
    "qc_reliability_threshold",
    "qc_brightness_change_per_frame",
)
"""QC columns compared alongside the features (their own family) as potential confounders."""


@dataclass(frozen=True)
class ComparisonSettings:
    """Choices of the comparison.

    Attributes
    ----------
    control
        The control condition every other condition is compared with.
    include_axial
        Also test experimental axial (Z-dependent) features.
    permutations
        Shuffles of the FOV-level randomization test (MorphoCoverage's screen: 9999).
    balanced_permutations
        Labellings of the balanced test (999).
    seed
        Seed of every shuffle (each test seeded from it and its identity).
    """

    control: str
    include_axial: bool = False
    permutations: int = 9999
    balanced_permutations: int = 999
    seed: int = 0


def repeat_column(table: pd.DataFrame) -> str:
    """Return the column identifying biological repeats (``repeat_id`` when present)."""
    return "repeat_id" if "repeat_id" in table.columns else "biological_repeat"


def _rng(settings: ComparisonSettings, *identity: object) -> np.random.Generator:
    """Return a generator seeded from the settings' seed and a test's identity (order-free)."""
    digest = hashlib.sha256("\x1f".join(map(str, identity)).encode("utf-8")).digest()
    return np.random.default_rng([settings.seed, int.from_bytes(digest[:8], "little")])


def tested_features(defs: list[FeatureDef], columns: list[str], include_axial: bool) -> list[str]:
    """Return the feature columns tested: biological (and optionally axial) ones present."""
    return [d.name for d in defs if pca_eligible(d, include_axial) and d.name in columns]


def _groups(table: pd.DataFrame, feature: str, condition: str) -> dict[str, np.ndarray]:
    """Return the defined values of one condition per biological repeat."""
    rows = table[table["condition"] == condition]
    values = pd.to_numeric(rows[feature], errors="coerce")
    out = {}
    for repeat, group in values.groupby(rows[repeat_column(table)], sort=True):
        defined = group.to_numpy(dtype=float)
        # Sorted, so the shuffles (seeded from the test's identity) do not depend on row order.
        defined = np.sort(defined[np.isfinite(defined)])
        if defined.size:
            out[str(repeat)] = defined
    return out


def _normalised(cond: dict, ctrl: dict, both: list[str]) -> tuple[dict, dict] | None:
    """Values divided by their repeat's control mean; None when a control mean is <= 0."""
    means = {r: float(np.mean(ctrl[r])) for r in both}
    if not both or any(not m > 0 for m in means.values()):
        return None
    return {r: cond[r] / means[r] for r in both}, {r: ctrl[r] / means[r] for r in both}


def _sparse(sizes: dict[str, int]) -> list[str]:
    """Repeats too small to balance to: < a quarter of the median repeat, or < 5 FOVs."""
    typical = float(np.median(list(sizes.values())))
    return [r for r, n in sizes.items() if n < SPARSE * typical or n < MIN_BALANCED]


def _unbalanced(cond: dict, ctrl: dict, other_control: list[str]) -> bool:
    """Return whether the repeats are unbalanced.

    True when one repeat holds more than 25% more FOVs than another on a side, or the control
    pools repeats the condition was not imaged in.
    """
    for side in (cond, ctrl):
        sizes = [len(v) for v in side.values()]
        if sizes and max(sizes) > IMBALANCE * min(sizes):
            return True
    return bool(other_control)


def _cell_tests(cond: dict, ctrl: dict, both: list[str], other: list[str], rng_for: _Seeds) -> dict:
    """Run the FOV-level tests of one feature and condition, and their reruns."""
    out: dict = {"retests": {}}
    treated, control = np.concatenate(list(cond.values())), np.concatenate(list(ctrl.values()))
    d, p = st.randomization(treated, control, rng_for.permutations, rng_for("fovs"))
    out["d_fovs"] = d
    out["p_fovs"] = np.nan if other else p
    out["retests"]["p_fovs"] = lambda b, rng: st.randomization(treated, control, b, rng)[1]
    norm = _normalised(cond, ctrl, both)
    out["d_fovs_normalised"] = out["p_fovs_normalised"] = np.nan
    if norm is not None:
        nt, nc = np.concatenate(list(norm[0].values())), np.concatenate(list(norm[1].values()))
        out["d_fovs_normalised"], out["p_fovs_normalised"] = st.randomization(
            nt, nc, rng_for.permutations, rng_for("fovs_normalised")
        )
        out["retests"]["p_fovs_normalised"] = lambda b, rng: st.randomization(nt, nc, b, rng)[1]
    out["unbalanced"] = _unbalanced({r: cond[r] for r in both} or cond, ctrl, other)
    small = (
        sorted(
            set(_sparse({r: len(cond[r]) for r in both}))
            | set(_sparse({r: len(ctrl[r]) for r in both}))
        )
        if both
        else []
    )
    out["sparse_repeats"] = "; ".join(small)
    kept = [r for r in both if r not in small] if out["unbalanced"] else []
    kept = kept if len(kept) >= 2 else []
    out["balanced_repeats"] = "; ".join(kept)
    for suffix, normalise in (("", False), ("_normalised", True)):
        out[f"d_balanced{suffix}"] = out[f"p_balanced{suffix}"] = np.nan
        if kept and (not normalise or norm is not None):
            t_parts, c_parts = [cond[r] for r in kept], [ctrl[r] for r in kept]
            b0 = rng_for.balanced_permutations
            d_b, p_b, *_ = st.balanced(
                t_parts, c_parts, b0, rng_for(f"balanced{suffix}"), normalise
            )
            out[f"d_balanced{suffix}"], out[f"p_balanced{suffix}"] = d_b, p_b
            out["retests"][f"p_balanced{suffix}"] = (
                lambda b, rng, t=t_parts, c=c_parts, n=normalise: st.balanced(t, c, b, rng, n)[1]
            )
    return out


def _screen_version(row: dict) -> str:
    """Return the FOV-level test the screen reads: normalised, balanced when unbalanced."""
    order = ["p_fovs_normalised", "p_fovs"]
    if row["unbalanced"]:
        order = ["p_balanced_normalised", "p_balanced", *order]
    return next((c for c in order if np.isfinite(row[c])), "")


class _Seeds:
    """Per-test generators and shuffle counts of one feature and condition."""

    def __init__(self, settings: ComparisonSettings, feature: str, condition: str) -> None:
        self.settings, self.identity = settings, (feature, condition)
        self.permutations = settings.permutations
        self.balanced_permutations = settings.balanced_permutations

    def __call__(self, test: str) -> np.random.Generator:
        return _rng(self.settings, *self.identity, test)


def _repeat_rows(feature: str, condition: str, cond: dict, ctrl: dict) -> list[dict]:
    """Per-repeat effect sizes and means of one feature and condition (descriptive)."""
    rows = []
    for repeat in sorted(set(cond) | set(ctrl)):
        a, b = cond.get(repeat, np.array([])), ctrl.get(repeat, np.array([]))
        rows.append(
            {
                "feature": feature,
                "condition": condition,
                "repeat": repeat,
                "n_fovs": a.size,
                "n_control_fovs": b.size,
                "mean": float(np.mean(a)) if a.size else np.nan,
                "control_mean": float(np.mean(b)) if b.size else np.nan,
                "d": st.cohen_d(a, b),
            }
        )
    return rows


def _paired(cond: dict, ctrl: dict, both: list[str], scale: str) -> dict:
    """Run the paired test on repeat means, the sign-flip test and the direction per repeat."""
    a = np.array([np.mean(cond[r]) for r in both])
    b = np.array([np.mean(ctrl[r]) for r in both])
    change, p, note = st.paired_repeats(a, b, scale)
    changes = np.log(a / b) if scale == "log ratio" else a - b
    signs = np.sign(a - b)
    return {
        "repeats_paired": len(both),
        "paired_scale": scale,
        "change": float(np.exp(change)) if scale == "log ratio" and np.isfinite(change) else change,
        "change_meaning": "fold change (geometric mean of repeat ratios)"
        if scale == "log ratio"
        else "mean difference of repeat means",
        "p_repeats": p,
        "repeats_note": note,
        "p_sign_flip": st.sign_flip(changes),
        "direction_per_repeat": "".join({1.0: "+", -1.0: "-"}.get(float(s), "0") for s in signs),
    }


def compare_one(
    table: pd.DataFrame, feature: str, condition: str, scale: str, settings: ComparisonSettings
) -> tuple[dict, list[dict], dict]:
    """Every answer for one feature and condition, its per-repeat rows and its reruns."""
    cond, ctrl = _groups(table, feature, condition), _groups(table, feature, settings.control)
    both = sorted(set(cond) & set(ctrl))
    other = sorted(set(ctrl) - set(cond))
    row: dict = {
        "feature": feature,
        "condition": condition,
        "control": settings.control,
        "fovs": int(sum(v.size for v in cond.values())),
        "control_fovs": int(sum(v.size for v in ctrl.values())),
        "repeats": "; ".join(sorted(cond)),
        "other_control_repeats": "; ".join(other),
    }
    if len(cond) == 0 or len(ctrl) == 0:
        row["note"] = "no defined value in the condition or the control"
        return row, [], {}
    cells = _cell_tests(cond, ctrl, both, other, _Seeds(settings, feature, condition))
    retests = cells.pop("retests")
    row.update(cells)
    row["permutations"] = settings.permutations
    row.update(_paired(cond, ctrl, both, scale))
    per_well = np.mean([st.effective_per_well([len(v) for v in s.values()]) for s in (cond, ctrl)])
    row["chance_low"], row["chance_high"] = (
        st.chance_without_effect(per_well, s) for s in st.TYPICAL_BETWEEN
    )
    row["note"] = (
        "test as provided withheld: the control pools repeats the condition was not imaged in"
        if other
        else ""
    )
    return row, _repeat_rows(feature, condition, cond, ctrl), retests


def _default_shuffles(column: str, settings: ComparisonSettings) -> int:
    """Return the first-pass shuffles of a p column."""
    return settings.balanced_permutations if "balanced" in column else settings.permutations


def _correct(tests: pd.DataFrame, retests: dict, settings: ComparisonSettings) -> pd.DataFrame:
    """Rerun tests at p <= 0.05 with enough shuffles, then add q-values per family."""
    for _, rows in tests.groupby("family"):
        for column in P_COLUMNS[:4]:
            default = _default_shuffles(column, settings)
            needed = st.permutations_for(int(np.isfinite(rows[column]).sum()), default)
            for index in rows.index[rows[column] <= st.ALPHA]:
                retest = retests.get((index, column))
                if retest is None or needed <= default:
                    continue
                identity = (tests.at[index, "feature"], tests.at[index, "condition"], column)
                tests.at[index, column] = retest(needed, _rng(settings, *identity, "rerun"))
                tests.at[index, f"{column}_shuffles"] = needed
        for column in P_COLUMNS:
            tests.loc[rows.index, "q" + column[1:]] = st.benjamini_hochberg(
                tests.loc[rows.index, column].to_numpy(dtype=float)
            )
    return tests


def _verdict(row: pd.Series) -> str:
    """MorphoCoverage's reading of one feature and condition."""
    screen = row.get("q_screen", np.nan) <= st.ALPHA
    repeats = row.get("q_repeats", np.nan) <= st.ALPHA
    if screen and repeats:
        return "significant across repeats"
    if screen:
        return "candidate (exploratory FOV-level screen only)"
    if repeats:
        return "consistent across repeats (paired test only)"
    if not np.isfinite(row.get("p_screen", np.nan)) and not np.isfinite(
        row.get("p_repeats", np.nan)
    ):
        return "not tested"
    return "no difference detected"


def compare_conditions(
    table: pd.DataFrame, defs: list[FeatureDef], settings: ComparisonSettings
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare every condition with the control on every tested feature and QC column.

    Parameters
    ----------
    table
        Per-FOV table (time averages), with ``condition`` and a repeat identity.
    defs
        Per-FOV feature definitions (selects the biological features).
    settings
        Control and test choices.

    Returns
    -------
    tuple of pandas.DataFrame
        The tests (one row per feature and condition, ``family`` ``features`` or ``qc``, with
        d, p, q, the screen version and the verdict) and the per-repeat descriptive table.

    Raises
    ------
    ValueError
        When the control is not in the table or is the only condition.
    """
    conditions = sorted(set(table["condition"]))
    if settings.control not in conditions:
        raise ValueError(f"The control '{settings.control}' is not a condition of the table.")
    others = [c for c in conditions if c != settings.control]
    if not others:
        raise ValueError("Only the control is in the table; nothing to compare.")
    columns = list(table.columns)
    families = {"features": tested_features(defs, columns, settings.include_axial)}
    qc = {d.name for d in defs if d.applicability == QC}
    families["qc"] = [c for c in CONFOUNDERS if c in columns and c in qc]
    rows, repeat_rows, retests = [], [], {}
    for family, features in families.items():
        for feature in features:
            scale = st.paired_scale(pd.to_numeric(table[feature], errors="coerce").to_numpy(float))
            for condition in others:
                row, reps, tests = compare_one(table, feature, condition, scale, settings)
                row["family"] = family
                retests.update({(len(rows), k): v for k, v in tests.items()})
                rows.append(row)
                repeat_rows += reps
    tests = pd.DataFrame(rows)
    for column in (*P_COLUMNS, "p_sign_flip", "unbalanced"):
        if column not in tests.columns:
            tests[column] = np.nan
    tests["screen_test"] = [_screen_version(r) for r in tests.to_dict("records")]
    tests = _correct_with_screen(tests, retests, settings)
    tests["verdict"] = [_verdict(r) for _, r in tests.iterrows()]
    return tests, pd.DataFrame(repeat_rows)


def _correct_with_screen(
    tests: pd.DataFrame, retests: dict, settings: ComparisonSettings
) -> pd.DataFrame:
    """Rerun and correct, then copy the screen's p (after reruns) and correct it too."""
    tests = _correct(tests, retests, settings)
    tests["p_screen"] = [
        r[r["screen_test"]] if r["screen_test"] else np.nan for r in tests.to_dict("records")
    ]
    for _, rows in tests.groupby("family"):
        tests.loc[rows.index, "q_screen"] = st.benjamini_hochberg(
            tests.loc[rows.index, "p_screen"].to_numpy(dtype=float)
        )
    return tests
