"""Compare conditions on a few interpretable readouts (pure).

Fields of view are first averaged within each biological repeat; the condition effect is
estimated between repeats, never between fields of view. A test is run only when the
design supports it (at least 3 repeats per condition; pairing only when declared and
complete). The output always carries the effect size and variability, whether or not a
test is run.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

MIN_REPEATS_FOR_TEST = 3

READOUTS = {
    "median motion magnitude": "speed_xy_median__tmean",
    "upper-tail motion magnitude": "speed_xy_p90__tmean",
    "directional coherence": "coherence_xy_global__tmean",
    "spatial heterogeneity": "regional_speed_cv__tmean",
    "temporal variation": "speed_xy_median__tsd",
}
"""Default readouts (XY speed mode); ``speed_3d`` replaces ``speed_xy`` in XYZ mode."""

CONFOUNDERS = (
    "qc_foreground_intensity_mean__tmean",
    "qc_foreground_fraction__tmean",
    "qc_object_mean_voxels__tmean",
    "qc_object_mean_z_extent__tmean",
    "qc_reliable_fraction__tmean",
    "qc_reliability_threshold__tmean",
)
"""QC columns compared alongside the readouts as potential confounders."""


def repeat_column(table: pd.DataFrame) -> str:
    """Return the column that identifies independent biological repeats.

    ``repeat_id`` (written by :func:`~opticalflow3d_profiler.analysis.load_runs`, which
    scopes labels to their run unless they are declared shared) takes precedence over the raw
    ``biological_repeat`` label.
    """
    return "repeat_id" if "repeat_id" in table.columns else "biological_repeat"


def replicate_means(table: pd.DataFrame, feature: str) -> pd.DataFrame:
    """Average a feature over the fields of view of each biological repeat.

    Parameters
    ----------
    table
        Per-FOV table with ``condition`` and a repeat identity (:func:`repeat_column`).
    feature
        Column to average (NaN values are left out and counted).

    Returns
    -------
    pandas.DataFrame
        ``condition``, ``repeat``, ``value`` (NaN when every FOV is missing), ``n_fovs``
        (defined values) and ``n_fovs_missing``.
    """
    values = pd.to_numeric(table[feature], errors="coerce")
    keys = [table["condition"], table[repeat_column(table)].rename("repeat")]
    grouped = values.groupby(keys, sort=True)
    out = pd.DataFrame(
        {
            "value": grouped.mean(),
            "n_fovs": grouped.count(),
            "n_fovs_missing": grouped.apply(lambda v: int(v.isna().sum())),
        }
    )
    return out.reset_index()


def hedges_g(a: np.ndarray, b: np.ndarray) -> tuple[float, str]:
    """Return Hedges' g (b minus a, bias corrected) and the reason when it is undefined."""
    n_a, n_b = a.size, b.size
    if n_a < 2 or n_b < 2:
        return float("nan"), "fewer than 2 repeats in a condition"
    pooled = np.sqrt(
        ((n_a - 1) * np.var(a, ddof=1) + (n_b - 1) * np.var(b, ddof=1)) / (n_a + n_b - 2)
    )
    if pooled == 0:
        return float("nan"), "no variation between repeats within either condition"
    correction = 1 - 3 / (4 * (n_a + n_b) - 9)
    return float((np.mean(b) - np.mean(a)) / pooled * correction), ""


