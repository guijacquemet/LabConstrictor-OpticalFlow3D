"""End-to-end demonstration on synthetic data with a known answer (orchestration).

:func:`run_demo` writes a small synthetic experiment, runs every step of the app on it and
checks the results against the ground truth:

- condition ``ctrl``: nuclei move at 0.3 px/frame in random XY directions;
- condition ``drug``: nuclei move at 0.6 px/frame, all within ±15° of +x (collective motion);
- 3 biological repeats x 2 fields of view per condition, written in the MorphoBricks
  layout ``experiment/<condition>/<repeat>/<fov>.tif`` (technical repeat ``single``), plus
  one unreadable TIFF (its failure must be recorded, not skipped).

Every intermediate file is kept: input TIFFs, optical-flow TIFFs and
manifests, feature tables, QC figures, PCA and comparison exports, and ``demo_report.md``
with each expectation, its observed value and PASS or FAIL. Expected ranges for speeds
include the documented gain bias of the 3D algorithm (docs/validation.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd
import tifffile

from . import figures
from .analysis import analyse, compare_conditions, export_analysis, load_runs
from .comparison import ComparisonSettings
from .config import Calibration, FeatureSettings, FlowParameters, ForegroundSpec, to_record
from .experiment import read_experiment_folder
from .flow_store import open_result
from .naming import ColumnNames
from .pipeline import RunSettings, run_experiment
from .profile_analysis import PcaSettings
from .qc_export import export_qc_figures
from .results import create_run, write_csv, write_text_atomic
from .synthetic import SyntheticMovie, render

BROKEN = "fov9_unreadable"
OBJECT_SET = "Nuclei"
NAMES = ColumnNames(OBJECT_SET)
CONDITIONS = {"ctrl": (0.3, 360.0), "drug": (0.6, 30.0)}
"""Condition -> (XY speed in px/frame, direction spread in degrees)."""


@dataclass(frozen=True)
class DemoDesign:
    """Size and content of the synthetic experiment."""

    shape: tuple[int, int, int, int] = (15, 11, 256, 256)
    n_nuclei: int = 80
    sigma_xy: float = 5.0
    sigma_z: float = 1.5
    noise_sd: float = 20.0
    repeats: int = 3
    fovs_per_repeat: int = 2
    calibration: Calibration = field(
        default_factory=lambda: Calibration(0.65, 0.65, 2.0, 1.0, source="synthetic design")
    )
    reliability_threshold: float = 50.0
    intensity_threshold: float = 300.0
    drift_tolerance: float = 0.01
    axial_floor_tolerance: float = 0.03

    @classmethod
    def small(cls) -> DemoDesign:
        """Return the quick 96 x 96 design (about 1.5 min).

        With 14 nuclei per image the axial statistics are noisier, so their tolerances are
        2.5x and 1.5x wider (measured: drift 0.0106 and noise floor 0.0275 slice/frame,
        against 0.0022 and 0.0196 at full size).
        """
        return cls(
            shape=(15, 11, 96, 96), n_nuclei=14, drift_tolerance=0.025, axial_floor_tolerance=0.045
        )


def _write_fov(
    folder: Path, design: DemoDesign, condition: str, rep: int, fov: int, seed: int
) -> dict[str, str]:
    """Write one synthetic single-channel image; return its labels."""
    speed, spread = CONDITIONS[condition]
    movie = SyntheticMovie(
        design.shape,
        design.n_nuclei,
        (0.0, 0.0, speed),
        spread,
        design.sigma_xy,
        design.sigma_z,
        noise_sd=design.noise_sd,
        seed=seed,
    )
    relative = Path(condition) / f"rep{rep}" / f"fov{fov}.tif"
    image = folder / "experiment" / relative
    image.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(image, render(movie), imagej=True, metadata={"axes": "TZYX"})
    return {"condition": condition, "biological_repeat": f"rep{rep}", "position_id": f"fov{fov}"}


def write_experiment(folder: Path, design: DemoDesign) -> Path:
    """Write the synthetic experiment folder and its ground truth.

    Returns
    -------
    pathlib.Path
        The experiment folder (MorphoBricks layout).
    """
    rows = []
    for condition in CONDITIONS:
        for rep in range(1, design.repeats + 1):
            for fov in range(1, design.fovs_per_repeat + 1):
                rows.append(_write_fov(folder, design, condition, rep, fov, len(rows) + 1))
    (folder / "experiment" / "ctrl" / "rep1" / f"{BROKEN}.tif").write_bytes(b"not a TIFF file")
    path = folder / "experiment"
    truth = {
        "conditions": {
            c: {"xy_speed_px_per_frame": s, "direction_spread_deg": d, "direction_deg": 0.0}
            for c, (s, d) in CONDITIONS.items()
        },
        "design": to_record(design),
        "fields_of_view": rows,
    }
    (folder / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return path


@dataclass
class Checks:
    """Expectations with observed values."""

    rows: list[dict[str, object]] = field(default_factory=list)

    def add(self, name: str, expected: str, observed: object, passed: bool) -> None:
        """Record one expectation."""
        self.rows.append(
            {
                "check": name,
                "expected": expected,
                "observed": observed,
                "result": "PASS" if passed else "FAIL",
            }
        )

    @property
    def passed(self) -> bool:
        """Return True when every expectation passed."""
        return all(r["result"] == "PASS" for r in self.rows)


def _condition_means(table: pd.DataFrame, column: str) -> dict[str, float]:
    """Return the mean over fields of view of a column per condition."""
    return table.groupby("condition")[column].mean().to_dict()


def _check_status(checks: Checks, run: Path, design: DemoDesign) -> None:
    """Check field-of-view statuses and the saved optical-flow outputs."""
    fovs = pd.read_csv(run / "fovs.csv")
    n_real = len(CONDITIONS) * design.repeats * design.fovs_per_repeat
    complete = fovs[fovs["status"] == "complete"]
    failed = fovs[fovs["status"] == "failed"]
    checks.add("fields of view completed", f"{n_real}", len(complete), len(complete) == n_real)
    checks.add(
        "unreadable TIFF recorded as failed",
        f"1 failure ({BROKEN})",
        f"{len(failed)}: {failed['position_id'].tolist()}",
        len(failed) == 1 and failed["position_id"].iloc[0] == BROKEN,
    )
    half = FlowParameters().half_window
    expected = list(range(half, design.shape[0] - half))
    frames_ok = all(
        [f.source_frame for f in open_result(run / "flow" / u).frames] == expected
        for u in complete["fov_uid"]
    )
    checks.add(
        "optical-flow outputs per FOV (verified hashes)",
        f"source frames {expected}",
        "all FOVs" if frames_ok else "mismatch",
        frames_ok,
    )


def _check_motion(checks: Checks, per_fov: pd.DataFrame, design: DemoDesign) -> None:
    """Check recovered speed, coherence and direction against the ground truth."""
    scale = design.calibration.pixel_size_x / design.calibration.frame_interval
    speed = _condition_means(per_fov, NAMES.column("speed_xy_median"))
    ratio = speed["drug"] / speed["ctrl"]
    checks.add("speed ratio drug/ctrl", "1.5-2.6 (true 2.0)", round(ratio, 3), 1.5 <= ratio <= 2.6)
    for condition, (true_speed, _) in CONDITIONS.items():
        gain = speed[condition] / (true_speed * scale)
        checks.add(
            f"speed gain {condition} (recovered/true)",
            "0.4-1.0 (documented 3D bias)",
            round(gain, 3),
            0.4 <= gain <= 1.0,
        )
    coherence = _condition_means(per_fov, NAMES.column("coherence_xy_global"))
    checks.add(
        "global XY coherence drug", "> 0.8", round(coherence["drug"], 3), coherence["drug"] > 0.8
    )
    checks.add(
        "global XY coherence ctrl", "< 0.35", round(coherence["ctrl"], 3), coherence["ctrl"] < 0.35
    )
    direction = per_fov.loc[
        per_fov["condition"] == "drug", NAMES.column("xy_dominant_direction_deg")
    ]
    checks.add(
        "dominant direction drug",
        "within ±15° of 0°",
        round(float(direction.abs().max()), 2),
        bool((direction.abs() < 15).all()),
    )


def _check_axial_and_confounders(checks: Checks, per_fov: pd.DataFrame, design: DemoDesign) -> None:
    """Check the axial noise floor (true vz = 0) and the nuclear-size confounder."""
    z_scale = design.calibration.pixel_size_z / design.calibration.frame_interval
    drift = float((per_fov[NAMES.column("vz_mean")] / z_scale).abs().max())
    checks.add(
        "net axial drift (true vz = 0)",
        f"|mean vz| < {design.drift_tolerance:g} slice/frame",
        round(drift, 4),
        drift < design.drift_tolerance,
    )
    floor = float((per_fov[NAMES.column("vz_abs_mean")] / z_scale).max())
    checks.add(
        "axial noise floor (true vz = 0)",
        f"mean|vz| < {design.axial_floor_tolerance:g} slice/frame",
        round(floor, 4),
        floor < design.axial_floor_tolerance,
    )
    size = _condition_means(per_fov, "qc_object_mean_voxels")
    size_ratio = size["drug"] / size["ctrl"]
    checks.add(
        "confounder: nuclear object size drug/ctrl",
        "0.8-1.25",
        round(size_ratio, 3),
        0.8 <= size_ratio <= 1.25,
    )


def check_run(checks: Checks, run: Path, design: DemoDesign) -> pd.DataFrame:
    """Check statuses, flow outputs and feature values of the main run."""
    _check_status(checks, run, design)
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    _check_motion(checks, per_fov, design)
    _check_axial_and_confounders(checks, per_fov, design)
    return per_fov


def check_analysis(checks: Checks, run: Path, out: Path, design: DemoDesign) -> None:
    """Run and check the PCA and the condition comparison; export them with figures."""
    features = load_runs([run])
    settings = PcaSettings()
    result = analyse(features, settings)
    comparison_settings = ComparisonSettings("ctrl")
    comparison = compare_conditions(features, comparison_settings)
    export_analysis(out, features, settings, result, comparison, comparison_settings)
    figures.save(
        figures.pca_scatter(result.scores, result.explained_variance_ratio),
        out / "figures" / "pca_pc1_pc2.png",
    )
    figures.save(figures.pca_loadings(result.loadings), out / "figures" / "pca_loadings.png")
    figures.save(
        figures.correlation_heatmap(result.prepared.matrix.corr()),
        out / "figures" / "feature_correlation.png",
    )
    for key in ("speed_xy_median", "coherence_xy_global"):
        figures.save(
            figures.condition_plot(features.table, NAMES.column(key), key),
            out / "figures" / f"condition_{key}.png",
        )
    pc1 = result.scores.groupby("condition")["PC1"]
    separated = pc1.max().min() < pc1.min().max()
    checks.add(
        "PCA: PC1 separates the conditions",
        "no overlap on PC1",
        f"ranges {pc1.min().round(2).to_dict()} to {pc1.max().round(2).to_dict()}",
        bool(separated),
    )
    tests = comparison[0].set_index("feature")
    coherence = tests.loc[NAMES.column("coherence_xy_global")]
    checks.add(
        "comparison: FOVs and paired repeats",
        f"{design.repeats * design.fovs_per_repeat} FOVs a side, {design.repeats} repeats paired",
        f"{coherence['fovs']}/{coherence['control_fovs']} FOVs, "
        f"{coherence['repeats_paired']} repeats",
        coherence["repeats_paired"] == design.repeats
        and coherence["fovs"] == design.repeats * design.fovs_per_repeat,
    )
    checks.add(
        "comparison: coherence higher in drug in every repeat",
        "d > 0, q_screen <= 0.05, direction +++",
        f"d {coherence['d_fovs']:.2f}, q {coherence['q_screen']:.4f}, "
        f"{coherence['direction_per_repeat']}",
        coherence["d_fovs"] > 0
        and coherence["q_screen"] <= 0.05
        and coherence["direction_per_repeat"] == "+" * design.repeats,
    )


def check_reuse_run(checks: Checks, run: Path, whole_run: Path) -> None:
    """Check that a whole-image re-extraction reused the verified flow and is named ``whole``."""
    manifest = json.loads((whole_run / "run_manifest.json").read_text(encoding="utf-8"))
    done = [f for f in manifest["fovs"] if f["status"] == "complete"]
    reused = all(str(f["flow_origin"]).startswith("reused") for f in done)
    checks.add(
        "re-extraction reuses verified flow",
        "no optical flow recomputed",
        f"{len(done)} reused" if reused else "recomputed",
        reused and bool(done),
    )
    columns = pd.read_csv(whole_run / "features" / "features_per_fov.csv", nrows=1).columns
    checks.add(
        "whole-image columns (no foreground)",
        "whole__speed_xy_median",
        "present" if "whole__speed_xy_median" in columns else "missing",
        "whole__speed_xy_median" in columns,
    )
    del run


def markdown_table(table: pd.DataFrame) -> str:
    """Return a DataFrame as a Markdown table (no extra dependency)."""
    lines = ["| " + " | ".join(table.columns) + " |", "|" + "---|" * len(table.columns)]
    for row in table.itertuples(index=False):
        lines.append("| " + " | ".join(str(v).replace("|", "/") for v in row) + " |")
    return "\n".join(lines)


def run_demo(
    folder: Path, design: DemoDesign | None = None, progress: Callable[[str], None] = print
) -> Checks:
    """Write the synthetic experiment, run every step and check the results.

    Parameters
    ----------
    folder
        New, empty folder for everything the demo writes.
    design
        Experiment size and content (default: 256 x 256 x 11 x 15, 12 fields of view).
    progress
        Callback for progress lines.

    Returns
    -------
    Checks
        Every expectation with its observed value; also written to ``demo_report.md``.
    """
    design = design or DemoDesign()
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise ValueError(f"{folder} is not empty; the demo writes into a new folder.")
    progress("Writing the synthetic experiment folder...")
    metadata = read_experiment_folder(write_experiment(folder, design))
    features = FeatureSettings(
        reliability_value=design.reliability_threshold, region_size_px=64, min_region_voxels=100
    )
    settings = RunSettings(
        "TZYX",
        None,
        design.calibration,
        FlowParameters(mode="xyz"),  # the demo validates the 3D engine, including Z
        features=features,
        foreground=ForegroundSpec("threshold", design.intensity_threshold),
        object_set=OBJECT_SET,
    )
    run = create_run(folder / "results", "run-threshold")
    progress("Step 2: optical flow...")
    run_experiment(metadata, settings, run, progress=progress, flow_only=True)
    progress("Step 3: features (intensity-threshold foreground)...")
    run_experiment(metadata, settings, run, reuse_from=run, progress=progress)
    progress("Saving QC figures...")
    export_qc_figures(run, settings)
    checks = Checks()
    check_run(checks, run, design)
    progress("Step 4-5: PCA, comparison and export...")
    check_analysis(checks, run, run / "analysis" / "demo", design)
    progress("Re-extraction on the whole image (reusing the flow)...")
    whole_run = create_run(folder / "results", "run-whole-image")
    run_experiment(
        metadata, replace(settings, foreground=ForegroundSpec()), whole_run, reuse_from=run
    )
    check_reuse_run(checks, run, whole_run)
    report = pd.DataFrame(checks.rows)
    write_csv(folder / "expectations.csv", report)
    verdict = "ALL EXPECTATIONS PASSED" if checks.passed else "SOME EXPECTATIONS FAILED"
    write_text_atomic(
        folder / "demo_report.md",
        f"# Synthetic demo: {verdict}\n\n" + markdown_table(report) + "\n",
    )
    progress(f"{verdict}. Report: {folder / 'demo_report.md'}")
    return checks
