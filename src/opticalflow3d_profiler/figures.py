"""Matplotlib figures of images, flow fields, features, PCA and condition comparisons.

Figures only display results computed elsewhere. Conditions use a fixed categorical order
(validated palette, assigned by sorted condition name, never cycled); biological repeats
are also distinguished by marker shape so identity never relies on colour alone.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

CATEGORICAL = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
)
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")
INK, MUTED = "#0b0b0b", "#52514e"


def condition_colours(conditions: list[str]) -> dict[str, str]:
    """Return a fixed colour per condition (sorted names, first eight slots).

    Raises
    ------
    ValueError
        With more than eight conditions (split the comparison instead).
    """
    names = sorted(set(conditions))
    if len(names) > len(CATEGORICAL):
        raise ValueError("More than eight conditions cannot be told apart in one plot.")
    return dict(zip(names, CATEGORICAL, strict=False))


def _style(ax: plt.Axes) -> None:
    """Apply recessive axes styling."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED)
    ax.grid(alpha=0.2, linewidth=0.5)


def image_preview(volume: np.ndarray, z: int, title: str = "") -> Figure:
    """Show one Z slice of a ZYX volume with its raw intensity scale (no normalisation)."""
    fig, ax = plt.subplots(figsize=(5, 5))
    shown = ax.imshow(volume[z], cmap="gray", interpolation="nearest")
    fig.colorbar(shown, ax=ax, fraction=0.046, label="raw intensity")
    ax.set_title(title or f"Z slice {z}", color=INK)
    ax.set_axis_off()
    return fig


def flow_overview(
    intensity: np.ndarray,
    flow: dict[str, np.ndarray],
    z: int,
    step: int = 16,
    reliable: np.ndarray | None = None,
) -> Figure:
    """Show image with flow vectors, lateral speed and reliability of one Z slice.

    Parameters
    ----------
    intensity
        Source ZYX intensities at the flow's time point.
    flow
        ``vx``, ``vy``, ``rel`` (ZYX, upstream units).
    z
        Slice to show.
    step
        Spacing of the drawn vectors in pixels.
    reliable
        Optional boolean ZYX mask; unreliable vectors are drawn grey.
    """
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    vx, vy = flow["vx"][z], flow["vy"][z]
    yy, xx = np.mgrid[0 : vx.shape[0] : step, 0 : vx.shape[1] : step]
    sel = (slice(None, None, step), slice(None, None, step))
    axes[0].imshow(intensity[z], cmap="gray")
    ok = np.ones(vx.shape, bool) if reliable is None else reliable[z]
    axes[0].quiver(
        xx[ok[sel]],
        yy[ok[sel]],
        vx[sel][ok[sel]],
        vy[sel][ok[sel]],
        np.arctan2(vy[sel], vx[sel])[ok[sel]],
        cmap="twilight",
        angles="xy",
        pivot="mid",
    )
    if not ok.all():
        bad = ~ok[sel]
        axes[0].quiver(
            xx[bad],
            yy[bad],
            vx[sel][bad],
            vy[sel][bad],
            color="#9a9a9a",
            angles="xy",
            pivot="mid",
            alpha=0.6,
        )
    axes[0].set_title("Flow vectors (colour = direction, y down)")
    speed = axes[1].imshow(np.hypot(vx, vy), cmap="Blues")
    fig.colorbar(speed, ax=axes[1], fraction=0.046, label="XY speed (px/frame)")
    axes[1].set_title("XY optical-flow speed")
    rel = axes[2].imshow(np.log10(np.maximum(flow["rel"][z], 1e-12)), cmap="Greys")
    fig.colorbar(rel, ax=axes[2], fraction=0.046, label="log10 reliability")
    axes[2].set_title("Reliability")
    for ax in axes:
        ax.set_axis_off()
    return fig


def feature_histograms(table: pd.DataFrame, columns: list[str], units: str = "") -> Figure:
    """Histogram of a few per-frame features (NaN values left out and counted)."""
    fig, axes = plt.subplots(1, len(columns), figsize=(4 * len(columns), 3.2), squeeze=False)
    for ax, column in zip(axes[0], columns, strict=True):
        values = pd.to_numeric(table[column], errors="coerce")
        ax.hist(values.dropna(), bins=20, color=CATEGORICAL[0], edgecolor="white")
        ax.set_title(f"{column}\n({int(values.isna().sum())} undefined)", fontsize=9)
        ax.set_xlabel(units)
        _style(ax)
    fig.tight_layout()
    return fig


def _scatter_groups(ax: plt.Axes, table: pd.DataFrame, x: str, y: str, size: float) -> None:
    """Scatter points coloured by condition and shaped by biological repeat."""
    colours = condition_colours(table["condition"].tolist())
    repeats = sorted(table["biological_repeat"].unique())
    for (condition, repeat), group in table.groupby(["condition", "biological_repeat"]):
        ax.scatter(
            group[x],
            group[y],
            s=size,
            color=colours[condition],
            marker=MARKERS[repeats.index(repeat) % len(MARKERS)],
            edgecolor="white",
            linewidth=1,
            label=f"{condition} / {repeat}",
        )


def pca_scatter(scores: pd.DataFrame, explained: list[float]) -> Figure:
    """PC1 against PC2, coloured by condition, marker per biological repeat."""
    fig, ax = plt.subplots(figsize=(6.5, 5))
    _scatter_groups(ax, scores, "PC1", "PC2", 60)
    ax.set_xlabel(f"PC1 ({explained[0]:.0%} of variance)")
    ax.set_ylabel(f"PC2 ({explained[1]:.0%} of variance)")
    ax.set_title("Exploratory PCA of FOV motion profiles", color=INK)
    ax.legend(
        title="condition / biological repeat",
        fontsize=8,
        frameon=False,
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
    )
    _style(ax)
    fig.tight_layout()
    return fig