def _paired_values(
    reps: pd.DataFrame, control: str, treatment: str
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return defined values paired by repeat, and the repeats left out for missing values.

    Only the two compared conditions are considered.

    Raises
    ------
    ValueError
        When a repeat of one condition has no counterpart in the other.
    """
    two = reps[reps["condition"].isin([control, treatment])]
    wide = two.pivot(index="repeat", columns="condition", values="value")
    present = two.pivot(index="repeat", columns="condition", values="n_fovs_missing")
    unmatched = present.index[present.reindex(columns=[control, treatment]).isna().any(axis=1)]
    if len(unmatched):
        raise ValueError(
            "Paired comparison refused: repeat(s) "
            f"{', '.join(map(str, unmatched))} lack one of the two conditions."
        )
    missing = wide.index[wide[[control, treatment]].isna().any(axis=1)].tolist()
    wide = wide.drop(index=missing)
    return wide[control].to_numpy(), wide[treatment].to_numpy(), [str(m) for m in missing]


def _test(a: np.ndarray, b: np.ndarray, paired: bool) -> dict[str, object]:
    """Run the design's t-test on repeat means, or say why it was not run or is degenerate."""
    if min(a.size, b.size) < MIN_REPEATS_FOR_TEST:
        return {
            "test": "not run",
            "p_value": np.nan,
            "test_note": f"fewer than {MIN_REPEATS_FOR_TEST} biological repeats per condition",
        }
    if paired:
        name, note = "paired t-test on repeat means", "assumes normal paired differences"
        degenerate = np.ptp(b - a) == 0
        result = None if degenerate else stats.ttest_rel(b, a)
    else:
        name, note = "Welch t-test on repeat means", "assumes approximately normal repeat means"
        degenerate = np.ptp(a) == 0 or np.ptp(b) == 0
        result = None if degenerate else stats.ttest_ind(b, a, equal_var=False)
    if result is None or not np.isfinite(result.statistic) or not np.isfinite(result.pvalue):
        return {
            "test": f"{name}: not interpretable",
            "p_value": np.nan,
            "test_note": "zero variance between repeats (degenerate test)",
        }
    return {"test": name, "p_value": float(result.pvalue), "test_note": note}


def compare(
    table: pd.DataFrame, feature: str, control: str, treatment: str, paired: bool = False
) -> dict[str, object]:
    """Compare two conditions on one per-FOV feature, at the biological-repeat level.

    Parameters
    ----------
    table
        Per-FOV table.
    feature
        Feature column.
    control, treatment
        Condition names.
    paired
        True only when biological repeats are explicitly matched across conditions (the
        same repeat identity means the same paired experiment).

    Returns
    -------
    dict
        Repeat and FOV counts, repeats left out (all FOVs missing), means, SDs,
        difference, Hedges' g with its undefined reason, and the test result or the reason
        it was not run or is not interpretable.

    Raises
    ------
    ValueError
        For an unknown condition, or a paired design with unmatched repeats.
    """
    for name in (control, treatment):
        if name not in set(table["condition"]):
            raise ValueError(f"Condition '{name}' is not in the table.")
    all_reps = replicate_means(table, feature)
    reps = all_reps[all_reps["condition"].isin([control, treatment])]
    dropped = reps[reps["value"].isna()]
    defined = reps.dropna(subset=["value"])
    a = defined.loc[defined["condition"] == control, "value"].to_numpy()
    b = defined.loc[defined["condition"] == treatment, "value"].to_numpy()
    out: dict[str, object] = {
        "feature": feature,
        "control": control,
        "treatment": treatment,
        "design": "paired by biological repeat" if paired else "unpaired",
        "n_repeats_control": int(a.size),
        "n_repeats_treatment": int(b.size),
        "n_fovs_used": int(defined["n_fovs"].sum()),
        "n_fovs_missing": int(reps["n_fovs_missing"].sum()),
        "repeats_excluded": "; ".join(
            f"{r.condition}/{r.repeat}: all FOVs missing" for r in dropped.itertuples()
        ),
        "mean_control": float(np.mean(a)) if a.size else np.nan,
        "mean_treatment": float(np.mean(b)) if b.size else np.nan,
        "sd_control": float(np.std(a, ddof=1)) if a.size > 1 else np.nan,
        "sd_treatment": float(np.std(b, ddof=1)) if b.size > 1 else np.nan,
    }
    out["difference"] = out["mean_treatment"] - out["mean_control"]
    out["hedges_g"], out["hedges_g_note"] = hedges_g(a, b)
    if paired:
        a, b, missing = _paired_values(reps, control, treatment)
        if missing:
            out["repeats_excluded"] = "; ".join(
                filter(
                    None,
                    [
                        out["repeats_excluded"],
                        f"pairs left out (missing value): {', '.join(missing)}",
                    ],
                )
            )
    out.update(_test(a, b, paired))
    return out


def readouts_for(columns: list[str]) -> dict[str, str]:
    """Return the default readouts available in a table, adapting to the speed mode."""
    out = {}
    for label, column in READOUTS.items():
        if column not in columns:
            column = column.replace("speed_xy", "speed_3d")
        if column in columns:
            out[label] = column
    return out


def compare_all(
    table: pd.DataFrame, control: str, treatment: str, paired: bool = False
) -> pd.DataFrame:
    """Compare the default readouts and the confounder QC columns.

    Returns
    -------
    pandas.DataFrame
        One row per readout or confounder, with a ``role`` column.
    """
    rows = []
    for label, column in readouts_for(list(table.columns)).items():
        rows.append(
            {
                "role": "readout",
                "readout": label,
                **compare(table, column, control, treatment, paired),
            }
        )
    for column in CONFOUNDERS:
        if column in table.columns and table[column].notna().any():
            rows.append(
                {
                    "role": "potential confounder",
                    "readout": column,
                    **compare(table, column, control, treatment, paired),
                }
            )
    return pd.DataFrame(rows)
