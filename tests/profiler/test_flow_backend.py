import json
from pathlib import Path

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
    verify_result,
)
from opticalflow3d_profiler.image_io import file_identity, inspect_tiff
from opticalflow3d_profiler.validation import InputError


@pytest.fixture
def flow_run(tmp_path, imagej_file):
    path, stack = imagej_file
    spec = ImageSpec(path, "TZYX")
    header = inspect_tiff(path)
    out = tmp_path / "flow" / "fov1"
    manifest = run_flow(spec, header, FlowParameters(mode="xyz"), out, "fov1")
    return spec, header, stack, out, manifest


def test_parity_with_direct_upstream_call(flow_run):
    _, _, stack, out, manifest = flow_run
    movie = stack
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
    assert identity["axes"] == "TZYX" and "channel" not in identity
    assert identity["source"]["sha256"] == file_identity(spec.path)["sha256"]
    assert identity["frame_map"] == [3, 4, 5]
    assert manifest["velocity_units"]["vz"] == "slice/frame"


def test_results_are_never_overwritten(flow_run):
    spec, header, _, out, _ = flow_run
    with pytest.raises(InputError, match="never overwritten"):
        run_flow(spec, header, FlowParameters(mode="xyz"), out, "fov1")


def test_reuse_requires_identical_identity_and_files(flow_run):
    spec, header, _, out, manifest = flow_run
    source = file_identity(spec.path)
    assert verify_result(out, flow_identity(spec, header, FlowParameters(mode="xyz"), source)) == []
    other = flow_identity(spec, header, FlowParameters(mode="xyz", w_sig=2), source)
    assert any("parameters" in p for p in verify_result(out, other))
    other_axes = flow_identity(
        ImageSpec(spec.path, "ZTYX"), header, FlowParameters(mode="xyz"), source
    )
    assert any("axes" in p for p in verify_result(out, other_axes))
    target = out / manifest["outputs"][0]["files"]["vx"]["name"]
    target.write_bytes(target.read_bytes()[:-8] + b"\0" * 8)
    assert any("changed" in p for p in verify_result(out))
    with pytest.raises(InputError):
        open_result(out)


def test_open_result_lists_frames(flow_run):
    *_, out, _ = flow_run
    result = open_result(out)
    assert [f.source_frame for f in result.frames] == [3, 4, 5]
    assert set(result.frames[0].load()) == {"vx", "vy", "vz", "rel"}


def test_float32_output_is_explicit(tmp_path, imagej_file):
    path, stack = imagej_file
    params = FlowParameters(mode="xyz", output_dtype="float32")
    manifest = run_flow(ImageSpec(path, "TZYX"), inspect_tiff(path), params, tmp_path / "f32", "f")
    assert manifest["outputs"][0]["files"]["vx"]["dtype"] == "float32"
    assert manifest["identity"]["parameters"]["output_dtype"] == "float32"


def test_too_short_movie_is_refused_before_computing(tmp_path):
    path = tmp_path / "short.tif"
    tifffile.imwrite(
        path, np.zeros((5, 3, 16, 16), np.uint16), imagej=True, metadata={"axes": "TZYX"}
    )
    with pytest.raises(InputError, match="at least 7"):
        run_flow(
            ImageSpec(path, "TZYX"),
            inspect_tiff(path),
            FlowParameters(mode="xyz"),
            tmp_path / "o",
            "x",
        )
    assert not (tmp_path / "o").exists()


def test_upstream_hash_is_checked():
    assert upstream_identity()["calc_flow_sha256"].startswith("e40c6cff")


def test_resource_estimate_full_size_dataset(tmp_path):
    dims = {"T": 15, "Z": 11, "Y": 1840, "X": 1840}
    estimate = estimate_resources(dims, 2, FlowParameters(mode="xyz"), tmp_path)
    assert estimate.n_outputs == 9
    assert 10e9 < estimate.peak_ram_bytes < 12e9
    assert estimate.output_bytes == 9 * 11 * 1840 * 1840 * 28


def test_upstream_licence_ships_with_the_python_files():
    from pathlib import Path

    from opticalflow3d_profiler._upstream import _license

    folder = Path(_license.__file__).parent
    assert (folder / "LICENSE").read_text() == _license.LICENSE_TEXT
    assert "Howard Hughes Medical Institute" in _license.LICENSE_TEXT


