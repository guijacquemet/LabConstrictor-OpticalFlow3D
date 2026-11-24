"""End-to-end: synthetic experiment -> optical flow -> features -> MorphoCoverage report."""

import json

import pandas as pd
import pytest
import tifffile
from opticalflow3d_profiler.analysis import load_runs
from opticalflow3d_profiler.config import (
    Calibration,
    FeatureSettings,
    FlowParameters,
    ForegroundSpec,
)
from opticalflow3d_profiler.experiment import read_experiment_folder
from opticalflow3d_profiler.pipeline import RunSettings, run_experiment
from opticalflow3d_profiler.results import create_run
from opticalflow3d_profiler.synthetic import SyntheticMovie, render
from opticalflow3d_profiler.validation import InputError

CAL = Calibration(0.65, 0.65, 2.0, 0.5, source="user")
SPEED = "Nuclei__speed_xy_median"


def settings(**changes):
    base = dict(
        axes="TZYX",
        calibration=CAL,
        features=FeatureSettings(reliability_value=1e-3, region_size_px=24, min_region_voxels=20),
        foreground=ForegroundSpec(mode="threshold", threshold=300.0),
        object_set="Nuclei",
    )
    base.update(changes)
    return RunSettings(**base)


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp")
    rows = []
    for condition, speed in (("ctrl", 0.2), ("drug", 0.6)):
        for rep in ("r1", "r2", "r3"):
            seed = len(rows)
            movie = SyntheticMovie(
                shape=(9, 11, 48, 48),
                n_nuclei=6,
                velocity=(0.0, 0.1, speed),
                seed=seed,
                noise_sd=5.0,
            )
            path = root / "experiment" / condition / rep / "pos1.tif"  # MorphoBricks layout
            path.parent.mkdir(parents=True, exist_ok=True)
            tifffile.imwrite(path, render(movie), imagej=True, metadata={"axes": "TZYX"})
            rows.append(path)
    (root / "experiment" / "ctrl" / "r1" / "broken.tif").write_bytes(b"not a TIFF")
    metadata = read_experiment_folder(root / "experiment")
    run = create_run(root / "results", "run1")
    manifest = run_experiment(metadata, settings(), run)
    return root, metadata, run, manifest


def test_failures_are_recorded_not_skipped(experiment):
    _, _, run, manifest = experiment
    fovs = pd.read_csv(run / "fovs.csv")
    assert len(fovs) == 7
    failed = fovs[fovs["status"] == "failed"]
    assert list(failed["position_id"]) == ["broken"]
    assert set(fovs["technical_repeat"]) == {"single"}  # missing level, MorphoBricks
    assert sum(f["status"] == "complete" for f in manifest["fovs"]) == 6


def test_tables_and_provenance(experiment):
    _, metadata, run, manifest = experiment
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    assert len(per_fov) == 6 and per_fov["fov_uid"].is_unique
    assert sorted(frames["t"].unique()) == [3, 4, 5]
    assert (frames["time_min"] == frames["t"] * 0.5).all()
    for column in ("condition", "biological_repeat", "technical_repeat", "position_id"):
        assert column in frames.columns and column in per_fov.columns
    assert SPEED in frames.columns and SPEED in per_fov.columns
    first = frames[frames["fov_uid"] == per_fov["fov_uid"].iloc[0]]
    assert per_fov[SPEED].iloc[0] == pytest.approx(first[SPEED].mean())  # time average
    assert frames.groupby("fov_uid").size().eq(3).all()
    dictionary = json.loads((run / "features" / "feature_dictionary.json").read_text())
    assert dictionary["units"] == {"lateral": "µm/min", "axial": "µm/min", "time": "min"}
    names = {d["name"] for d in dictionary["fov_features"]}
    assert names <= set(per_fov.columns)
    assert dictionary["column_naming"]["object_set"] == "Nuclei"
    assert manifest["upstream"]["commit"].startswith("6b88604")
    assert manifest["settings"]["foreground"]["threshold"] == 300.0
    assert manifest["settings"]["calibration"]["pixel_size_z"] == 2.0
    assert "numpy" in manifest["environment"]
    assert (run / "logs" / "run.log").read_text().count("failed") >= 1


