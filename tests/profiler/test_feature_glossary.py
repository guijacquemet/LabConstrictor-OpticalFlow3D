"""docs/features.md is generated from the feature dictionary and must not be stale."""

import importlib.util
from pathlib import Path

from opticalflow3d_profiler.feature_dictionary import frame_dictionary

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "make_feature_glossary", ROOT / "tools" / "make_feature_glossary.py"
)
glossary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(glossary)


def test_the_glossary_page_is_up_to_date():
    page = (ROOT / "docs" / "features.md").read_text(encoding="utf-8")
    assert page == glossary.glossary_markdown(), "run: python tools/make_feature_glossary.py"


def test_every_feature_column_is_explained():
    page = glossary.glossary_markdown()
    for mode in ("xy", "xyz"):
        for definition in frame_dictionary(mode, intensity=True):
            assert f"| `{definition.name}` |" in page
