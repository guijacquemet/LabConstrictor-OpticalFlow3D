"""The tests of the condition comparison, following MorphoCoverage's rules (pure).

Reimplemented from MorphoCoverage (``statistics.cohen_d``, ``sampling_unit.contrast_cells``,
``sampling_unit._balanced``, ``sampling_unit._cell_chance``, the paired test of
``sampling_unit.contrast_repeats``; MIT licence, CellMigrationLab; commit recorded in
``docs/morphobricks.md``). MorphoCoverage is not a dependency. Here the observation is the
field of view (its time-averaged profile), where MorphoCoverage's is usually the cell.

- :func:`cohen_d`: the pooled-SD Cohen's d of the lab's Plot&Stats notebook.
- :func:`randomization`: Cohen's d with a randomization test shuffling the condition labels
  over the observations, ``p = (extreme + 1) / (B + 1)`` (the exploratory screen).
- :func:`balanced`: the balanced permutation test: the median d over draws taking the same
  number of observations from every repeat, its null shuffling labels within each repeat.
- :func:`paired_repeats`: the paired t-test on the repeat means (log ratios when every
  observation of the feature is positive, else differences), the biological repeat as the
  replicate; :func:`sign_flip`: the exact sign-flip test, from 6 repeats.
- :func:`benjamini_hochberg`, :func:`permutations_for` and :func:`chance_without_effect`.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats

ALPHA = 0.05
BALANCED_DRAWS = 100
MIN_PAIRED_REPEATS = 3
MIN_SIGN_FLIP_REPEATS = 6
TYPICAL_BETWEEN = (0.25, 0.5)
_TOLERANCE = 1e-12


def _spread_is_zero(sd: float, values: np.ndarray) -> bool:
    """Return whether an SD is zero up to rounding of the values' scale."""
    scale = float(np.max(np.abs(values))) if values.size else 0.0
    return sd <= 1e-12 * max(scale, 1e-300)


def cohen_d(first: np.ndarray, second: np.ndarray) -> float:
    """Cohen's d with the pooled sample variance, ``(mean(first) - mean(second)) / sd``.

    NaN when a side has fewer than two values or the pooled SD is zero up to rounding.
    """
    n1, n2 = len(first), len(second)
    if n1 < 2 or n2 < 2:
        return float("nan")
    pooled = ((n1 - 1) * np.var(first, ddof=1) + (n2 - 1) * np.var(second, ddof=1)) / (n1 + n2 - 2)
    sd = math.sqrt(max(float(pooled), 0.0))
    if _spread_is_zero(sd, np.concatenate([first, second])):
        return float("nan")
    return float((np.mean(first) - np.mean(second)) / sd)


