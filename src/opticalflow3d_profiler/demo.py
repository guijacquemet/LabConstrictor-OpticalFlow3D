"""End-to-end demonstration on synthetic data with a known answer (orchestration).

:func:`run_demo` writes a small synthetic experiment, runs every step of the app on it and
checks the results against the ground truth:

- condition ``ctrl``: nuclei move at 0.3 px/frame in random XY directions;
- condition ``drug``: nuclei move at 0.6 px/frame, all within ±15° of +x (collective motion);
- 3 biological repeats x 2 fields of view per condition, plus one listed file that does not
  exist (its failure must be recorded, not skipped).

Every intermediate file is kept: input TIFFs, ground-truth masks, optical-flow TIFFs and
manifests, feature tables, QC figures, PCA and comparison exports, and ``demo_report.md``
with each expectation, its observed value and PASS or FAIL. Expected ranges for speeds
include the documented gain bias of the 3D algorithm (docs/validation.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile

from . import figures
from .analysis import analyse, compare_conditions, export_analysis, load_runs
from .config import Calibration, FeatureSettings, ForegroundSpec, to_record
from .experiment import read_metadata
from .flow_store import open_result
from .pipeline import RunSettings, run_experiment
from .profile_analysis import PcaSettings
from .qc_export import export_qc_figures
from .results import create_run, write_csv, write_text_atomic
from .synthetic import SyntheticMovie, render

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


def write_experiment(folder: Path, design: DemoDesign) -> Path:
    """Write the synthetic images, ground-truth masks and metadata CSV.

    Returns
    -------
    pathlib.Path
        The metadata CSV.
    """
    rows, seed = [], 0
    for condition, (speed, spread) in CONDITIONS.items():
        for rep in range(1, design.repeats + 1):
            for fov in range(1, design.fovs_per_repeat + 1):
                seed += 1
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
                name = f"{condition}_rep{rep}_fov{fov}"
                image = folder / "images" / f"{name}.tif"
                mask = folder / "masks" / f"{name}_mask.tif"
                for path in (image, mask):
                    path.parent.mkdir(parents=True, exist_ok=True)
                tifffile.imwrite(image, render(movie), imagej=True, metadata={"axes": "TZYX"})
                truth = render(replace(movie, noise_sd=0.0), dtype="float64")
                tifffile.imwrite(
                    mask,
                    (truth > movie.background + 0.3 * movie.amplitude).astype(np.uint8),
                    imagej=True,
                    metadata={"axes": "TZYX"},
                )
                rows.append(
                    {
                        "sample_id": name,
                        "position_id": f"pos{fov}",
                        "condition": condition,
                        "biological_repeat": f"rep{rep}",
                        "technical_repeat": "t1",
                        "batch": f"day{rep}",
                        "input_path": f"images/{name}.tif",
                        "mask_path": f"masks/{name}_mask.tif",
                    }
                )
    rows.append(
        {
            **rows[0],
            "sample_id": "missing_file",
            "position_id": "pos9",
            "input_path": "images/does_not_exist.tif",
            "mask_path": "",
        }
    )
    path = folder / "metadata.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    (folder / "ground_truth.json").write_text(
        json.dumps(
            {
                "conditions": {
                    c: {"xy_speed_px_per_frame": s, "direction_spread_deg": d, "direction_deg": 0.0}
                    for c, (s, d) in CONDITIONS.items()
                },
                "design": to_record(design),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
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
    """Return the mean of biological-repeat means of a column per condition."""
    reps = table.groupby(["condition", "biological_repeat"])[column].mean()
    return reps.groupby(level=0).mean().to_dict()


def check_run(checks: Checks, run: Path, design: DemoDesign) -> pd.DataFrame:
    """Check statuses, flow outputs and feature values of the main run."""
    fovs = pd.read_csv(run / "fovs.csv")
    n_real = len(CONDITIONS) * design.repeats * design.fovs_per_repeat
    complete = fovs[fovs["status"] == "complete"]
    failed = fovs[fovs["status"] == "failed"]
    checks.add("fields of view completed", f"{n_real}", len(complete), len(complete) == n_real)
    checks.add(
        "missing file recorded as failed",
        "1 failure, 'does not exist'",
        f"{len(failed)}: {failed['message'].tolist()}",
        len(failed) == 1 and "does not exist" in failed["message"].iloc[0],
    )
    half = 3
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
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    scale = design.calibration.pixel_size_x / design.calibration.frame_interval
    speed = _condition_means(per_fov, "speed_xy_median__tmean")
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
    coherence = _condition_means(per_fov, "coherence_xy_global__tmean")
    checks.add(
        "global XY coherence drug", "> 0.8", round(coherence["drug"], 3), coherence["drug"] > 0.8
    )
    checks.add(
        "global XY coherence ctrl", "< 0.35", round(coherence["ctrl"], 3), coherence["ctrl"] < 0.35
    )
    direction = per_fov.loc[per_fov["condition"] == "drug", "xy_dominant_direction_deg__tcircmean"]
    checks.add(
        "dominant direction drug",
        "within ±15° of 0°",
        round(float(direction.abs().max()), 2),
        bool((direction.abs() < 15).all()),
    )
    z_scale = design.calibration.pixel_size_z / design.calibration.frame_interval
    drift = float((per_fov["vz_mean__tmean"] / z_scale).abs().max())
    checks.add(
        "net axial drift (true vz = 0)",
        "|mean vz| < 0.01 slice/frame",
        round(drift, 4),
        drift < 0.01,
    )
    floor = float((per_fov["vz_abs_mean__tmean"] / z_scale).max())
    checks.add(
        "axial noise floor (true vz = 0)",
        "mean|vz| < 0.03 slice/frame",
        round(floor, 4),
        floor < 0.03,
    )
    size = _condition_means(per_fov, "qc_object_mean_voxels__tmean")
    size_ratio = size["drug"] / size["ctrl"]
    checks.add(
        "confounder: nuclear object size drug/ctrl",
        "0.8-1.25",
        round(size_ratio, 3),
        0.8 <= size_ratio <= 1.25,
    )
    return per_fov


def check_analysis(checks: Checks, run: Path, out: Path, design: DemoDesign) -> None:
    """Run and check the PCA and the condition comparison; export them with figures."""
    features = load_runs([run])
    settings = PcaSettings()
    result = analyse(features, settings)
    comparison = compare_conditions(features, "ctrl", "drug")
    export_analysis(out, features, settings, result, comparison)
    figures.save(
        figures.pca_scatter(result.scores, result.explained_variance_ratio),
        out / "figures" / "pca_pc1_pc2.png",
    )
    figures.save(figures.pca_loadings(result.loadings), out / "figures" / "pca_loadings.png")
    figures.save(
        figures.correlation_heatmap(result.prepared.matrix.corr()),
        out / "figures" / "feature_correlation.png",
    )
    for _, row in comparison[comparison["role"] == "readout"].iterrows():
        figures.save(
            figures.condition_plot(features.table, row["feature"], row["readout"]),
            out / "figures" / f"condition_{row['feature']}.png",
        )
    pc1 = result.scores.groupby("condition")["PC1"]
    separated = pc1.max().min() < pc1.min().max()
    checks.add(
        "PCA: PC1 separates the conditions",
        "no overlap on PC1",
        f"ranges {pc1.min().round(2).to_dict()} to {pc1.max().round(2).to_dict()}",
        bool(separated),
    )
    readouts = comparison.set_index("readout")
    tested = readouts.loc["median motion magnitude"]
    checks.add(
        "comparison at repeat level",
        f"{design.repeats} repeats per condition, Welch",
        f"{tested['n_repeats_control']}/{tested['n_repeats_treatment']}, {tested['test']}",
        tested["n_repeats_control"] == design.repeats and tested["test"].startswith("Welch"),
    )
    checks.add(
        "comparison: coherence higher in drug",
        "difference > 0",
        round(float(readouts.loc["directional coherence", "difference"]), 3),
        readouts.loc["directional coherence", "difference"] > 0,
    )


def check_mask_run(
    checks: Checks, run: Path, mask_run: Path, threshold_table: pd.DataFrame
) -> None:
    """Check that the ground-truth-mask run reused the flow and agrees with the threshold run."""
    manifest = json.loads((mask_run / "run_manifest.json").read_text(encoding="utf-8"))
    done = [f for f in manifest["fovs"] if f["status"] == "complete"]
    reused = all(str(f["flow_origin"]).startswith("reused") for f in done)
    checks.add(
        "mask run reuses verified flow",
        "no optical flow recomputed",
        f"{len(done)} reused" if reused else "recomputed",
        reused and bool(done),
    )
    masked = pd.read_csv(mask_run / "features" / "features_per_fov.csv")
    merged = threshold_table.merge(masked, on="fov_uid", suffixes=("_thr", "_mask"))
    diff = (merged["speed_xy_median__tmean_mask"] / merged["speed_xy_median__tmean_thr"] - 1).abs()
    checks.add(
        "threshold vs ground-truth mask: median speed",
        "relative difference < 20%",
        round(float(diff.max()), 3),
        bool(diff.max() < 0.2),
    )


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
    progress("Writing synthetic images and ground-truth masks...")
    metadata = read_metadata(write_experiment(folder, design))
    features = FeatureSettings(
        reliability_value=design.reliability_threshold, region_size_px=64, min_region_voxels=100
    )
    settings = RunSettings(
        "TZYX",
        None,
        design.calibration,
        features=features,
        foreground=ForegroundSpec("threshold", design.intensity_threshold),
    )
    run = create_run(folder / "results", "run-threshold")
    progress("Step 2: optical flow...")
    run_experiment(metadata, settings, run, progress=progress, flow_only=True)
    progress("Step 3: features (intensity-threshold foreground)...")
    run_experiment(metadata, settings, run, reuse_from=run, progress=progress)
    progress("Saving QC figures...")
    export_qc_figures(run, settings)
    checks = Checks()
    threshold_table = check_run(checks, run, design)
    progress("Step 4-5: PCA, comparison and export...")
    check_analysis(checks, run, run / "analysis" / "demo", design)
    progress("Re-extraction with ground-truth masks (reusing the flow)...")
    mask_settings = replace(settings, foreground=ForegroundSpec("mask", mask_axes="TZYX"))
    mask_run = create_run(folder / "results", "run-truth-masks")
    run_experiment(metadata, mask_settings, mask_run, reuse_from=run, progress=progress)
    check_mask_run(checks, run, mask_run, threshold_table)
    report = pd.DataFrame(checks.rows)
    write_csv(folder / "expectations.csv", report)
    verdict = "ALL EXPECTATIONS PASSED" if checks.passed else "SOME EXPECTATIONS FAILED"
    write_text_atomic(
        folder / "demo_report.md",
        f"# Synthetic demo: {verdict}\n\n" + markdown_table(report) + "\n",
    )
    progress(f"{verdict}. Report: {folder / 'demo_report.md'}")
    return checks
