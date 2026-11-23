import json

import numpy as np
import pytest
import tifffile
from opticalflow3d_profiler._upstream.calc_flow import calc_flow3D
from opticalflow3d_profiler.config import FlowParameters, ImageSpec
from opticalflow3d_profiler.flow_backend import (
    estimate_resources,
    flow_identity,
    run_flow,
    upstream_identity,
)
from opticalflow3d_profiler.flow_store import (
    open_result,
    open_upstream_result,
    verify_result,
)
from opticalflow3d_profiler.image_io import file_identity, inspect_tiff
from opticalflow3d_profiler.validation import InputError


@pytest.fixture
def flow_run(tmp_path, imagej_file):
    path, stack = imagej_file
    spec = ImageSpec(path, "TZCYX", channel=1)
    header = inspect_tiff(path)
    out = tmp_path / "flow" / "fov1"
    manifest = run_flow(spec, header, FlowParameters(), out, "fov1")
    return spec, header, stack, out, manifest


def test_parity_with_direct_upstream_call(flow_run):
    _, _, stack, out, manifest = flow_run
    movie = stack[:, :, 1]
    assert [o["source_frame"] for o in manifest["outputs"]] == [3, 4, 5]  # 9 frames
    for t in (3, 4, 5):
        vx, vy, vz, rel = calc_flow3D(movie[t - 3 : t + 4], 3, 1, 4)
        for name, expected in zip(("vx", "vy", "vz", "rel"), (vx, vy, vz, rel), strict=True):
            saved = tifffile.imread(out / f"fov1_{name}_t{t:04d}.tiff")
            assert saved.dtype == expected.dtype  # no silent precision change
            np.testing.assert_array_equal(saved, expected)


def test_manifest_records_provenance(flow_run):
    spec, _, _, out, manifest = flow_run
    on_disk = json.loads((out / "flow_manifest.json").read_text())
    assert on_disk == manifest
    identity = manifest["identity"]
    assert identity["upstream"]["commit"].startswith("6b88604")
    assert identity["axes"] == "TZCYX" and identity["channel"] == 1
    assert identity["source"]["sha256"] == file_identity(spec.path)["sha256"]
    assert identity["frame_map"] == [3, 4, 5]
    assert manifest["velocity_units"]["vz"] == "slice/frame"


def test_results_are_never_overwritten(flow_run):
    spec, header, _, out, _ = flow_run
    with pytest.raises(InputError, match="never overwritten"):
        run_flow(spec, header, FlowParameters(), out, "fov1")


def test_reuse_requires_identical_identity_and_files(flow_run):
    spec, header, _, out, manifest = flow_run
    source = file_identity(spec.path)
    assert verify_result(out, flow_identity(spec, header, FlowParameters(), source)) == []
    other = flow_identity(spec, header, FlowParameters(w_sig=2), source)
    assert any("parameters" in p for p in verify_result(out, other))
    other_channel = flow_identity(
        ImageSpec(spec.path, "TZCYX", channel=0), header, FlowParameters(), source
    )
    assert any("channel" in p for p in verify_result(out, other_channel))
    target = out / manifest["outputs"][0]["files"]["vx"]["name"]
    target.write_bytes(target.read_bytes()[:-8] + b"\0" * 8)
    assert any("changed" in p for p in verify_result(out))
    with pytest.raises(InputError):
        open_result(out)


def test_open_result_lists_frames(flow_run):
    *_, out, _ = flow_run
    result = open_result(out)
    assert result.verified and [f.source_frame for f in result.frames] == [3, 4, 5]
    assert set(result.frames[0].load()) == {"vx", "vy", "vz", "rel"}


def test_float32_output_is_explicit(tmp_path, imagej_file):
    path, stack = imagej_file
    params = FlowParameters(output_dtype="float32")
    manifest = run_flow(
        ImageSpec(path, "TZCYX", channel=1), inspect_tiff(path), params, tmp_path / "f32", "f"
    )
    assert manifest["outputs"][0]["files"]["vx"]["dtype"] == "float32"
    assert manifest["identity"]["parameters"]["output_dtype"] == "float32"


def test_too_short_movie_is_refused_before_computing(tmp_path):
    path = tmp_path / "short.tif"
    tifffile.imwrite(
        path, np.zeros((5, 3, 16, 16), np.uint16), imagej=True, metadata={"axes": "TZYX"}
    )
    with pytest.raises(InputError, match="at least 7"):
        run_flow(ImageSpec(path, "TZYX"), inspect_tiff(path), FlowParameters(), tmp_path / "o", "x")
    assert not (tmp_path / "o").exists()


def test_upstream_hash_is_checked():
    assert upstream_identity()["calc_flow_sha256"].startswith("e40c6cff")


def test_resource_estimate_full_size_dataset(tmp_path):
    dims = {"T": 15, "Z": 11, "Y": 1840, "X": 1840}
    estimate = estimate_resources(dims, 2, FlowParameters(), tmp_path)
    assert estimate.n_outputs == 9
    assert 10e9 < estimate.peak_ram_bytes < 12e9
    assert estimate.output_bytes == 9 * 11 * 1840 * 1840 * 28


def test_upstream_process_flow_folder_can_be_opened(tmp_path):
    folder = tmp_path / "OpticalFlow3D" / "exp"
    folder.mkdir(parents=True)
    (folder / "exp_parameters.csv").write_text("xyzSig,tiSig,wSig,Nx,Ny,Nz,Nt\n3,1,4,8,8,3,9\n")
    for t in (3, 4):
        for c in ("vx", "vy", "vz", "rel"):
            tifffile.imwrite(
                folder / f"exp_{c}_t{t:04d}.tiff", np.zeros((3, 8, 8)), photometric="minisblack"
            )
    result = open_upstream_result(folder, "exp")
    assert not result.verified and [f.source_frame for f in result.frames] == [3, 4]
    (folder / "exp_rel_t0004.tiff").unlink()
    with pytest.raises(InputError, match="incomplete"):
        open_upstream_result(folder, "exp")


def test_upstream_licence_ships_with_the_python_files():
    from pathlib import Path

    from opticalflow3d_profiler._upstream import _license

    folder = Path(_license.__file__).parent
    assert (folder / "LICENSE").read_text() == _license.LICENSE_TEXT
    assert "Howard Hughes Medical Institute" in _license.LICENSE_TEXT
