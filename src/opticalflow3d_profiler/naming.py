"""MorphoBricks feature column names (pure).

Feature columns follow the MorphoBricks scheme (decision D09, MorphoRelate's naming): tokens
joined by a double underscore. The videos have a single channel, so columns take the
MorphoBricks form without a channel token: the object-set (or compartment) token, then the
lower-case feature key, ``Nuclei__speed_xy_median``. Without a foreground the region is the
whole image, the MorphoBricks compartment ``whole`` (``whole__speed_xy_median``); with an
intensity-threshold foreground it is the user's object-set name (default ``Nuclei``).

The per-FOV time averages keep the per-frame column names. Quality-control columns
(``qc_*``) are observation metadata, not features (MorphoFeature naming contract, principle
7): they keep their plain names and are never given to MorphoCoverage as features.

The token rules, reserved names and :func:`feature_column` are reimplemented from
MorphoFeature ``src/morphofeature/naming.py`` (MIT licence, CellMigrationLab, commit
recorded in ``docs/morphobricks.md``); MorphoFeature is not a dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .validation import InputError

SEPARATOR = "__"
WHOLE = "whole"
RESERVED_COMPARTMENTS = ("whole", "cell", "nucleus", "cytoplasm", "ring", "expanded_nucleus")
RESERVED_NAMES = frozenset(
    {
        "condition", "biological_repeat", "repeat", "technical_repeat", "position_id",
        "image_file", "image_path", "mask_file", "patch_file", "patch_id", "label_id",
        "z", "z0", "z1", "c", "t",
    }
)  # fmt: skip
_NAME_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*$")
_FEATURE_KEY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def is_name_token(text: object) -> bool:
    """Return whether ``text`` can be an object-set token.

    A token starts with a letter and holds only letters, digits and single underscores, so it
    can never contain the separator.
    """
    return isinstance(text, str) and bool(_NAME_TOKEN.match(text))


def reserved_name(text: str) -> bool:
    """Return whether an object-set name is reserved (case-folded).

    MorphoBricks identity columns and compartment tokens cannot name an object set.
    """
    return text.casefold() in RESERVED_NAMES | set(RESERVED_COMPARTMENTS)


def check_object_set(name: object) -> str:
    """Return a valid object-set token for the foreground, else raise.

    Raises
    ------
    InputError
        When malformed, reserved (``whole`` and the other compartments included) or with an
        ``in`` part (MorphoRelate's ``<compartment>_in_<region>`` columns).
    """
    if not is_name_token(name):
        raise InputError(f"Object-set name {name!r} is not valid (for example Nuclei).")
    text = str(name)
    if reserved_name(text) or "in" in text.casefold().split("_"):
        raise InputError(f"Object-set name {name!r} is reserved by MorphoBricks; choose another.")
    return text


def feature_column(feature: str, object_set: str) -> str:
    """Build ``{object_set}__{feature}``.

    Raises
    ------
    InputError
        If the token or the feature key is malformed.
    """
    if not isinstance(feature, str) or not _FEATURE_KEY.match(feature):
        raise InputError(f"Feature key {feature!r} must be lower-case snake_case.")
    if not is_name_token(object_set):
        raise InputError(f"Token {object_set!r} is not a valid object-set name.")
    return SEPARATOR.join((object_set, feature))


def feature_key(column: str) -> str:
    """Return the feature key of a column (its last token; a QC column is its own key)."""
    return column.rsplit(SEPARATOR, 1)[-1]


def find_column(columns: Iterable[str], key: str) -> str | None:
    """Return the one column whose feature key is ``key``, or None.

    Raises
    ------
    InputError
        When several columns share the key (two object sets in one table).
    """
    found = [c for c in columns if feature_key(c) == key]
    if len(found) > 1:
        raise InputError(f"Several columns have the feature key {key}: {', '.join(found)}.")
    return found[0] if found else None


@dataclass(frozen=True)
class ColumnNames:
    """The object-set token of a run's feature columns.

    Attributes
    ----------
    object_set
        The user's foreground name, or ``whole`` without foreground.
    """

    object_set: str

    @classmethod
    def of(cls, object_set: str | None, has_foreground: bool) -> ColumnNames:
        """Check and return the token of a run (``whole`` when there is no foreground)."""
        return cls(check_object_set(object_set) if has_foreground else WHOLE)

    def column(self, key: str) -> str:
        """Return the column of a feature key; QC keys stay unprefixed (metadata)."""
        if key.startswith("qc_"):
            return key
        return feature_column(key, self.object_set)

    def mapping(self, keys: Iterable[str]) -> dict[str, str]:
        """Return ``{key: column}`` for several keys."""
        return {k: self.column(k) for k in keys}
