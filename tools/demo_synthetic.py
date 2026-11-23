"""Run the synthetic end-to-end demo and keep every intermediate file.

Usage::

    python tools/demo_synthetic.py OUTPUT_FOLDER [--small]

Writes images, masks, optical flow, feature tables, QC figures, PCA and comparison exports,
and ``demo_report.md`` (each expectation with PASS or FAIL). Exits with 1 if an expectation
fails. ``--small`` uses 96 x 96 images for a quick check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opticalflow3d_profiler.demo import DemoDesign, run_demo  # noqa: E402


def main() -> int:
    """Run the demo and return the exit code."""
    small = DemoDesign.small()
    checks = run_demo(Path(sys.argv[1]), small if "--small" in sys.argv else DemoDesign())
    for row in checks.rows:
        print(f"{row['result']}  {row['check']}: {row['observed']} (expected {row['expected']})")
    return 0 if checks.passed else 1


if __name__ == "__main__":
    sys.exit(main())
