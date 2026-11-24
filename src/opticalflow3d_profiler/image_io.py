"""Read-only TIFF and OME-TIFF access with tifffile (I/O).

:func:`inspect_tiff` reads the header only. :func:`read_frames` reads just the planes of
the requested time points, page by page, so the whole movie is never held in
memory. Calibration found in a header is returned as a *suggestion* for the user to
confirm; it is never applied silently, and missing values stay ``None``.
"""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import tifffile

from .config import Calibration, ImageSpec
from .validation import (
    LENGTH_TO_MICROMETRE,
    TIME_TO_MINUTE,
    InputError,
    check_axes,
    check_channel,
    raise_for_errors,
)

HASH_CHUNK = 8 * 1024 * 1024


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

    @property
    def axes_ambiguous(self) -> bool:
        """Return True when the header does not name every axis with T, Z, C, Y or X."""
        return not set(self.header_axes) <= set("TZCYX") or "T" not in self.header_axes


def inspect_tiff(path: Path) -> ImageHeader:
    """Read a TIFF header without loading the image.

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
    try:
        with tifffile.TiffFile(path) as tif:
            series = tif.series[0]
            fmt = "OME-TIFF" if tif.is_ome else "ImageJ TIFF" if tif.is_imagej else "TIFF"
            calibration, notes = _header_calibration(tif)
            header = ImageHeader(
                path=path,
                shape=tuple(int(n) for n in series.shape),
                dtype=str(series.dtype),
                header_axes=str(series.axes),
                format=fmt,
                n_series=len(tif.series),
                file_size=path.stat().st_size,
                calibration_suggestion=calibration,
                notes=tuple(notes),
            )
    except (tifffile.TiffFileError, OSError) as error:
        raise InputError(f"{path.name} could not be read as a TIFF file: {error}") from error
    extra: list[str] = []
    if header.n_series > 1:
        extra.append(f"The file holds {header.n_series} image series; it will be refused.")
    if header.axes_ambiguous:
        extra.append(
            f"The header does not name all axes ({header.header_axes}); confirm the "
            "axis order before processing."
        )
    return ImageHeader(**{**header.__dict__, "notes": header.notes + tuple(extra)})


def _header_calibration(tif: tifffile.TiffFile) -> tuple[Calibration, list[str]]:
    """Return the calibration stated in an OME or ImageJ header, with notes."""
    if tif.is_ome and tif.ome_metadata:
        return _ome_calibration(tif.ome_metadata)
    if tif.is_imagej and tif.imagej_metadata is not None:
        return _imagej_calibration(tif)
    return Calibration(source="none"), ["The header states no calibration."]


def _ome_calibration(xml_text: str) -> tuple[Calibration, list[str]]:
    """Read PhysicalSize and TimeIncrement of the first OME image.

    A missing unit takes the OME schema's default (µm for sizes, s for the time increment),
    as MorphoBricks preprocessing reads it; every value read this way is named in a note, so
    the user sees it before confirming the calibration.
    """
    root = ET.fromstring(xml_text)
    pixels = next((el for el in root.iter() if el.tag.endswith("Pixels")), None)
    if pixels is None:
        return Calibration(source="none"), ["The OME header has no Pixels element."]
    notes: list[str] = []
    sizes = []
    for axis in "XYZ":
        sizes.append(
            _scaled(
                pixels.get(f"PhysicalSize{axis}"),
                pixels.get(f"PhysicalSize{axis}Unit", "µm"),
                LENGTH_TO_MICROMETRE,
                f"PhysicalSize{axis}",
                notes,
            )
        )
    interval = _scaled(
        pixels.get("TimeIncrement"),
        pixels.get("TimeIncrementUnit", "s"),
        TIME_TO_MINUTE,
        "TimeIncrement",
        notes,
    )
    defaults = [
        f"{name} (unit not stated: OME default {unit})"
        for name, unit, value in (
            ("PhysicalSizeX", "µm", sizes[0]),
            ("PhysicalSizeY", "µm", sizes[1]),
            ("PhysicalSizeZ", "µm", sizes[2]),
            ("TimeIncrement", "s", interval),
        )
        if value is not None and pixels.get(f"{name}Unit") is None
    ]
    if defaults:
        notes.append(
            "Units taken from the OME schema defaults: "
            + ", ".join(defaults)
            + ". Check these values before confirming."
        )
    return Calibration(*sizes, interval, source="header (OME)"), notes


def _imagej_calibration(tif: tifffile.TiffFile) -> tuple[Calibration, list[str]]:
    """Read XResolution/YResolution, spacing and finterval of an ImageJ header."""
    meta = tif.imagej_metadata or {}
    notes: list[str] = []
    unit = str(meta.get("unit", "")).replace("\\u00B5", "µ").replace("micron", "um")
    page = tif.pages.first
    xy = []
    for tag_name in ("XResolution", "YResolution"):
        tag = page.tags.get(tag_name)
        value = None
        if tag is not None and tag.value[0]:
            value = tag.value[1] / tag.value[0]
        xy.append(_scaled(value, unit or "pixel", LENGTH_TO_MICROMETRE, tag_name, notes))
    z = _scaled(meta.get("spacing"), unit or "pixel", LENGTH_TO_MICROMETRE, "spacing", notes)
    t_unit = str(meta.get("tunit", "")).strip()
    interval = None
    if meta.get("finterval") is not None:
        if t_unit:
            interval = _scaled(meta["finterval"], t_unit, TIME_TO_MINUTE, "finterval", notes)
        else:
            notes.append(
                f"finterval={meta['finterval']} has no time unit in the header; "
                "enter the frame interval yourself."
            )
    return Calibration(xy[0], xy[1], z, interval, source="header (ImageJ)"), notes


def _scaled(
    value: object, unit: str, table: dict[str, float], name: str, notes: list[str]
) -> float | None:
    """Convert a header value with its unit, or note why it is unusable."""
    if value is None:
        return None
    key = {"micron": "um", "microns": "um", "sec": "s"}.get(unit.strip(), unit.strip())
    if key not in table:
        notes.append(f"{name}={value} has unit '{unit}', which is not a physical unit here.")
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        notes.append(f"{name}={value} is not a valid positive value.")
        return None
    converted = number * table[key]
    if not (math.isfinite(converted) and converted > 0):  # overflow or underflow on conversion
        notes.append(f"{name}={value} {unit} cannot be converted to a usable value.")
        return None
    return converted


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
    if "S" in header.header_axes:
        raise InputError(
            "The file stores samples per pixel (RGB or similar planar samples); "
            "save the nuclear channel as a greyscale TIFF."
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


UNKNOWN_AXES = "QI"
"""tifffile's letters for a dimension without a known role: the only axes a user may name."""


def named_axis_conflicts(confirmed: str, header_axes: str) -> str:
    """Return where confirmed axes contradict the axes a header names ('' when none).

    Every position whose header letter is an axis role (``T``, ``Z``, ``C``, ``Y``, ``X``)
    must be confirmed with that letter, and a position the header names with any other
    letter (``E``, ``H``, ``A``, ``R``, ``0``, ...) is a dimension the profiler does not
    analyse, so it is refused; only tifffile's unknown positions (:data:`UNKNOWN_AXES`,
    ``Q`` and ``I``) are the user's to confirm. A header without ``T`` (``ZCYX``) or with
    another named axis (``EZYX``) therefore cannot be read as a time-lapse (re-validation
    R3 and round 3).
    """
    if len(confirmed) != len(header_axes):
        return f"{len(confirmed)} axes confirmed for {len(header_axes)} in the file"
    found = []
    for i, (given, named) in enumerate(zip(confirmed, header_axes, strict=True)):
        if named in UNKNOWN_AXES or given == named:
            continue
        if named in "TZCYX":
            found.append(f"axis {i + 1} is {named} in the header, not {given}")
        else:
            found.append(f"axis {i + 1} is {named} in the header, a dimension not analysed")
    return ", ".join(found)


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
