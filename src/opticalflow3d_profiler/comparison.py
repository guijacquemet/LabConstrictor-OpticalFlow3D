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


def replicate_means(table: pd.DataFrame, feature: str) -> pd.DataFrame:
    """Average a feature over the fields of view of each biological repeat.

    Parameters
    ----------
    table
        Per-FOV table with ``condition`` and ``biological_repeat``.
    feature
        Column to average (NaN values are left out and counted).

    Returns
    -------
    pandas.DataFrame
        ``condition``, ``biological_repeat``, ``value``, ``n_fovs``, ``n_fovs_missing``.
    """
    grouped = table.groupby(["condition", "biological_repeat"], sort=True)[feature]
    out = pd.DataFrame(
        {
            "value": grouped.mean(),
            "n_fovs": grouped.count(),
            "n_fovs_missing": grouped.apply(lambda s: int(s.isna().sum())),
        }
    )
    return out.reset_index()


def hedges_g(a: np.ndarray, b: np.ndarray) -> float:
    """Return Hedges' g (bias-corrected standardised mean difference, b minus a)."""
    n_a, n_b = a.size, b.size
    if n_a < 2 or n_b < 2:
        return float("nan")
    pooled = np.sqrt(
        ((n_a - 1) * np.var(a, ddof=1) + (n_b - 1) * np.var(b, ddof=1)) / (n_a + n_b - 2)
    )
    if pooled == 0:
        return float("nan")
    correction = 1 - 3 / (4 * (n_a + n_b) - 9)
    return float((np.mean(b) - np.mean(a)) / pooled * correction)


def _paired_values(
    reps: pd.DataFrame, control: str, treatment: str
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return values paired by biological repeat; raise when pairing is incomplete."""
    wide = reps.pivot(index="biological_repeat", columns="condition", values="value")
    incomplete = wide.index[wide[[control, treatment]].isna().any(axis=1)].tolist()
    if incomplete:
        raise ValueError(
            "Paired comparison refused: biological repeat(s) "
            f"{', '.join(map(str, incomplete))} lack one of the two conditions."
        )
    return wide[control].to_numpy(), wide[treatment].to_numpy(), wide.index.tolist()


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
        True only when biological repeats are explicitly matched across conditions
        (the same ``biological_repeat`` label means the same paired experiment).

    Returns
    -------
    dict
        Repeat counts, means, SDs, difference, Hedges' g (unpaired) and the test result
        or the reason it was not run.

    Raises
    ------
    ValueError
        For an unknown condition, or a paired design with incomplete pairs.
    """
    reps = replicate_means(table, feature).dropna(subset=["value"])
    for name in (control, treatment):
        if name not in set(table["condition"]):
            raise ValueError(f"Condition '{name}' is not in the table.")
    a = reps.loc[reps["condition"] == control, "value"].to_numpy()
    b = reps.loc[reps["condition"] == treatment, "value"].to_numpy()
    out: dict[str, object] = {
        "feature": feature,
        "control": control,
        "treatment": treatment,
        "design": "paired by biological repeat" if paired else "unpaired",
        "n_repeats_control": int(a.size),
        "n_repeats_treatment": int(b.size),
        "mean_control": float(np.mean(a)) if a.size else np.nan,
        "mean_treatment": float(np.mean(b)) if b.size else np.nan,
        "sd_control": float(np.std(a, ddof=1)) if a.size > 1 else np.nan,
        "sd_treatment": float(np.std(b, ddof=1)) if b.size > 1 else np.nan,
    }
    out["difference"] = out["mean_treatment"] - out["mean_control"]
    out["hedges_g"] = hedges_g(a, b)
    if paired:
        a, b, _ = _paired_values(reps, control, treatment)
    if min(a.size, b.size) < MIN_REPEATS_FOR_TEST:
        out.update(
            test="not run",
            p_value=np.nan,
            test_note=(f"fewer than {MIN_REPEATS_FOR_TEST} biological repeats per condition"),
        )
    elif paired:
        result = stats.ttest_rel(b, a)
        out.update(
            test="paired t-test on repeat means",
            p_value=float(result.pvalue),
            test_note="assumes normally distributed paired differences",
        )
    else:
        result = stats.ttest_ind(b, a, equal_var=False)
        out.update(
            test="Welch t-test on repeat means",
            p_value=float(result.pvalue),
            test_note="assumes approximately normal repeat means",
        )
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