def test_faster_condition_has_higher_speed(experiment):
    _, _, run, _ = experiment
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    speed = per_fov.groupby("condition")[SPEED].mean()
    assert speed["drug"] > 2 * speed["ctrl"]


def test_run_folder_is_never_overwritten(experiment):
    root, *_ = experiment
    with pytest.raises(InputError, match="never overwritten"):
        create_run(root / "results", "run1")


def test_features_recomputed_from_verified_flow(experiment):
    root, metadata, run, _ = experiment
    new = create_run(root / "results", "run2")
    other = settings(features=FeatureSettings(reliability_mode="none", region_size_px=24))
    manifest = run_experiment(metadata, other, new, reuse_from=run)
    reused = [f for f in manifest["fovs"] if f["status"] == "complete"]
    assert len(reused) == 6 and all(f["flow_origin"].startswith("reused") for f in reused)
    assert not any((new / "flow").iterdir())  # nothing recomputed


def test_flow_with_other_parameters_is_recomputed_not_reused(experiment):
    import hashlib

    root, metadata, run, _ = experiment
    one = metadata[metadata["position_id"] != "broken"].iloc[:1]
    old = run / "flow" / one["fov_uid"].iloc[0]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in old.iterdir()}
    new = create_run(root / "results", "run3")
    manifest = run_experiment(
        one, settings(flow=FlowParameters(mode="xyz", w_sig=2)), new, reuse_from=run
    )
    status = manifest["fovs"][0]
    assert status["status"] == "complete"
    assert status["flow_origin"].startswith("computed (earlier flow in")
    assert "parameters.w_sig: 4" in status["flow_origin"] and "→ 2" in status["flow_origin"]
    assert (new / "flow" / one["fov_uid"].iloc[0] / "flow_manifest.json").is_file()
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in old.iterdir()}
    assert before == after  # the earlier result is untouched


def test_morphocoverage_report_from_the_per_fov_table(experiment):
    from opticalflow3d_profiler.coverage import Design, coverage_input, run_report

    _, _, run, _ = experiment
    features = load_runs([run])
    with pytest.raises(InputError, match="Confirm that each biological-repeat label"):
        coverage_input(features, Design("ctrl", SPEED, repeats_paired=False))
    data = coverage_input(features, Design("ctrl", SPEED, repeats_paired=True))
    assert len(data.objects) == 6 and not any(c.startswith("qc_") for c in data.features)
    assert (data.fovs["repeat_group"] == data.fovs["biological_repeat"]).all()
    assert set(data.fovs["repeat_group"]) == {"r1", "r2", "r3"}  # one run: the folder labels
    out = run / "analysis" / "report-1"
    path, result, _ = run_report(features, Design("ctrl", SPEED, repeats_paired=True), out)
    assert path == out / "report.html" and path.stat().st_size > 100_000
    row = result.discovery.tests.set_index("feature").loc[SPEED]
    assert row["observations"] == 3 and row["repeats"] == 3 and row["d"] > 0
    assert (out / "morphocoverage_objects.csv").is_file()
    record = json.loads((out / "design.json").read_text())
    assert record["design"]["control"] == "ctrl" and record["observation_unit"] == "fov"
    assert record["morphocoverage"]["version"]
    with pytest.raises(InputError, match="never overwritten"):
        run_report(features, Design("ctrl", SPEED, repeats_paired=True), out)


def _copy_run(run, target, prefix, change=None):
    import shutil

    shutil.copytree(run, target)
    table = target / "features" / "features_per_fov.csv"
    data = pd.read_csv(table, dtype=str, keep_default_na=False)
    data["fov_uid"] = prefix + data["fov_uid"]
    data.to_csv(table, index=False)
    if change:
        manifest = json.loads((target / "run_manifest.json").read_text())
        manifest["settings"]["features"].update(change)
        (target / "run_manifest.json").write_text(json.dumps(manifest))
    return target


def test_runs_with_different_settings_are_not_combined(experiment, tmp_path):
    _, _, run, _ = experiment
    a = _copy_run(run, tmp_path / "a", "a-")
    b = _copy_run(run, tmp_path / "b", "b-", {"reliability_value": 0.1})
    with pytest.raises(InputError, match="features.reliability_value"):
        load_runs([a, b])


