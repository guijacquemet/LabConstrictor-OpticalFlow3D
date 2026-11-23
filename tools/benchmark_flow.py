"""Measure time and peak memory of one upstream ``calc_flow3D`` call.

Usage::

    python tools/benchmark_flow.py --shape 11 1840 1840            # synthetic window
    python tools/benchmark_flow.py --tiff movie.tif --axes TZYX --frame 3 [--channel 0]

Prints the wall time, the peak resident memory of this process (``ru_maxrss``) and the
profiler's estimate, so the estimate in ``flow_backend`` can be checked on real hardware.
Real-data numbers are only valid when run on the real data.
"""

from __future__ import annotations

import argparse
import resource
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opticalflow3d_profiler.config import FlowParameters, ImageSpec  # noqa: E402
from opticalflow3d_profiler.flow_backend import BYTES_PER_VOXEL_PEAK, compute_frame  # noqa: E402
from opticalflow3d_profiler.image_io import inspect_tiff, read_frames  # noqa: E402
from opticalflow3d_profiler.synthetic import SyntheticMovie, render  # noqa: E402


def load_window(args: argparse.Namespace, params: FlowParameters) -> np.ndarray:
    """Return one TZYX input window from a TIFF or a synthetic movie."""
    if args.tiff:
        spec = ImageSpec(Path(args.tiff), args.axes, args.channel)
        half = params.half_window
        frames = list(range(args.frame - half, args.frame + half + 1))
        return read_frames(spec, inspect_tiff(spec.path), frames)
    n_z, n_y, n_x = args.shape
    small = SyntheticMovie(shape=(params.window_length, n_z, 256, 256), velocity=(0, 0.3, 0.5))
    tile = render(small)
    reps = (1, 1, -(-n_y // 256), -(-n_x // 256))
    return np.ascontiguousarray(np.tile(tile, reps)[:, :, :n_y, :n_x])


def main() -> None:
    """Run the benchmark and print the measurements."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shape", type=int, nargs=3, default=(11, 512, 512))
    parser.add_argument("--tiff")
    parser.add_argument("--axes", default="")
    parser.add_argument("--channel", type=int)
    parser.add_argument("--frame", type=int, default=3)
    args = parser.parse_args()
    params = FlowParameters()
    window = load_window(args, params)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.perf_counter()
    compute_frame(window, params)
    seconds = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    voxels = int(np.prod(window.shape[1:]))
    estimate = voxels * (BYTES_PER_VOXEL_PEAK + window.shape[0] * window.itemsize)
    print(
        f"window {window.shape} {window.dtype}; {seconds:.1f} s; peak RSS {peak / 1e9:.2f} GB "
        f"(before call {before * 1024 / 1e9:.2f} GB); estimate {estimate / 1e9:.2f} GB"
    )


if __name__ == "__main__":
    main()
