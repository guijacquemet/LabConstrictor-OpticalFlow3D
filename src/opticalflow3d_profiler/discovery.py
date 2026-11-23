"""Find the fields of view of a MorphoBricks experiment folder (I/O, names only).

The MorphoBricks layout (MorphoBricks preprocessing contract §1) is::

    <experiment root>/<condition>/<biological repeat>/<technical repeat>/<image>.tif

- A *leaf folder* holds images and no subfolders; only images in leaf folders are fields of
  view. A folder with both images and subfolders is refused (``tiff_outside_leaf``).
- A branch may stop early: the missing levels are ``single``; when the root itself is the
  leaf, all three labels are ``single``. A folder named ``single`` (lower case) is accepted
  when it is the only folder in its place; in another case or beside other folders it is
  refused (``reserved_folder_name``). At most three folder levels.
- ``position_id`` is the image name without ``.tif``/``.tiff`` (any case, with a preceding
  ``.ome``). A field of view is identified by condition, biological repeat, technical repeat
  and ``position_id``.
- Names with outer whitespace or read as missing (``NA``, ``nan``, ``none``...) are refused
  (``invalid_name``), as are two folders of one level differing only in case anywhere in the
  experiment (``case_conflict``), two images of a leaf with the same ``position_id``
  ignoring case (``duplicate_position_id``), and an image named as a mask of another image
  (``image_named_as_mask``). Dot-files, ``Thumbs.db``, ``desktop.ini`` and ``__MACOSX`` are
  ignored. Links are followed only inside the experiment folder (``link_outside_folder``).
- OME-Zarr images are not read by this tool and are refused.

Foreground masks live in a masks folder outside the experiment, in the MorphoBricks mask
layouts (contract §15) for one mask type: ``<masks>/<type>/<same folders>/<position>.tif``
or ``<masks>/<same folders>/<position>_<type>.tif``.

The rules are reimplemented from MorphoBricks preprocessing (``discovery.py``,
``image_names.py``, MIT licence, CellMigrationLab); it is not a dependency. Nothing is read
from image contents here, and no label is taken from a file name.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

from .validation import InputError

LEVELS = ("condition", "biological_repeat", "technical_repeat")
FOV_KEY = (*LEVELS, "position_id")
SINGLE = "single"
MISSING_TEXT = frozenset({"", "na", "nan", "none", "null", "n/a", "<na>"})
SYSTEM_NAMES = frozenset({"thumbs.db", "desktop.ini", "__macosx"})
MASK_SUFFIXES = ("_mask", "_masks", "_cp_masks", "_labels", "_label", "_seg", "_segmentation")
_TIFF = re.compile(r"^(?P<stem>.*?)(?:\.ome)?\.tiff?$", re.IGNORECASE)


def is_system_name(name: str) -> bool:
    """Return whether a file or folder is ignored (hidden or system)."""
    return name.startswith(".") or name.casefold() in SYSTEM_NAMES


def position_id(name: str) -> str:
    """Return the position identifier of a TIFF image: its name without the extension.

    Raises
    ------
    InputError
        When the name is not a TIFF or is only an extension.
    """
    match = _TIFF.match(name)
    if not match or not match.group("stem") or match.group("stem").casefold() == ".ome":
        raise InputError(f"{name!r} is not a TIFF image name with a position name.")
    return match.group("stem")


def check_identity_text(value: str, field: str, where: str) -> str:
    """Return a label or position identifier, or raise ``invalid_name``."""
    if value != value.strip() or value.casefold() in MISSING_TEXT:
        raise InputError(
            f"invalid_name: {field} {value!r} ({where}) has outer spaces or reads as a missing "
            "value; rename it."
        )
    return value


def _entries(folder: Path, root: Path) -> tuple[list[Path], list[Path]]:
    """Return the subfolders and TIFF images of a folder (system names ignored)."""
    folders, images = [], []
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if is_system_name(path.name):
            continue
        real = Path(os.path.realpath(path))
        if path.is_symlink() and not real.is_relative_to(root):
            raise InputError(f"link_outside_folder: {path} points outside the experiment.")
        if path.name.casefold().endswith(".zarr"):
            raise InputError(f"{path}: OME-Zarr images are not supported; convert to OME-TIFF.")
        if path.is_dir():
            folders.append(path)
        elif _TIFF.match(path.name):
            images.append(path)
    return folders, images


def _check_single(folders: list[Path], where: Path) -> None:
    """Refuse a ``single`` folder in another case or beside other folders."""
    for path in folders:
        if path.name.casefold() == SINGLE and (path.name != SINGLE or len(folders) > 1):
            raise InputError(
                f"reserved_folder_name: {path.name!r} in {where} — 'single' is accepted only "
                "in lower case and as the only folder in its place."
            )


def _walk(folder: Path, root: Path, labels: tuple[str, ...], leaves: list) -> None:
    """Collect ``(labels, folder, images)`` for every leaf folder below ``folder``."""
    folders, images = _entries(folder, root)
    if folders and images:
        raise InputError(
            f"tiff_outside_leaf: {folder} holds both images and subfolders; images must be "
            "in leaf folders only."
        )
    if not folders:
        if images:
            leaves.append((labels, folder, images))
        return
    if len(labels) == len(LEVELS):
        raise InputError(f"{folders[0]} is below the technical-repeat level (max 3 levels).")
    _check_single(folders, folder)
    for path in folders:
        field = LEVELS[len(labels)]
        label = check_identity_text(path.name, field, path.relative_to(root).as_posix())
        _walk(path, root, (*labels, label), leaves)


def _check_case(table: pd.DataFrame) -> None:
    """Refuse labels of one level that differ only in case anywhere in the experiment."""
    for level in LEVELS:
        values = pd.Series(table[level].unique())
        folded = values.str.casefold()
        clash = values[folded.duplicated(keep=False)]
        if len(clash):
            raise InputError(f"case_conflict: {level} folders {sorted(clash)} differ only in case.")


def _leaf_rows(labels: tuple[str, ...], folder: Path, images: list[Path], root: Path) -> list:
    """Return the rows of one leaf folder, refusing duplicate or mask-named positions."""
    where = folder.relative_to(root).as_posix()
    full = (*labels, *([SINGLE] * (len(LEVELS) - len(labels))))
    positions = {}
    for image in images:
        pid = check_identity_text(position_id(image.name), "position_id", f"{where}/{image.name}")
        if pid.casefold() in positions:
            raise InputError(
                f"duplicate_position_id: {image.name} and {positions[pid.casefold()].name} in "
                f"{where} have the same position name."
            )
        positions[pid.casefold()] = image
    rows = []
    for pid_folded, image in positions.items():
        for other in positions:
            if other != pid_folded and any(pid_folded == other + s for s in MASK_SUFFIXES):
                raise InputError(
                    f"image_named_as_mask: {where}/{image.name} is named as a mask of "
                    f"{positions[other].name}; masks belong in a masks folder outside the "
                    "experiment."
                )
        record = dict(zip(LEVELS, full, strict=True))
        record["position_id"] = position_id(image.name)
        record["image_path"] = image.as_posix()
        record["source_relative_path"] = image.relative_to(root).as_posix()
        rows.append(record)
    return rows


def find_mask(masks: Path, mask_type: str, relative_folder: str, pid: str) -> Path | None:
    """Return the mask of one position in a MorphoBricks masks folder, or None.

    Raises
    ------
    InputError
        When both layouts, or two files differing in case or extension, match.
    """
    candidates = [
        (masks / mask_type / relative_folder, pid),
        (masks / relative_folder, f"{pid}_{mask_type}"),
    ]
    found = []
    for folder, stem in candidates:
        if folder.is_dir():
            found += [
                p
                for p in folder.iterdir()
                if p.is_file()
                and _TIFF.match(p.name)
                and position_id(p.name).casefold() == stem.casefold()
            ]
    if len(found) > 1:
        raise InputError(f"Several masks match {relative_folder}/{pid}: {[p.name for p in found]}.")
    return found[0] if found else None


def discover_experiment(
    root: Path, masks: Path | None = None, mask_type: str | None = None
) -> pd.DataFrame:
    """Return one row per field of view of a MorphoBricks experiment folder.

    Parameters
    ----------
    root
        Experiment folder.
    masks
        Optional masks folder (outside the experiment).
    mask_type
        The mask type name used in the masks folder (required with ``masks``).

    Returns
    -------
    pandas.DataFrame
        ``condition``, ``biological_repeat``, ``technical_repeat``, ``position_id``,
        ``image_path``, ``source_relative_path`` and, with masks, ``mask_path`` (empty when a
        position has no mask), sorted by the field-of-view key.

    Raises
    ------
    InputError
        For any layout rule above, an empty experiment or a masks folder inside it.
    """
    root = Path(os.path.realpath(root))
    if not root.is_dir():
        raise InputError(f"The experiment folder {root} does not exist.")
    leaves: list = []
    _walk(root, root, (), leaves)
    rows = [
        r for labels, folder, images in leaves for r in _leaf_rows(labels, folder, images, root)
    ]
    if not rows:
        raise InputError(f"No TIFF image was found in a leaf folder of {root}.")
    table = pd.DataFrame(rows)
    _check_case(table)
    if masks is not None:
        masks = Path(os.path.realpath(masks))
        if masks.is_relative_to(root) or root.is_relative_to(masks):
            raise InputError("The masks folder must be outside the experiment folder.")
        if not mask_type:
            raise InputError("Give the mask type name used in the masks folder.")
        table["mask_path"] = [
            (m.as_posix() if (m := find_mask(masks, mask_type, str(Path(r).parent), p)) else "")
            for r, p in zip(table["source_relative_path"], table["position_id"], strict=True)
        ]
    return table.sort_values(list(FOV_KEY)).reset_index(drop=True)