def test_repeat_labels_are_scoped_to_their_run_unless_shared(experiment, tmp_path):
    _, _, run, _ = experiment
    a = _copy_run(run, tmp_path / "a", "a-")
    b = _copy_run(run, tmp_path / "b", "b-")
    scoped = load_runs([a, b])
    assert scoped.table.groupby("condition")["repeat_id"].nunique().eq(6).all()
    assert scoped.table["repeat_id"].str.contains("/").all()
    shared = load_runs([a, b], shared_repeat_labels=True)
    assert shared.table.groupby("condition")["repeat_id"].nunique().eq(3).all()


def test_auto_mode_picks_per_slice_for_anisotropic_stacks(experiment):
    _, _, run, manifest = experiment
    assert manifest["settings"]["flow"]["mode"] == "xy_per_slice"  # Z 2.0 / XY 0.65 > 3
    fovs = pd.read_csv(run / "fovs.csv", keep_default_na=False)
    complete = fovs[fovs["status"] == "complete"]
    assert not complete["warnings"].str.contains("spatial derivative kernel").any()
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    assert frames["Nuclei__vz_mean"].isna().all()
    assert frames["undefined_features"].str.contains("no axial component").all()
    flow = next((run / "flow").iterdir())
    assert not list(flow.glob("*_vz_t*.tiff"))


def test_shallow_z_warning_is_recorded_per_fov_in_3d_mode(experiment, tmp_path):
    _, metadata, _, _ = experiment
    run = create_run(tmp_path, "xyz")
    manifest = run_experiment(
        metadata[metadata["position_id"] != "broken"].iloc[:1],
        settings(flow=FlowParameters(mode="xyz")),
        run,
    )
    assert "shorter than the spatial derivative kernel" in manifest["fovs"][0]["warnings"]


def test_3d_speed_is_refused_with_per_slice_flow(experiment, tmp_path):
    _, metadata, _, _ = experiment
    bad = settings(
        flow=FlowParameters(mode="xy_per_slice"),
        features=FeatureSettings(speed_mode="xyz", reliability_value=1e-3),
    )
    with pytest.raises(InputError, match="3D speed needs 3D optical flow"):
        run_experiment(
            metadata[metadata["position_id"] != "broken"].iloc[:1], bad, create_run(tmp_path, "bad")
        )


def test_feature_settings_are_checked_before_any_computation(experiment, tmp_path):
    _, metadata, _, _ = experiment
    run = create_run(tmp_path, "early")
    bad = settings(features=FeatureSettings(reliability_value=None))
    with pytest.raises(InputError, match="needs a value"):
        run_experiment(metadata, bad, run)
    assert not any((run / "flow").iterdir())


def test_progress_is_reported_per_fov_flow_window_and_frame(experiment, tmp_path):
    from opticalflow3d_profiler.progress import Stage, Tracker

    class Recorder(Tracker):
        def __init__(self):
            self.stages = []

        def stage(self, description, total, nested=False):
            record = {"name": description, "total": total, "done": 0}
            self.stages.append(record)

            class Counting(Stage):
                def update(self, note=""):
                    record["done"] += 1

            return Counting()

    _, metadata, _, _ = experiment
    one = metadata[metadata["position_id"] != "broken"].iloc[:1]
    recorder = Recorder()
    run_experiment(one, settings(), create_run(tmp_path, "progress"), tracker=recorder)
    names = [s["name"].split()[0] for s in recorder.stages]
    assert names == ["Fields", "Optical", "Features"]
    assert all(s["done"] == s["total"] for s in recorder.stages)
    assert recorder.stages[1]["total"] == 3  # 9 frames, tSig 1: 3 flow windows


def test_unpaired_runs_are_refused_for_morphocoverage(experiment, tmp_path):
    from opticalflow3d_profiler.coverage import Design, coverage_input

    _, _, run, _ = experiment
    ctrl = _copy_run(run, tmp_path / "c", "c-")
    drug = _copy_run(run, tmp_path / "d", "d-")
    for folder, keep in ((ctrl, "ctrl"), (drug, "drug")):
        table = folder / "features" / "features_per_fov.csv"
        data = pd.read_csv(table, dtype=str, keep_default_na=False)
        data[data["condition"] == keep].to_csv(table, index=False)
    scoped = load_runs([ctrl, drug])
    with pytest.raises(InputError, match="No biological repeat holds both"):
        coverage_input(scoped, Design("ctrl", SPEED, repeats_paired=True))
    shared = load_runs([ctrl, drug], shared_repeat_labels=True)
    assert len(coverage_input(shared, Design("ctrl", SPEED, repeats_paired=True)).objects) == 6


