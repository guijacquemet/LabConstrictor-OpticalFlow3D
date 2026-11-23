"""Section 1's header checks: per image, and across images with MorphoBricks preprocessing."""

import numpy as np
import pandas as pd
import tifffile
from opticalflow3d_profiler.experiment_check import check_headers, header_notes, header_problems


def experiment(tmp_path, specs):
    rows = []
    for name, shape, dtype in specs:
        path = tmp_path / name
        tifffile.imwrite(path, np.zeros(shape, dtype), imagej=True, metadata={"axes": "TZYX"})
        rows.append({"image_path": str(path), "source_relative_path": name})
    return pd.DataFrame(rows)


def test_z_stacks_pass_the_preprocessing_header_checks(tmp_path):
    table, issues = check_headers(experiment(tmp_path, [("a.tif", (7, 3, 8, 8), "uint16")]), "TZYX")
    assert issues == [] and header_problems(table, issues) == []  # no z_stack_not_supported


def test_mixed_pixel_types_are_refused_and_sizes_noted(tmp_path):
    specs = [("a.tif", (7, 3, 8, 8), "uint16"), ("b.tif", (7, 3, 8, 8), "uint8"),
             ("c.tif", (7, 3, 16, 16), "uint16")]  # fmt: skip
    table, issues = check_headers(experiment(tmp_path, specs), "TZYX")
    assert any(p.startswith("mixed_dtypes") for p in header_problems(table, issues))
    assert any(n.startswith("different_sizes") for n in header_notes(table, issues))