def pca_loadings(loadings: pd.DataFrame, component: str = "PC1", top: int = 15) -> Figure:
    """Horizontal bars of the largest absolute loadings of one component."""
    data = loadings.reindex(loadings[component].abs().sort_values().index)[-top:]
    fig, ax = plt.subplots(figsize=(7, 0.3 * len(data) + 1.2))
    ax.barh(data["feature"], data[component], color=CATEGORICAL[0], height=0.6)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_title(f"Top {len(data)} loadings of {component}", color=INK)
    ax.tick_params(axis="y", labelsize=7)
    _style(ax)
    fig.tight_layout()
    return fig


def correlation_heatmap(corr: pd.DataFrame) -> Figure:
    """Pearson correlation between PCA input features (diverging, neutral at 0)."""
    n = len(corr)
    fig, ax = plt.subplots(figsize=(0.18 * n + 3, 0.18 * n + 2.5))
    shown = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(n), corr.columns, rotation=90, fontsize=5)
    ax.set_yticks(range(n), corr.index, fontsize=5)
    fig.colorbar(shown, ax=ax, fraction=0.03, label="Pearson r")
    ax.set_title("Feature correlation", color=INK)
    fig.tight_layout()
    return fig


def condition_plot(table: pd.DataFrame, feature: str, label: str, unit: str = "") -> Figure:
    """Fields of view (small) and biological-repeat means (large) per condition."""
    fig, ax = plt.subplots(figsize=(4.5, 4))
    conditions = sorted(table["condition"].unique())
    colours = condition_colours(conditions)
    repeats = sorted(table["biological_repeat"].unique())
    rng = np.random.default_rng(0)
    for i, condition in enumerate(conditions):
        sub = table[table["condition"] == condition]
        values = pd.to_numeric(sub[feature], errors="coerce")
        ax.scatter(
            i + rng.uniform(-0.12, 0.12, len(sub)),
            values,
            s=14,
            color=colours[condition],
            alpha=0.45,
            linewidth=0,
        )
        means = values.groupby(sub["biological_repeat"]).mean()
        for repeat, mean in means.items():
            ax.scatter(
                i + 0.28,
                mean,
                s=70,
                color=colours[condition],
                edgecolor="white",
                marker=MARKERS[repeats.index(repeat) % len(MARKERS)],
                zorder=3,
            )
        ax.hlines(means.mean(), i - 0.2, i + 0.4, color=INK, linewidth=2)
    ax.set_xticks(range(len(conditions)), conditions)
    ax.set_ylabel(f"{feature}" + (f" ({unit})" if unit else ""), fontsize=8)
    ax.set_title(f"{label}\nsmall: FOVs; large: repeat means; bar: mean of repeats", fontsize=9)
    _style(ax)
    fig.tight_layout()
    return fig


def time_montage(planes: list[np.ndarray], titles: list[str], title: str) -> Figure:
    """Show one Z slice at every time point, on one shared raw-intensity scale."""
    n = len(planes)
    cols = min(n, 5)
    rows = -(-n // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3 * cols, 3 * rows), squeeze=False)
    low = min(float(p.min()) for p in planes)
    high = max(float(p.max()) for p in planes)
    for ax in axes.ravel():
        ax.set_axis_off()
    for ax, plane, label in zip(axes.ravel(), planes, titles, strict=False):
        ax.imshow(plane, cmap="gray", vmin=low, vmax=high, interpolation="nearest")
        ax.set_title(label, fontsize=9)
    fig.suptitle(title, color=INK)
    fig.tight_layout()
    return fig


def foreground_overlay(intensity: np.ndarray, foreground: np.ndarray, z: int, title: str) -> Figure:
    """Show the raw slice next to the foreground outline used for the features."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].imshow(intensity[z], cmap="gray")
    axes[0].set_title("Raw intensity")
    axes[1].imshow(intensity[z], cmap="gray")
    axes[1].contour(
        foreground[z].astype(float), levels=[0.5], colors=[CATEGORICAL[1]], linewidths=1
    )
    axes[1].set_title(f"Foreground outline ({foreground[z].mean():.1%} of slice)")
    for ax in axes:
        ax.set_axis_off()
    fig.suptitle(title, color=INK)
    return fig


def feature_timeseries(frames: pd.DataFrame, columns: list[str], time: str) -> Figure:
    """Plot per-frame features of one field of view against time (one panel each)."""
    fig, axes = plt.subplots(1, len(columns), figsize=(4 * len(columns), 3), squeeze=False)
    for ax, column in zip(axes[0], columns, strict=True):
        ax.plot(
            frames[time],
            pd.to_numeric(frames[column], errors="coerce"),
            "o-",
            color=CATEGORICAL[0],
            linewidth=2,
            markersize=6,
        )
        ax.set_title(column, fontsize=9)
        ax.set_xlabel(time)
        _style(ax)
    fig.tight_layout()
    return fig


def save(fig: Figure, path: Path, dpi: int = 300) -> None:
    """Save a figure as PNG through a temporary file, then close it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp.png")
    fig.savefig(tmp, dpi=dpi, bbox_inches="tight")
    tmp.replace(path)
    plt.close(fig)
