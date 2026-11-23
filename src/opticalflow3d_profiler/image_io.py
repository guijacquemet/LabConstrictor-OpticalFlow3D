"""Read-only TIFF and OME-TIFF access with tifffile (I/O).

:func:`inspect_tiff` reads the header only. :func:`read_frames` reads just the planes of
the requested time points, page by page, so the whole movie is never held in
memory. Calibration found in a header is returned as a *suggestion* for the user to
confirm; it is never applied silently, and missing values stay ``None``.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

import morphobricks_preprocessing as preprocessing
import numpy as np
import tifffile

from .config import Calibration, ImageSpec
from .validation import (
    InputError,
    check_axes,
    check_channel,
    raise_for_errors,
)

HASH_CHUNK = 8 * 1024 * 1024
TIME_UNIT_TO_MINUTE = {
    "nanosecond": 1 / 6e10,
    "microsecond": 1 / 6e7,
    "millisecond": 1 / 60000,
    "second": 1 / 60,
    "minute": 1.0,
    "hour": 60.0,
}
"""Minutes per OME-NGFF time unit, the names preprocessing's ``PhysicalSizes`` gives."""


@dataclass(frozen=True)
class ImageHeader:
    """What the header of a TIFF file says, without reading pixels.

    Attributes
    ----------
    path
        The file.
    shape
        Shape of the first series.
    dtype
        Pixel type name.
    header_axes
        tifffile's axis letters for the first series (``Q``/``I`` mean unknown).
    format
        ``"OME-TIFF"``, ``"ImageJ TIFF"`` or ``"TIFF"``.
    n_series
        Number of image series in the file (only the first is used).
    file_size
        Size in bytes.
    calibration_suggestion
        Calibration read from the header, to be confirmed by the user.
    notes
        Plain-language remarks about axes and calibration.
    axes_named
        Whether preprocessing's ``header_axes`` names every axis (False for a plain stack of
        pages, whose ``Y`` and ``X`` only say where rows and columns are stored).
    metadata
        Preprocessing's ``TiffMetadata`` of the file, for the experiment-wide header checks.
    """

    path: Path
    shape: tuple[int, ...]
    dtype: str
    header_axes: str
    format: str
    n_series: int
    file_size: int
    calibration_suggestion: Calibration = field(default_factory=Calibration)
    notes: tuple[str, ...] = ()
    axes_named: bool = True
    metadata: object = field(default=None, compare=False, repr=False)

    @property
    def axes_ambiguous(self) -> bool:
        """Return True unless the header names every axis, with T among them."""
        return (
            not self.axes_named
            or not set(self.header_axes) <= set("TZCYX")
            or "T" not in self.header_axes
        )


def inspect_tiff(path: Path) -> ImageHeader:
    """Read a TIFF header without loading the image, with MorphoBricks preprocessing's reader.

    Shape, pixel type, axes, series count and physical sizes come from
    ``morphobricks_preprocessing.inspect_tiff`` (contract §20, read with Z allowed); the axes
    count as named only where preprocessing's ``header_axes`` names them all. The physical
    sizes are converted to µm and minutes as a *suggestion* for the user to confirm.

    Parameters
    ----------
    path
        TIFF or OME-TIFF file.

    Returns
    -------
    ImageHeader
        Shape, type, header axes and suggested calibration.

    Raises
    ------
    InputError
        When the file does not exist or is not a readable TIFF.
    """
    path = Path(path)
    if not path.is_file():
        raise InputError(f"The file {path} does not exist.")
    meta = preprocessing.inspect_tiff(path)
    if not meta.readable:
        raise InputError(f"{path.name} could not be read as a TIFF file: {meta.error}")
    try:
        with tifffile.TiffFile(path) as tif:
            fmt = "OME-TIFF" if tif.is_ome else "ImageJ TIFF" if tif.is_imagej else "TIFF"
            unstated = _unstated_units(tif)
    except (tifffile.TiffFileError, OSError) as error:
        raise InputError(f"{path.name} could not be read as a TIFF file: {error}") from error
    calibration, notes = _calibration(meta.physical_sizes, fmt, unstated)
    header = ImageHeader(
        path=path,
        shape=tuple(int(n) for n in meta.shape),
        dtype=str(meta.dtype),
        header_axes=meta.axes,
        format=fmt,
        n_series=meta.series_count,
        file_size=path.stat().st_size,
        calibration_suggestion=calibration,
        notes=tuple(notes),
        axes_named=preprocessing.header_axes(meta) is not None,
        metadata=meta,
    )
    extra: list[str] = []
    if header.n_series > 1:
        extra.append(f"The file holds {header.n_series} image series; it will be refused.")
    if header.axes_ambiguous:
        extra.append(
            f"The header does not name all axes ({header.header_axes}); confirm the "
            "axis order before processing."
        )
    return replace(header, notes=header.notes + tuple(extra))