def test_runs_with_the_same_folder_name_are_never_paired(experiment, tmp_path):
    from opticalflow3d_profiler.coverage import Design, coverage_input

    _, _, run, _ = experiment
    ctrl = _copy_run(run, tmp_path / "batchA" / "run1", "a-")
    drug = _copy_run(run, tmp_path / "batchB" / "run1", "b-")
    for folder, keep in ((ctrl, "ctrl"), (drug, "drug")):
        table = folder / "features" / "features_per_fov.csv"
        data = pd.read_csv(table, dtype=str, keep_default_na=False)
        data[data["condition"] == keep].to_csv(table, index=False)
    combined = load_runs([ctrl, drug])
    assert combined.table["run"].nunique() == 2  # same folder name, different labels
    with pytest.raises(InputError, match="No biological repeat holds both"):
        coverage_input(combined, Design("ctrl", SPEED, repeats_paired=True))


def test_a_run_label_never_equals_another_runs_folder_name(tmp_path):
    from opticalflow3d_profiler.analysis import run_labels

    # Re-validation R4: seriesC/run-1-<hash> was given the label generated for seriesA/run-1.
    first, second = tmp_path / "seriesA" / "run-1", tmp_path / "seriesB" / "run-1"
    generated = run_labels([first, second])[first]
    third = tmp_path / "seriesC" / generated
    labels = run_labels([first, second, third])
    assert len(set(labels.values())) == 3
    assert labels[first] == generated == run_labels([first])[first]  # stable for one run
    with pytest.raises(InputError, match="same run folder"):
        run_labels([first, tmp_path / "seriesA" / "x" / ".." / "run-1"])


def test_repeated_or_shadowed_feature_columns_are_refused(experiment, tmp_path):
    _, _, run, _ = experiment
    copy = _copy_run(run, tmp_path / "copy", "c-")
    table = copy / "features" / "features_per_fov.csv"
    text = table.read_text(encoding="utf-8").splitlines()
    header = text[0].split(",")
    qc = next(c for c in header if c.startswith("qc_"))
    shadow = [",".join([*header, "Nuclei__" + qc])] + [r + "," + r.split(",")[header.index(qc)]
                                                       for r in text[1:]]  # fmt: skip
    table.write_text("\n".join(shadow) + "\n", encoding="utf-8")
    with pytest.raises(InputError, match="share a feature key"):
        load_runs([copy])
    table.write_text("\n".join([",".join([*header, qc])] + [r + ",0" for r in text[1:]]) + "\n",
                     encoding="utf-8")  # fmt: skip
    with pytest.raises(InputError, match="repeated column names"):
        load_runs([copy])


def test_a_run_folder_is_never_run_twice(experiment, tmp_path):
    import hashlib

    _, metadata, _, _ = experiment
    one = metadata[metadata["position_id"] != "broken"].iloc[:1]
    run = create_run(tmp_path, "flow-only")
    run_experiment(one, settings(), run, flow_only=True)
    digests = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (run / "run_manifest.json", run / "fovs.csv")
    }
    for flow_only in (True, False):
        with pytest.raises(InputError, match="never run twice"):
            run_experiment(one, settings(), run, flow_only=flow_only, reuse_from=run)
    assert digests == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (run / "run_manifest.json", run / "fovs.csv")
    }


def test_an_interrupted_or_concurrent_run_is_never_entered_again(experiment, tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from opticalflow3d_profiler.results import claim_run

    _, metadata, _, _ = experiment
    one = metadata[metadata["position_id"] != "broken"].iloc[:1]
    interrupted = create_run(tmp_path, "interrupted")
    claim_run(interrupted)  # a run that stopped before writing its manifest
    (interrupted / "flow" / one["fov_uid"].iloc[0]).mkdir()  # and had published a flow
    with pytest.raises(InputError, match="never run twice"):
        run_experiment(one, settings(), interrupted)
    assert not (interrupted / "run_manifest.json").exists()
    race = create_run(tmp_path, "race")
    start = threading.Barrier(8)  # all threads claim at the same moment

    def attempt(_):
        start.wait()
        try:
            claim_run(race)
            return True
        except InputError:
            return False

    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(attempt, range(8))) == 1  # exactly one claim wins


