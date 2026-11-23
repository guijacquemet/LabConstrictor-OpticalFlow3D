"""Progress bars for long steps: fields of view, optical-flow windows, features (UI helper).

The pipeline reports progress to a :class:`Tracker`. It opens one *stage* per loop (the
fields of view of a run, the optical-flow time windows of one field of view, its feature
frames) and advances it after each item. :class:`NullTracker` (the default) shows nothing;
:class:`TqdmTracker` draws ``tqdm.auto`` bars, a widget in Jupyter and Colab and text
elsewhere, each with the items done, the elapsed time and the estimated time left. The
bars only display: they never change a number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tqdm.auto import tqdm


class Stage:
    """One loop's progress (no display)."""

    def update(self, note: str = "") -> None:
        """Advance by one item; ``note`` describes the item just finished."""

    def close(self) -> None:
        """Finish the stage."""


class Tracker:
    """Where the pipeline reports progress; this base class displays nothing."""

    def stage(self, description: str, total: int, nested: bool = False) -> Stage:
        """Open a stage of ``total`` items (``nested``: inside the current outer stage)."""
        del description, total, nested
        return Stage()


NullTracker = Tracker


class _TqdmStage(Stage):
    """A stage drawn by one tqdm bar."""

    def __init__(self, bar: tqdm) -> None:
        self.bar = bar

    def update(self, note: str = "") -> None:
        """Advance the bar and show the item just finished."""
        if note:
            self.bar.set_postfix_str(note, refresh=False)
        self.bar.update(1)

    def close(self) -> None:
        """Close the bar (it stays visible with its final count and time)."""
        self.bar.close()


class TqdmTracker(Tracker):
    """Draw every stage as a ``tqdm.auto`` progress bar (elapsed time and time left)."""

    def stage(self, description: str, total: int, nested: bool = False) -> Stage:
        """Open a bar; a nested bar disappears when done, an outer one stays."""
        from tqdm.auto import tqdm

        bar = tqdm(
            total=total,
            desc=description,
            unit="item" if not nested else "step",
            leave=not nested,
            dynamic_ncols=True,
        )
        return _TqdmStage(bar)