def test_correction_code_identity_invalidates_cached_corrected_flow(flow_run, monkeypatch):
    from opticalflow3d_profiler import flow_backend

    spec, header, _, _, _ = flow_run
    source = file_identity(spec.path)
    plain = FlowParameters(mode="xyz")
    corrected = FlowParameters(mode="xyz", brightness_equalisation="global_mean")
    before = flow_backend.flow_identity(spec, header, corrected, source)
    assert before["brightness_correction"]["time_series_sha256"]
    assert "brightness_correction" not in flow_backend.flow_identity(spec, header, plain, source)
    # Re-validation M2: a real change of the bytes of either module changes the identity.
    import morphobricks_normalization.time_series as time_series
    from opticalflow3d_profiler import brightness

    original = Path.read_bytes
    for edited in (time_series.__file__, brightness.__file__):
        with monkeypatch.context() as patch:
            patch.setattr(
                Path, "read_bytes",
                lambda self, e=edited: original(self) + (b"#" if str(self) == e else b""),
            )  # fmt: skip
            after = flow_backend.flow_identity(spec, header, corrected, source)
        assert flow_backend.identity_key(after) != flow_backend.identity_key(before)
    assert "commit" not in before["brightness_correction"]  # a wheel install has none


def test_a_failing_window_closes_progress_and_removes_the_partial_folder(
    tmp_path, imagej_file, monkeypatch
):
    from opticalflow3d_profiler import flow_backend
    from opticalflow3d_profiler.progress import Stage, Tracker

    closed = []

    class Recording(Tracker):
        def stage(self, description, total, nested=False):
            class Closing(Stage):
                def close(self):
                    closed.append(description)

            return Closing()

    calls = {"n": 0}
    original = flow_backend.flow_window

    def failing(window, params):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return original(window, params)

    monkeypatch.setattr(flow_backend, "flow_window", failing)
    path, _ = imagej_file
    out = tmp_path / "flow" / "f"
    with pytest.raises(RuntimeError, match="disk full"):
        run_flow(ImageSpec(path, "TZYX"), inspect_tiff(path), FlowParameters(mode="xyz"), out, "f",
                 tracker=Recording())  # fmt: skip
    assert closed == ["Optical flow f"]
    assert not out.exists() and not list((tmp_path / "flow").glob("f.partial-*"))


def test_a_manifest_missing_a_planned_output_is_refused(flow_run):
    spec, header, _, out, manifest = flow_run
    edited = json.loads((out / "flow_manifest.json").read_text())
    edited["outputs"] = edited["outputs"][:1]  # files and hashes of the kept output are intact
    from opticalflow3d_profiler.flow_backend import identity_key

    edited["identity_key"] = identity_key(edited["identity"])
    (out / "flow_manifest.json").write_text(json.dumps(edited))
    assert any("not the planned [3, 4, 5]" in p for p in verify_result(out))
    with pytest.raises(InputError):
        open_result(out)


@pytest.mark.parametrize("where", ["tiff", "manifest", "publish"])
def test_a_failure_up_to_publication_removes_only_the_partial_folder(
    tmp_path, imagej_file, monkeypatch, where
):
    # Re-validation M7: a failure writing the manifest or in os.replace left the partial folder.
    from opticalflow3d_profiler import flow_backend

    def fail(*_args, **_kwargs):
        raise OSError(f"{where} failed")

    if where == "tiff":
        monkeypatch.setattr(flow_backend.tifffile, "imwrite", fail)
    elif where == "manifest":
        original = Path.write_text
        monkeypatch.setattr(
            Path, "write_text",
            lambda self, *a, **k: fail() if self.name == "flow_manifest.json"
            else original(self, *a, **k),
        )  # fmt: skip
    else:
        monkeypatch.setattr(flow_backend.os, "replace", fail)
    path, _ = imagej_file
    flow = tmp_path / "flow"
    (flow / "other").mkdir(parents=True)
    (flow / "other" / "keep.txt").write_text("unrelated")
    with pytest.raises(OSError, match=f"{where} failed"):
        run_flow(ImageSpec(path, "TZYX"), inspect_tiff(path), FlowParameters(mode="xyz"),
                 flow / "f", "f")  # fmt: skip
    assert sorted(p.name for p in flow.iterdir()) == ["other"]
    assert (flow / "other" / "keep.txt").read_text() == "unrelated"
