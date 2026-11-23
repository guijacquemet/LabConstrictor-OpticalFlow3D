"""MorphoBricks feature column names (pure).

Feature columns follow the MorphoBricks scheme (decision D09, MorphoRelate's naming): tokens
joined by a double underscore, the channel token first, then the object-set (or
compartment) token, then the lower-case feature key: ``H2B__Nuclei__speed_xy_median``. The
optical flow reads one channel, so every flow feature carries that channel's name. Without a
foreground the region is the whole image, the MorphoBricks compartment ``whole``; with a
foreground (a threshold or masks) it is the user's object-set name.

Per-FOV aggregates over time add the statistic to the feature key
(``speed_xy_median_time_mean``). Quality-control columns (``qc_*``) are observation
metadata, not features (MorphoFeature naming contract, principle 7): they keep their plain
names and never enter a profile.

The token rules, reserved names and :func:`feature_column` are reimplemented from
MorphoFeature ``src/morphofeature/naming.py`` (MIT licence, CellMigrationLab, commit
recorded in ``docs/morphobricks.md``); MorphoFeature is not a dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .validation import InputError

SEPARATOR = "__"
WHOLE = "whole"
TIME_STAT = "_time_"
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
    """Return whether ``text`` can be a channel or object-set token.

    A token starts with a letter and holds only letters, digits and single underscores, so it
    can never contain the separator.
    """
    return isinstance(text, str) and bool(_NAME_TOKEN.match(text))


def reserved_name(text: str) -> bool:
    """Return whether a channel or object-set name is reserved (case-folded).

    MorphoBricks identity columns and compartment tokens cannot name a channel or a mask.
    """
    return text.casefold() in RESERVED_NAMES | set(RESERVED_COMPARTMENTS)


def check_channel_name(name: object) -> str:
    """Return a valid channel token, else raise.

    Raises
    ------
    InputError
        When the name is empty, malformed or reserved. Channels are never named by guess.
    """
    if not is_name_token(name):
        raise InputError(
            f"Channel name {name!r} is not valid: give the stain's name, starting with a "
            "letter, with letters, digits and single underscores only (for example H2B)."
        )
    if reserved_name(str(name)):
        raise InputError(f"Channel name {name!r} is reserved by MorphoBricks; choose another.")
    return str(name)


def check_object_set(name: object) -> str:
    """Return a valid object-set token for a foreground, else raise.

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


def feature_column(feature: str, object_set: str, channels: Sequence[str] = ()) -> str:
    """Build ``{channel}__...__{object_set}__{feature}``.

    Raises
    ------
    InputError
        If a token or the feature key is malformed.
    """
    if not isinstance(feature, str) or not _FEATURE_KEY.match(feature):
        raise InputError(f"Feature key {feature!r} must be lower-case snake_case.")
    for token in (*channels, object_set):
        if not is_name_token(token):
            raise InputError(f"Token {token!r} is not a valid channel or object-set name.")
    return SEPARATOR.join((*channels, object_set, feature))


def feature_key(column: str) -> str:
    """Return the feature key of a column (its last token; a QC column is its own key)."""
    return column.rsplit(SEPARATOR, 1)[-1]


def find_column(columns: Iterable[str], key: str) -> str | None:
    """Return the one column whose feature key is ``key``, or None.

    Raises
    ------
    InputError
        When several columns share the key (two channels or object sets in one table).
    """
    found = [c for c in columns if feature_key(c) == key]
    if len(found) > 1:
        raise InputError(f"Several columns have the feature key {key}: {', '.join(found)}.")
    return found[0] if found else None


@dataclass(frozen=True)
class ColumnNames:
    """The tokens of a run's feature columns.

    Attributes
    ----------
    channel
        The analysed channel's name (user-given, checked).
    object_set
        The object-set token: the user's foreground name, or ``whole`` without foreground.
    """

    channel: str
    object_set: str

    @classmethod
    def of(cls, channel: str | None, object_set: str | None, has_foreground: bool) -> ColumnNames:
        """Check and return the tokens of a run (``whole`` when there is no foreground)."""
        token = check_object_set(object_set) if has_foreground else WHOLE
        return cls(check_channel_name(channel), token)

    def column(self, key: str) -> str:
        """Return the column of a feature key; QC keys stay unprefixed (metadata)."""
        if key.startswith("qc_"):
            return key
        return feature_column(key, self.object_set, (self.channel,))

    def mapping(self, keys: Iterable[str]) -> dict[str, str]:
        """Return ``{key: column}`` for several keys."""
        return {k: self.column(k) for k in keys}
