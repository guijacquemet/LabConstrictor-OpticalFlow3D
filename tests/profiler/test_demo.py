"""The synthetic demo runs end to end and keeps every intermediate file."""

import matplotlib

matplotlib.use("Agg")

from opticalflow3d_profiler.demo import DemoDesign, run_demo  # noqa: E402

# Checks that hold at any size; the statistical ones need the full-size demo.
STRUCTURAL = {
    "fields of view completed",
    "missing file recorded as failed",
    "optical-flow outputs per FOV (verified hashes)",
    "dominant direction drug",
    "comparison at repeat level",
    "mask run reuses verified flow",
}


def test_demo_runs_and_keeps_intermediate_files(tmp_path):
    design = DemoDesign(shape=(15, 11, 64, 64), n_nuclei=8, repeats=3, fovs_per_repeat=1)
    checks = run_demo(tmp_path / "demo", design, progress=lambda _line: None)
    results = {r["check"]: r["result"] for r in checks.rows}
    assert {name for name in STRUCTURAL if results[name] == "PASS"} == STRUCTURAL, checks.rows
    run = tmp_path / "demo" / "results" / "run-threshold"
    fov = next((run / "qc").glob("drug*"))
    assert len(list(fov.glob("flow_t*.png"))) == 9
    assert len(list(fov.glob("foreground_t*.png"))) == 9
    assert (fov / "input_montage_z5.png").exists() and (fov / "features_over_time.png").exists()
    assert len(list((run / "flow" / fov.name).glob("*.tiff"))) == 36
    for name in (
        "features/features_per_frame.csv",
        "features/feature_dictionary.json",
        "analysis/demo/pca_scores.csv",
        "analysis/demo/figures/pca_pc1_pc2.png",
        "run_manifest.json",
        "fovs.csv",
    ):
        assert (run / name).exists(), name
    assert (tmp_path / "demo" / "demo_report.md").read_text().startswith("# Synthetic demo")
    assert (tmp_path / "demo" / "masks").is_dir()
