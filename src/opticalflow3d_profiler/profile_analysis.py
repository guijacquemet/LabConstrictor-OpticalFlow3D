"""Exploratory PCA of per-FOV motion profiles (pure).

Inputs are chosen from the feature dictionary (biological readouts, optionally the
experimental axial ones, filtered by family); metadata and QC columns are never PCA
inputs. Constant and missing values are handled explicitly and every exclusion is
reported. PCA is a visualisation, not a test: the result carries warnings when the
number of independent biological repeats is too small to interpret it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from .feature_dictionary import FeatureDef
from .temporal_features import pca_eligible

MissingPolicy = Literal["drop_features", "drop_fovs"]
MIN_REPEATS_PER_CONDITION = 3


@dataclass(frozen=True)
class PcaSettings:
    """Choices of the PCA.

    Attributes
    ----------
    families
        Feature families to include (``magnitude``, ``components``, ``collective``,
        ``spatial``).
    include_axial
        Also include experimental axial (Z-dependent) features.
    missing
        ``"drop_features"`` removes columns with any missing value; ``"drop_fovs"``
        removes fields of view with any missing value. Nothing is imputed.
    n_components
        Maximum number of components.
    """

    families: tuple[str, ...] = ("magnitude", "components", "collective", "spatial")
    include_axial: bool = False
    missing: MissingPolicy = "drop_features"
    n_components: int = 5


@dataclass
class PreparedMatrix:
    """The standardisable feature matrix and everything excluded on the way."""

    matrix: pd.DataFrame
    metadata: pd.DataFrame
    excluded_features: list[dict[str, str]] = field(default_factory=list)
    excluded_fovs: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PcaResult:
    """PCA scores, loadings and preprocessing record."""

    scores: pd.DataFrame
    loadings: pd.DataFrame
    explained_variance_ratio: list[float]
    scaling: pd.DataFrame
    prepared: PreparedMatrix


def select_inputs(
    table: pd.DataFrame, fov_defs: list[FeatureDef], settings: PcaSettings
) -> tuple[list[str], list[dict[str, str]]]:
    """Return eligible feature columns present in ``table`` and the columns left out.

    Parameters
    ----------
    table
        Per-FOV table.
    fov_defs
        Per-FOV feature dictionary.
    settings
        PCA settings.

    Returns
    -------
    tuple
        Selected column names (dictionary order) and exclusions with reasons.
    """
    selected, excluded = [], []
    for d in fov_defs:
        if d.name not in table.columns:
            continue
        if not pca_eligible(d, settings.include_axial):
            excluded.append({"feature": d.name, "reason": f"applicability {d.applicability}"})
        elif d.family not in settings.families:
            excluded.append({"feature": d.name, "reason": f"family {d.family} not selected"})
        else:
            selected.append(d.name)
    return selected, excluded


def prepare_matrix(
    table: pd.DataFrame,
    metadata_columns: list[str],
    fov_defs: list[FeatureDef],
    settings: PcaSettings,
) -> PreparedMatrix:
    """Build the PCA input matrix with explicit, reported exclusions.

    Parameters
    ----------
    table
        Per-FOV table (metadata and feature columns), one row per ``fov_uid``.
    metadata_columns
        Columns that describe the experiment; never used as inputs.
    fov_defs
        Per-FOV feature dictionary.
    settings
        PCA settings.

    Returns
    -------
    PreparedMatrix
        Matrix indexed by ``fov_uid``, metadata, exclusions and warnings.

    Raises
    ------
    ValueError
        When ``fov_uid`` values are not unique.
    """
    if table["fov_uid"].duplicated().any():
        raise ValueError("Each field of view must appear once in the PCA table.")
    table = table.sort_values("fov_uid").set_index("fov_uid", drop=False)
    columns, excluded = select_inputs(table, fov_defs, settings)
    columns = [c for c in columns if c not in metadata_columns]
    matrix = table[columns].apply(pd.to_numeric, errors="coerce")
    matrix = matrix.replace([np.inf, -np.inf], np.nan)
    excluded_fovs: list[dict[str, str]] = []
    if settings.missing == "drop_fovs":
        incomplete = matrix.isna().any(axis=1)
        excluded_fovs = [
            {"fov_uid": u, "reason": "missing value in a selected feature"}
            for u in matrix.index[incomplete]
        ]
        matrix = matrix.loc[~incomplete]
    else:
        missing = matrix.columns[matrix.isna().any()]
        excluded += [
            {"feature": c, "reason": f"missing in {int(matrix[c].isna().sum())} FOV(s)"}
            for c in missing
        ]
        matrix = matrix.drop(columns=missing)
    constant = [c for c in matrix.columns if matrix[c].nunique(dropna=True) <= 1]
    excluded += [{"feature": c, "reason": "constant across fields of view"} for c in constant]
    matrix = matrix.drop(columns=constant)
    metadata = table.loc[matrix.index, [c for c in metadata_columns if c in table.columns]]
    prepared = PreparedMatrix(matrix, metadata, excluded, excluded_fovs)
    prepared.warnings = design_warnings(metadata, matrix.shape[1])
    return prepared


def design_warnings(metadata: pd.DataFrame, n_features: int) -> list[str]:
    """Return warnings about the experimental design behind a PCA."""
    found = ["PCA is an exploratory visualisation, not a significance test."]
    if "condition" in metadata.columns and "biological_repeat" in metadata.columns:
        repeats = metadata.groupby("condition")["biological_repeat"].nunique()
        few = repeats[repeats < MIN_REPEATS_PER_CONDITION]
        if not few.empty:
            found.append(
                "Fewer than 3 independent biological repeats in: "
                + ", ".join(f"{c} ({n})" for c, n in few.items())
                + ". Fields of view of one repeat are "
                "not independent; separation in PCA cannot be interpreted as a reproducible "
                "condition effect."
            )
    if len(metadata) <= n_features:
        found.append(
            f"{len(metadata)} fields of view for {n_features} features: components are unstable."
        )
    return found


def run_pca(prepared: PreparedMatrix, n_components: int = 5) -> PcaResult:
    """Standardise the features and compute PCA scores and loadings.

    Parameters
    ----------
    prepared
        Output of :func:`prepare_matrix`.
    n_components
        Maximum number of components.

    Returns
    -------
    PcaResult
        Scores (with metadata), loadings, explained variance and the scaling used.

    Raises
    ------
    ValueError
        With fewer than 2 fields of view or 2 features.
    """
    x = prepared.matrix
    if x.shape[0] < 2 or x.shape[1] < 2:
        raise ValueError(f"PCA needs at least 2 fields of view and 2 features; got {x.shape}.")
    scaler = StandardScaler()
    z = scaler.fit_transform(x.to_numpy(dtype=float))
    k = min(n_components, *z.shape)
    pca = PCA(n_components=k, svd_solver="full")
    scores = pca.fit_transform(z)
    names = [f"PC{i + 1}" for i in range(k)]
    score_table = pd.concat(
        [prepared.metadata.reset_index(drop=True), pd.DataFrame(scores, columns=names)], axis=1
    )
    loadings = pd.DataFrame(pca.components_.T, index=x.columns, columns=names)
    loadings.index.name = "feature"
    scaling = pd.DataFrame({"feature": x.columns, "mean": scaler.mean_, "sd": scaler.scale_})
    return PcaResult(
        score_table,
        loadings.reset_index(),
        pca.explained_variance_ratio_.tolist(),
        scaling,
        prepared,
    )


def correlation_matrix(prepared: PreparedMatrix) -> pd.DataFrame:
    """Return the Pearson correlation between the prepared features."""
    return prepared.matrix.corr()
