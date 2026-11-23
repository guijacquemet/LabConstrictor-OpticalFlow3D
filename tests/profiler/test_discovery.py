"""MorphoBricks experiment folders: every level optional, missing levels are 'single'."""

import pytest
from opticalflow3d_profiler.discovery import discover_experiment, position_id
from opticalflow3d_profiler.experiment import read_experiment_folder
from opticalflow3d_profiler.validation import InputError


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def labels(table):
    return [tuple(r) for r in table[["condition", "biological_repeat", "technical_repeat",
                                      "position_id"]].itertuples(index=False)]  # fmt: skip


def test_single_folder_gives_single_labels(tmp_path):
    touch(tmp_path / "a.tif")
    touch(tmp_path / "b.ome.tiff")
    assert labels(discover_experiment(tmp_path)) == [
        ("single", "single", "single", "a"),
        ("single", "single", "single", "b"),
    ]


def test_every_level_is_optional(tmp_path):
    touch(tmp_path / "ctrl" / "f1.tif")
    touch(tmp_path / "drug" / "rep1" / "f1.tif")
    touch(tmp_path / "drug" / "rep2" / "dish1" / "f1.tif")
    touch(tmp_path / "drug" / "rep2" / "dish2" / "f1.tif")
    table = discover_experiment(tmp_path)
    assert labels(table) == [
        ("ctrl", "single", "single", "f1"),
        ("drug", "rep1", "single", "f1"),
        ("drug", "rep2", "dish1", "f1"),
        ("drug", "rep2", "dish2", "f1"),
    ]
    assert table.loc[3, "source_relative_path"] == "drug/rep2/dish2/f1.tif"
    assert read_experiment_folder(tmp_path)["fov_uid"].is_unique  # same name, 4 positions


def test_single_folder_name_rules(tmp_path):
    touch(tmp_path / "ctrl" / "single" / "f1.tif")
    assert labels(discover_experiment(tmp_path)) == [("ctrl", "single", "single", "f1")]
    touch(tmp_path / "ctrl" / "rep2" / "f1.tif")
    with pytest.raises(InputError, match="reserved_folder_name"):
        discover_experiment(tmp_path)


@pytest.mark.parametrize(
    ("files", "code"),
    [
        (["ctrl/a.tif", "ctrl/rep1/b.tif"], "tiff_outside_leaf"),
        (["a/b/c/d/e.tif"], "below the technical-repeat"),
        (["ctrl/Rep1/a.tif", "drug/rep1/a.tif"], "case_conflict"),
        (["ctrl/f1.tif", "ctrl/F1.tiff"], "duplicate_position_id"),
        (["ctrl/f1.tif", "ctrl/f1_mask.tif"], "image_named_as_mask"),
        (["NA/f1.tif"], "invalid_name"),
        (["ctrl /f1.tif"], "invalid_name"),
    ],
)
def test_layout_errors_are_refused(tmp_path, files, code):
    for name in files:
        touch(tmp_path / name)
    with pytest.raises(InputError, match=code):
        discover_experiment(tmp_path)


def test_system_files_are_ignored_and_empty_experiment_refused(tmp_path):
    touch(tmp_path / ".DS_Store")
    touch(tmp_path / "ctrl" / "Thumbs.db")
    with pytest.raises(InputError, match="No TIFF image"):
        discover_experiment(tmp_path)
    touch(tmp_path / "ctrl" / "f1.tif")
    assert len(discover_experiment(tmp_path)) == 1


def test_position_id_follows_morphobricks():
    assert position_id("img_01.ome.tif") == "img_01"
    assert position_id("A.TIFF") == "A"
    with pytest.raises(InputError):
        position_id(".tif")