def _unstated_units(tif: tifffile.TiffFile) -> dict[str, str]:
    """Return the sizes a header gives without a unit, with the unit they are read in.

    OME-XML defaults (µm for ``PhysicalSize*``, s for ``TimeIncrement``) are what
    preprocessing reads; they are named so that the user sees them before confirming.
    An ImageJ ``finterval`` without ``tunit`` is listed with ``None``: it is not used.
    """
    found: dict[str, str] = {}
    if tif.is_ome and tif.ome_metadata:
        try:
            root = ET.fromstring(tif.ome_metadata)
        except ET.ParseError:
            return found
        pixels = next((el for el in root.iter() if el.tag.endswith("Pixels")), None)
        if pixels is not None:
            named = [(f"PhysicalSize{axis}", "µm") for axis in "XYZ"] + [("TimeIncrement", "s")]
            for name, unit in named:
                if pixels.get(name) is not None and pixels.get(f"{name}Unit") is None:
                    found[name] = unit
    elif tif.is_imagej:
        meta = tif.imagej_metadata or {}
        if meta.get("finterval") is not None and not str(meta.get("tunit", "")).strip():
            found["finterval"] = None
    return found


def _calibration(
    sizes: preprocessing.PhysicalSizes, fmt: str, unstated: dict[str, str | None]
) -> tuple[Calibration, list[str]]:
    """Convert preprocessing's physical sizes to a calibration suggestion, with notes."""
    notes: list[str] = []
    if fmt == "TIFF":
        return Calibration(source="none"), ["The header states no calibration."]
    xyz = [sizes.micrometers(axis) for axis in "XYZ"]
    interval = None
    if sizes.t is not None and sizes.time_unit in TIME_UNIT_TO_MINUTE:
        interval = sizes.t * TIME_UNIT_TO_MINUTE[sizes.time_unit]
    if "finterval" in unstated:
        interval = None
        notes.append(
            f"finterval={sizes.t} has no time unit in the header; enter the frame interval "
            "yourself."
        )
    defaults = [f"{n} (unit not stated: OME default {u})" for n, u in unstated.items() if u]
    if defaults:
        notes.append(
            "Units taken from the OME schema defaults: "
            + ", ".join(defaults)
            + ". Check these values before confirming."
        )
    for axis, unit in sizes.unsupported_units:
        notes.append(f"The {axis} size is given in '{unit}', which is not converted; enter it.")
    if sizes.invalid:
        notes.append(f"The header calibration cannot be used: {sizes.invalid}.")
    source = "header (OME)" if fmt == "OME-TIFF" else "header (ImageJ)"
    return Calibration(*xyz, interval, source=source), notes


