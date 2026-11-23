"""OpticalFlow3D Profiler: nuclear-motion profiles from 3D optical flow.

The numerical engine is the unchanged OpticalFlow3D implementation in ``_upstream``.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:  # the installed release version (setup.py, set at every release by bump_version.py)
    __version__ = version("opticalflow3d_profiler")
except PackageNotFoundError:  # a source checkout that is not installed
    __version__ = "0+unknown"

__all__ = ["__version__"]
