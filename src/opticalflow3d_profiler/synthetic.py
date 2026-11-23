"""Synthetic nuclear time-lapses with known motion, for validation (pure).

Nuclei are anisotropic Gaussian blobs rendered analytically at sub-voxel positions, so a
known velocity gives an exact ground truth. Used by the tests and by the notebook's
validation check of the optical-flow gain.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SyntheticMovie:
    """Parameters of a synthetic movie.

    Attributes
    ----------
    shape
        ``(T, Z, Y, X)``.
    n_nuclei
        Number of blobs.
    velocity
        ``(vz, vy, vx)`` in voxels per frame, the same for every nucleus.
    sigma_xy, sigma_z
        Blob standard deviations in voxels.
    amplitude, background
        Peak height above background, and background level.
    noise_sd
        Standard deviation of additive Gaussian noise (0 for none).
    seed
        Random seed of positions and noise.
    """

    shape: tuple[int, int, int, int] = (7, 11, 96, 96)
    n_nuclei: int = 20
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    sigma_xy: float = 4.0
    sigma_z: float = 1.5
    amplitude: float = 1000.0
    background: float = 100.0
    noise_sd: float = 0.0
    seed: int = 0


def nucleus_centres(movie: SyntheticMovie) -> np.ndarray:
    """Return nucleus centres ``(z, y, x)`` at the central frame, inside a margin."""
    rng = np.random.default_rng(movie.seed)
    _, n_z, n_y, n_x = movie.shape
    margin = 3 * movie.sigma_xy
    return np.column_stack(
        [
            rng.uniform(min(2.0, n_z / 2), max(n_z - 3.0, n_z / 2), movie.n_nuclei),
            rng.uniform(margin, n_y - margin, movie.n_nuclei),
            rng.uniform(margin, n_x - margin, movie.n_nuclei),
        ]
    )


def render(movie: SyntheticMovie, dtype: str = "uint16") -> np.ndarray:
    """Render the movie as a TZYX array.

    Parameters
    ----------
    movie
        Movie parameters.
    dtype
        Output pixel type; values are rounded and clipped to its range for integers.

    Returns
    -------
    numpy.ndarray
        The movie; the central frame has the nuclei at :func:`nucleus_centres`.
    """
    n_t, n_z, n_y, n_x = movie.shape
    z, y, x = np.meshgrid(np.arange(n_z), np.arange(n_y), np.arange(n_x), indexing="ij")
    out = np.full(movie.shape, movie.background, dtype=np.float64)
    centres = nucleus_centres(movie)
    velocity = np.asarray(movie.velocity, dtype=np.float64)
    for t in range(n_t):
        for centre in centres + velocity * (t - n_t // 2):
            out[t] += movie.amplitude * np.exp(
                -((x - centre[2]) ** 2 + (y - centre[1]) ** 2) / (2 * movie.sigma_xy**2)
                - (z - centre[0]) ** 2 / (2 * movie.sigma_z**2)
            )
    if movie.noise_sd > 0:
        out += np.random.default_rng(movie.seed + 1).normal(0, movie.noise_sd, out.shape)
    if np.issubdtype(np.dtype(dtype), np.integer):
        info = np.iinfo(dtype)
        out = np.clip(np.rint(out), info.min, info.max)
    return out.astype(dtype)


def nuclear_interior(movie: SyntheticMovie, frame: np.ndarray, level: float = 0.3) -> np.ndarray:
    """Return voxels brighter than ``level`` x amplitude, away from XY borders.

    Parameters
    ----------
    movie
        Movie parameters.
    frame
        One ZYX frame of the rendered movie.
    level
        Fraction of the amplitude above background.

    Returns
    -------
    numpy.ndarray
        Boolean ZYX mask used to score recovered velocities.
    """
    mask = frame > movie.background + level * movie.amplitude
    border = int(3 * movie.sigma_xy)
    mask[:, :border] = mask[:, -border:] = False
    mask[:, :, :border] = mask[:, :, -border:] = False
    return mask