def validate_image(spec: ImageSpec, header: ImageHeader) -> None:
    """Check a confirmed image interpretation against its header.

    Parameters
    ----------
    spec
        Confirmed axes.
    header
        Header of the same file.

    Raises
    ------
    InputError
        When the axes are invalid or contradict axes the header names, the file has several
        channels or series, or Y and X are not the last two axes (pages must be XY planes).
    """
    issues = check_axes(spec.axes, header.shape) + check_channel(spec.axes, header.shape)
    raise_for_errors(issues)
    if spec.axes.upper()[-2:] != "YX":
        raise InputError(
            "Y and X must be the last two axes of the file; other layouts are "
            "not supported in this version."
        )
    contradicted = named_axis_conflicts(spec.axes.strip().upper(), header.header_axes)
    if contradicted:
        raise InputError(
            f"axes_contradict_header: {header.path.name} names its axes {header.header_axes} "
            f"in its header, but {spec.axes.strip().upper()} was confirmed ({contradicted}). "
            "Every axis the header names keeps its role, even when it names only some axes or "
            "has no T (Z planes read as time points, or channels as Z, would give false "
            "velocities); confirm the header's axes or fix the file."
        )
    if header.n_series > 1:
        raise InputError(
            f"multiple_series: {header.path.name} holds {header.n_series} image series "
            "(several positions or scenes); save one field of view per file (MorphoBricks)."
        )
    if "S" in header.header_axes:
        raise InputError(
            "The file stores samples per pixel (RGB or similar planar samples); "
            "save the nuclear channel as a greyscale TIFF."
        )


def named_axis_conflicts(confirmed: str, header_axes: str) -> str:
    """Return where confirmed axes contradict the axes a header names ('' when none).

    Every position whose header letter is an axis role (``T``, ``Z``, ``C``, ``Y``, ``X``)
    must be confirmed with that letter; unknown positions (tifffile's ``Q``, ``I``) are the
    user's to confirm. A header without ``T`` (``ZCYX``) therefore cannot be read as a
    time-lapse (re-validation R3).
    """
    if len(confirmed) != len(header_axes):
        return f"{len(confirmed)} axes confirmed for {len(header_axes)} in the file"
    return ", ".join(
        f"axis {i + 1} is {named} in the header, not {given}"
        for i, (given, named) in enumerate(zip(confirmed, header_axes, strict=True))
        if named in "TZCYX" and given != named
    )


def dimensions(spec: ImageSpec, header: ImageHeader) -> dict[str, int]:
    """Return the size of each confirmed axis.

    Parameters
    ----------
    spec
        Confirmed axes.
    header
        Header of the same file.

    Returns
    -------
    dict
        Mapping from axis letter to size (``C`` only when present).
    """
    return dict(zip(spec.axes.upper(), header.shape, strict=True))


def read_frames(spec: ImageSpec, header: ImageHeader, frames: list[int]) -> np.ndarray:
    """Read selected time points of the (single-channel) video as a TZYX array.

    Parameters
    ----------
    spec
        Confirmed interpretation (validated with :func:`validate_image`).
    header
        Header of the same file.
    frames
        Source time indices to read, in the order wanted.

    Returns
    -------
    numpy.ndarray
        Array of shape ``(len(frames), Z, Y, X)`` in the file's pixel type (unchanged).
    """
    validate_image(spec, header)
    axes = spec.axes.upper()
    outer_axes, outer_shape = axes[:-2], header.shape[:-2]
    dims = dimensions(spec, header)
    planes = []
    for t in frames:
        for z in range(dims["Z"]):
            position = {"T": t, "Z": z, "C": 0}
            planes.append(np.ravel_multi_index([position[a] for a in outer_axes], outer_shape))
    with tifffile.TiffFile(header.path) as tif:
        data = tif.asarray(key=[int(p) for p in planes], series=0)
    return data.reshape(len(frames), dims["Z"], dims["Y"], dims["X"])


def file_identity(path: Path) -> dict[str, object]:
    """Return a content identity of a file (SHA-256, size, name); the file is only read.

    Parameters
    ----------
    path
        File to identify.

    Returns
    -------
    dict
        ``name``, ``size_bytes`` and ``sha256``.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            digest.update(chunk)
    return {
        "name": Path(path).name,
        "size_bytes": Path(path).stat().st_size,
        "sha256": digest.hexdigest(),
    }
