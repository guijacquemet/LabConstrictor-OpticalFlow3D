"""Draw the original OpticalFlow3D Profiler icon and installer images.

Usage: ``python tools/draw_icon.py`` from the repository root. Writes into ``app/logo/``:

- ``opticalflow3d_profiler_icon.png`` (256 x 256), ``.ico`` (Windows) and ``.icns`` (macOS);
- ``opticalflow3d_profiler_banner.png`` (164 x 314, installer side banner);
- ``opticalflow3d_profiler_header.png`` (150 x 57, installer header).

The motif is original: three stacked Z slices, glowing nuclei on the top slice and flow
arrows sweeping in one direction (collective nuclear motion). It reuses no OpticalFlow3D or
Janelia artwork.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon  # noqa: E402
from PIL import Image  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "app" / "logo"
NAME = "opticalflow3d_profiler"
NAVY, DEEP = "#0d1b2e", "#123a5a"
SLICE_EDGE = "#6fd3ff"
ARROW = "#3be3c4"
NUCLEUS = "#e8fbff"


def slice_polygon(cx: float, cy: float, w: float, h: float, skew: float) -> np.ndarray:
    """Return the corners of a parallelogram (one Z slice seen in perspective)."""
    return np.array(
        [
            [cx - w / 2 + skew, cy + h / 2],
            [cx + w / 2 + skew, cy + h / 2],
            [cx + w / 2 - skew, cy - h / 2],
            [cx - w / 2 - skew, cy - h / 2],
        ]
    )


def draw_motif(
    ax: plt.Axes, scale: float = 1.0, cx: float = 0.5, cy: float = 0.5, size: float = 1.0
) -> None:
    """Draw the stacked slices, three nuclei and their arrows, centred on (cx, cy)."""
    for i, (dy, alpha) in enumerate(((-0.19, 0.4), (-0.095, 0.65), (0.0, 1.0))):
        poly = slice_polygon(cx, cy + 0.04 * size + dy * size, 0.66 * size, 0.36 * size, 0.1 * size)
        ax.add_patch(
            Polygon(
                poly,
                closed=True,
                facecolor=DEEP,
                edgecolor=SLICE_EDGE,
                linewidth=3.2 * scale,
                alpha=alpha,
                zorder=1 + i,
                joinstyle="round",
            )
        )
    nuclei = [(-0.17, 0.09), (0.0, -0.03), (0.15, 0.11)]
    for dx, dy in nuclei:
        x, y = cx + dx * size, cy + (0.04 + dy) * size
        for radius, a in ((0.075, 0.14), (0.055, 0.3), (0.038, 1.0)):
            ax.add_patch(
                plt.Circle((x, y), radius * size, color=NUCLEUS, alpha=a, zorder=5, linewidth=0)
            )
        start = (x + 0.02 * size, y + 0.005 * size)
        end = (start[0] + 0.15 * size, start[1] + 0.05 * size)
        ax.add_patch(
            FancyArrowPatch(
                start,
                end,
                arrowstyle="-|>",
                mutation_scale=26 * scale * size,
                color=ARROW,
                linewidth=4.2 * scale * size,
                zorder=6,
                capstyle="round",
            )
        )


def figure(size_px: tuple[int, int], dpi: int = 100) -> tuple[plt.Figure, plt.Axes]:
    """Return a borderless figure of the requested pixel size."""
    fig = plt.figure(figsize=(size_px[0] / dpi, size_px[1] / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, size_px[0] / size_px[1])
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    fig.patch.set_alpha(0)
    return fig, ax


def background(ax: plt.Axes, x0: float, y0: float, x1: float, y1: float, rounded: bool) -> None:
    """Fill the rectangle (x0, y0)-(x1, y1) with navy (rounded corners for the icon)."""
    style = "round,pad=0,rounding_size=0.16" if rounded else "square,pad=0"
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0), x1 - x0, y1 - y0, boxstyle=style, facecolor=NAVY, edgecolor="none", zorder=0
        )
    )


def save(fig: plt.Figure, path: Path, size: tuple[int, int]) -> None:
    """Render at 4x and downsample, for smooth edges at small sizes."""
    big = path.with_suffix(".big.png")
    fig.savefig(big, dpi=fig.dpi * 4, transparent=True)
    plt.close(fig)
    Image.open(big).convert("RGBA").resize(size, Image.LANCZOS).save(path)
    big.unlink()


def main() -> None:
    """Write every image."""
    OUT.mkdir(parents=True, exist_ok=True)
    fig, ax = figure((256, 256))
    background(ax, 0.02, 0.02, 0.98, 0.98, rounded=True)
    draw_motif(ax)
    icon = OUT / f"{NAME}_icon.png"
    save(fig, icon, (256, 256))
    image = Image.open(icon)
    image.save(OUT / f"{NAME}_icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    image.save(OUT / f"{NAME}_icon.icns")

    width = 164 / 314
    fig, ax = figure((164, 314))
    background(ax, 0, 0, width, 1, rounded=False)
    draw_motif(ax, 0.55, cx=width / 2, cy=0.42, size=0.5)
    ax.text(
        width / 2,
        0.83,
        "OpticalFlow3D",
        color="white",
        ha="center",
        fontsize=11.5,
        fontweight="bold",
    )
    ax.text(width / 2, 0.76, "Profiler", color=ARROW, ha="center", fontsize=11.5, fontweight="bold")
    save(fig, OUT / f"{NAME}_banner.png", (164, 314))

    fig, ax = figure((150, 57))
    ax.add_patch(plt.Rectangle((0, 0), 150 / 57, 1, color="white", zorder=0))
    background(ax, 0.06, 0.06, 0.94, 0.94, rounded=True)
    draw_motif(ax, 0.3, cx=0.5, cy=0.5, size=0.88)
    ax.text(1.08, 0.62, "OpticalFlow3D", color=NAVY, fontsize=7.5, fontweight="bold", va="center")
    ax.text(1.08, 0.32, "Profiler", color="#0f8f7a", fontsize=7.5, fontweight="bold", va="center")
    save(fig, OUT / f"{NAME}_header.png", (150, 57))


if __name__ == "__main__":
    main()