def _null_d(pooled: np.ndarray, sides: np.ndarray, n: int) -> np.ndarray:
    """Cohen's d of each labelling (rows of ``sides``: the treated positions)."""
    size = len(pooled)
    first = pooled[sides]
    rest_sum = pooled.sum() - first.sum(axis=1)
    rest_sq = (pooled**2).sum() - (first**2).sum(axis=1)
    m1, m2 = first.mean(axis=1), rest_sum / (size - n)
    ss1 = ((first - m1[:, None]) ** 2).sum(axis=1)
    ss2 = rest_sq - rest_sum**2 / (size - n)
    pooled_var = (ss1 + ss2) / (size - 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.abs(m1 - m2) / np.sqrt(pooled_var)


def randomization(
    treated: np.ndarray, control: np.ndarray, n_permutations: int, rng: np.random.Generator
) -> tuple[float, float]:
    """Return ``(d, p)``: Cohen's d and the randomization p over the observations.

    The labels are shuffled over the pooled observations; ``p = (extreme + 1) / (B + 1)``,
    where a labelling is extreme when its |d| is at least the observed |d|.
    """
    d = cohen_d(treated, control)
    if not np.isfinite(d):
        return d, float("nan")
    pooled = np.concatenate([treated, control])
    pooled = pooled - pooled.mean()
    n, extreme = len(treated), 0
    block = max(1, 2_000_000 // len(pooled))
    for start in range(0, n_permutations, block):
        keys = rng.random((min(block, n_permutations - start), len(pooled)))
        sides = np.argpartition(keys, n - 1, axis=1)[:, :n]
        null = _null_d(pooled, sides, n)
        extreme += int(np.sum(~(null < abs(d) - _TOLERANCE)))
    return d, (extreme + 1) / (n_permutations + 1)


def _draws(sizes: list[int], keep: int, rng: np.random.Generator) -> list[np.ndarray]:
    """Per repeat, the ``(draws, keep)`` positions each draw takes (all when it holds keep)."""
    if all(n == keep for n in sizes):
        return [np.arange(n)[None, :] for n in sizes]
    return [np.argsort(rng.random((BALANCED_DRAWS, n)), axis=1)[:, :keep] for n in sizes]


def _balanced_d(
    pools: list[np.ndarray], n_treated: list[int], draws: tuple[list, list], normalise: bool
) -> float:
    """Return the median Cohen's d over the draws of one labelling (pools: treated first)."""
    a_parts, b_parts = [], []
    for pool, n_t, take_a, take_b in zip(pools, n_treated, draws[0], draws[1], strict=True):
        values = pool / pool[n_t:].mean() if normalise else pool
        a_parts.append(values[:n_t][take_a])
        b_parts.append(values[n_t:][take_b])
    width = max(len(a_parts[0]), len(b_parts[0]))
    a = np.concatenate([np.broadcast_to(p, (width, p.shape[1])) for p in a_parts], axis=1)
    b = np.concatenate([np.broadcast_to(p, (width, p.shape[1])) for p in b_parts], axis=1)
    values = _row_d(a, b)
    finite = values[np.isfinite(values)]
    return float(np.median(finite)) if finite.size else float("nan")


def _row_d(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cohen's d of each row pair (as :func:`cohen_d`, NaN without spread)."""
    n1, n2 = a.shape[1], b.shape[1]
    pooled = ((n1 - 1) * a.var(axis=1, ddof=1) + (n2 - 1) * b.var(axis=1, ddof=1)) / (n1 + n2 - 2)
    sd = np.sqrt(np.maximum(pooled, 0.0))
    scale = np.maximum(np.abs(a).max(axis=1), np.abs(b).max(axis=1))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = (a.mean(axis=1) - b.mean(axis=1)) / sd
    return np.where(sd > 1e-12 * np.maximum(scale, 1e-300), d, np.nan)


def balanced(
    treated: list[np.ndarray],
    control: list[np.ndarray],
    n_permutations: int,
    rng: np.random.Generator,
    normalise: bool = False,
) -> tuple[float, float, int, int]:
    """Run the balanced permutation test over repeats (one array per repeat and side).

    Returns
    -------
    tuple
        ``(d, p, kept per repeat on the treated side, kept on the control side)``: d is the
        median Cohen's d over :data:`BALANCED_DRAWS` draws taking the fewest observations
        any repeat holds on each side; p shuffles the labels within each repeat, the same
        draws for every labelling. ``normalise`` divides each repeat by the mean of its
        control as labelled. NaN when a repeat holds fewer than 2 on a side.
    """
    keep_t, keep_c = min(len(t) for t in treated), min(len(c) for c in control)
    if keep_t < 2 or keep_c < 2:
        return float("nan"), float("nan"), keep_t, keep_c
    pools = [np.concatenate([t, c]) for t, c in zip(treated, control, strict=True)]
    sizes = [len(t) for t in treated]
    draws = (_draws(sizes, keep_t, rng), _draws([len(c) for c in control], keep_c, rng))
    observed = _balanced_d(pools, sizes, draws, normalise)
    if not np.isfinite(observed):
        return observed, float("nan"), keep_t, keep_c
    extreme = 0
    for _ in range(n_permutations):
        shuffled = [pool[rng.permutation(len(pool))] for pool in pools]
        null = _balanced_d(shuffled, sizes, draws, normalise)
        extreme += int(not abs(null) < abs(observed) - _TOLERANCE)
    return observed, (extreme + 1) / (n_permutations + 1), keep_t, keep_c


def permutations_for(family_size: int, default: int, alpha: float = ALPHA) -> int:
    """Shuffles for a rerun so that the smallest reachable q, ``K / (B + 1)``, is < alpha."""
    return max(int(default), int(np.ceil(family_size / alpha)))


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Return Benjamini-Hochberg q-values over the finite p-values (NaN stays NaN)."""
    p = np.asarray(p_values, dtype=float)
    q = np.full(p.shape, np.nan)
    ok = np.flatnonzero(np.isfinite(p))
    if ok.size == 0:
        return q
    order = ok[np.argsort(p[ok])]
    ranked = p[order] * ok.size / np.arange(1, ok.size + 1)
    q[order] = np.minimum(1.0, np.minimum.accumulate(ranked[::-1])[::-1])
    return q


def paired_scale(values: np.ndarray) -> str:
    """``"log ratio"`` when every observation of a feature is positive, else ``"difference"``.

    Chosen once per feature from all its observations, the same for every condition.
    """
    finite = values[np.isfinite(values)]
    return "log ratio" if finite.size and bool(np.all(finite > 0)) else "difference"


def paired_repeats(
    condition_means: np.ndarray, control_means: np.ndarray, scale: str
) -> tuple[float, float, str]:
    """Run the paired t-test on repeat means: ``(mean change, p, note)``.

    The change per repeat is ``log(mean(condition) / mean(control))`` or the difference;
    the reported change is the mean of those (a fold change ``exp`` of it for log ratios).
    """
    if scale == "log ratio":
        changes = np.log(condition_means / control_means)
    else:
        changes = condition_means - control_means
    changes = changes[np.isfinite(changes)]
    if changes.size < MIN_PAIRED_REPEATS:
        return float("nan"), float("nan"), f"fewer than {MIN_PAIRED_REPEATS} repeats hold both"
    mean = float(np.mean(changes))
    if _spread_is_zero(float(np.std(changes, ddof=1)), changes):
        return mean, float("nan"), "the repeats' changes do not vary (degenerate test)"
    return mean, float(stats.ttest_1samp(changes, 0.0).pvalue), ""


def sign_flip(changes: np.ndarray) -> float:
    """Return the exact two-sided sign-flip p of the mean change (NaN below 6 repeats)."""
    changes = changes[np.isfinite(changes)]
    if changes.size < MIN_SIGN_FLIP_REPEATS:
        return float("nan")
    observed = abs(float(np.mean(changes)))
    signs = np.array(list(itertools.product((1.0, -1.0), repeat=changes.size)))
    null = np.abs(signs @ changes) / changes.size
    return float(np.mean(~(null < observed - _TOLERANCE)))


def effective_per_well(sizes: list[int]) -> float:
    """Effective observations per repeat, ``sum(n²) / sum(n)`` (each weighted by its share)."""
    total = sum(sizes)
    return sum(n * n for n in sizes) / total if total else float("nan")


def chance_without_effect(per_well: float, between_sd: float, alpha: float = ALPHA) -> float:
    """Return the FOV-level test's chance of ``p <= alpha`` without an effect.

    When the difference varies between repeats by ``between_sd`` observation SDs, the
    variance of the mean difference is ``k = 1 + n s² / 2`` times what the test assumes, so
    it rejects in about ``2 P(Z > z_(alpha/2) / sqrt(k))`` of experiments.
    """
    z = stats.norm.isf(alpha / 2)
    k = 1 + per_well * between_sd**2 / 2
    return float(2 * stats.norm.sf(z / math.sqrt(k)))