def test_the_manifest_identifies_the_profiler_source(experiment, tmp_path):
    from opticalflow3d_profiler.results import implementation_identity

    _, metadata, _, _ = experiment
    one = metadata[metadata["position_id"] != "broken"].iloc[:1]
    manifest = run_experiment(one, settings(), create_run(tmp_path, "ident"), flow_only=True)
    identity = implementation_identity()
    assert manifest["profiler"] == identity and len(identity["source_sha256"]) == 64
    assert identity["modules"] > 20


def test_default_readout_is_a_feature_with_values(experiment):
    from dataclasses import replace as replace_set

    from opticalflow3d_profiler.coverage import default_readout
    from opticalflow3d_profiler.feature_dictionary import AXIAL, FeatureDef

    _, _, run, _ = experiment
    features = load_runs([run])
    assert default_readout(features) == SPEED
    speed_3d = "Nuclei__speed_3d_median"  # 3D speed without full calibration: all NaN
    table = features.table.assign(**{speed_3d: float("nan")})
    axial = FeatureDef(speed_3d, "magnitude", "", "", "lateral", "fov", "", AXIAL, "")
    undefined = replace_set(features, table=table, fov_defs=[axial, *features.fov_defs])
    assert default_readout(undefined) == SPEED


def test_the_report_server_serves_only_files_inside_its_folder(tmp_path):
    # Re-validation E24: no listing, no '..', no symbolic link out of the folder.
    import urllib.error
    import urllib.request

    from opticalflow3d_profiler.report_link import serve

    folder = tmp_path / "report"
    folder.mkdir()
    (folder / "report.html").write_text("<p>ok</p>")
    secret = tmp_path / "secret.txt"
    secret.write_text("outside")
    (folder / "link.txt").symlink_to(secret)
    port = serve(folder)
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never a proxy

    def status(path):
        try:
            with direct.open(f"http://127.0.0.1:{port}{path}") as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    assert status("/report.html") == 200
    assert {status(p) for p in ("/", "/link.txt", "/../secret.txt", "/%2e%2e/secret.txt")} == {404}


def test_an_undefined_brightness_change_gets_the_reason_its_record_supports():
    from opticalflow3d_profiler.pipeline import brightness_reason

    assert "older result" in brightness_reason({})
    assert "cause is not recorded" in brightness_reason({"brightness_change_per_frame": None})
    nan = brightness_reason({"brightness_change_per_frame": float("nan")})
    assert "central frame" in nan


def test_shared_repeat_labels_are_named_for_the_user():
    from opticalflow3d_profiler.notebook_analysis_ui import shared_repeats

    table = pd.DataFrame(
        {"run": ["A", "B", "A", "B"], "biological_repeat": ["r1", "r1", "r2", "r3"]}
    )
    assert shared_repeats(table) == {"r1": ["A", "B"]}


def test_invalid_sigmas_are_refused_before_a_run_folder_is_claimed(experiment, tmp_path):
    from opticalflow3d_profiler.pipeline import checked_settings

    _, metadata, _, _ = experiment
    bad = settings(flow=FlowParameters(mode="xyz", t_sig=0))
    with pytest.raises(InputError, match="invalid_sigma|positive numbers"):
        checked_settings(bad)
    run = create_run(tmp_path, "sigma")
    with pytest.raises(InputError):
        run_experiment(metadata.iloc[:1], bad, run)
    assert not (run / "run_started.json").exists()  # the folder stays usable


def test_refusing_a_finished_run_never_writes_into_it(tmp_path):
    # Round 3: a run older than the claim (manifest, no run_started.json) got an empty claim.
    from opticalflow3d_profiler.results import claim_run

    legacy = create_run(tmp_path, "legacy")
    (legacy / "run_manifest.json").write_text("{}")
    before = sorted(p.name for p in legacy.iterdir())
    with pytest.raises(InputError, match="never run twice"):
        claim_run(legacy)
    assert sorted(p.name for p in legacy.iterdir()) == before
