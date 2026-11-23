"""ipywidgets interface of steps 3 to 5: features, comparison and export (UI).

As in :mod:`notebook_ui`, the widgets only collect choices and call the package.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import ipywidgets as widgets
import pandas as pd
from IPython.display import display

from . import figures
from .analysis import analyse, compare_conditions, export_analysis, load_runs
from .config import FeatureSettings, ForegroundSpec
from .experiment import replicate_counts
from .external import external_features
from .notebook_ui import (
    METADATA_FIELDS,
    STYLE,
    FlowStep,
    LoadStep,
    Session,
    button,
    guarded,
    number,
    show,
    text,
)
from .pipeline import RunSettings, run_experiment
from .profile_analysis import PcaSettings
from .results import create_run
from .validation import InputError

FAMILIES = ("magnitude", "components", "collective", "spatial")


class FeatureStep:
    """Step 3: foreground, reliability and feature settings, then extraction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.fg_mode = widgets.Dropdown(
            options=[
                ("none (exploratory)", "none"),
                ("intensity threshold", "threshold"),
                ("mask file", "mask"),
            ],
            description="Foreground",
            style=STYLE,
        )
        self.threshold = text("Raw-intensity threshold")
        self.mask_path = text("Mask file (or mask_path column)")
        self.mask_axes = widgets.Dropdown(
            options=["", "TZYX", "ZYX", "YX"], style=STYLE, description="Mask axes"
        )
        self.mask_rule = widgets.Checkbox(description="Use a 2D mask for every Z slice")
        self.rel_mode = widgets.Dropdown(
            options=["absolute", "percentile", "none"],
            description="Reliability filter",
            style=STYLE,
        )
        self.rel_value = text("Reliability value", placeholder="threshold or percentile")
        self.speed = widgets.Dropdown(
            options=[("XY speed (recommended)", "xy"), ("3D speed (experimental)", "xyz")],
            description="Speed",
            style=STYLE,
        )
        self.region = widgets.IntText(value=128, description="Region size (px)", style=STYLE)
        self.window = widgets.IntText(value=15, description="Local window (px)", style=STYLE)
        self.motion = text("Moving-region threshold", placeholder="optional, feature units")
        self.new_run = text("New run name (re-extraction)", placeholder="optional")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the step's widget tree."""
        run = button("Extract features")
        run.on_click(guarded(self.output, self.extract))
        return widgets.VBox(
            [
                self.fg_mode,
                self.threshold,
                self.mask_path,
                self.mask_axes,
                self.mask_rule,
                self.rel_mode,
                self.rel_value,
                self.speed,
                widgets.HBox([self.region, self.window]),
                self.motion,
                self.new_run,
                run,
                self.output,
            ]
        )

    def settings(self) -> tuple[FeatureSettings, ForegroundSpec]:
        """Return the feature and foreground settings from the widgets."""
        features = FeatureSettings(
            speed_mode=self.speed.value,
            reliability_mode=self.rel_mode.value,
            reliability_value=number(self.rel_value.value),
            region_size_px=self.region.value,
            local_window_px=self.window.value,
            motion_threshold=number(self.motion.value),
        )
        mask = self.mask_path.value.strip()
        foreground = ForegroundSpec(
            self.fg_mode.value,
            number(self.threshold.value),
            Path(mask) if mask else None,
            self.mask_axes.value,
            "same_mask_for_every_z" if self.mask_rule.value else "",
        )
        return features, foreground

    def extract(self) -> None:
        """Extract features for every field of view of the run (flow reused, verified)."""
        session = self.session
        if session.run_dir is None or session.settings is None:
            raise InputError("Run step 2 first.")
        features, foreground = self.settings()
        settings = replace(session.settings, features=features, foreground=foreground)
        run_dir = session.run_dir
        if self.new_run.value.strip():
            run_dir = create_run(run_dir.parent, self.new_run.value.strip())
        manifest = run_experiment(
            session.metadata, settings, run_dir, reuse_from=session.run_dir, progress=print
        )
        session.run_dir, session.settings = run_dir, settings
        print(
            pd.DataFrame(manifest["fovs"])[["fov_uid", "status", "warnings", "message"]].to_string()
        )
        table = run_dir / "features" / "features_per_frame.csv"
        if table.exists():
            frames = pd.read_csv(table)
            prefix = "speed_3d" if features.speed_mode == "xyz" else "speed_xy"
            show(
                figures.feature_histograms(
                    frames, [f"{prefix}_median", "coherence_xy_global", "qc_reliable_fraction"]
                )
            )


class CompareStep:
    """Step 4: combine runs, PCA and condition comparison."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.runs = widgets.Textarea(
            description="Run folders",
            style=STYLE,
            placeholder="one per line (default: current run)",
            layout=widgets.Layout(width="90%", height="80px"),
        )
        self.families = widgets.SelectMultiple(
            options=FAMILIES, value=FAMILIES, description="Feature families", style=STYLE
        )
        self.axial = widgets.Checkbox(description="Include experimental axial features")
        self.missing = widgets.Dropdown(
            options=[
                ("drop features with missing values", "drop_features"),
                ("drop FOVs with missing values", "drop_fovs"),
            ],
            description="Missing values",
            style=STYLE,
        )
        self.control = widgets.Dropdown(description="Control", style=STYLE)
        self.treatment = widgets.Dropdown(description="Treatment", style=STYLE)
        self.paired = widgets.Checkbox(description="Repeats are paired across conditions")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the step's widget tree."""
        pca, compare = button("Run PCA"), button("Compare conditions")
        pca.on_click(guarded(self.output, self.pca))
        compare.on_click(guarded(self.output, self.compare))
        return widgets.VBox(
            [
                self.runs,
                self.families,
                self.axial,
                self.missing,
                pca,
                widgets.HBox([self.control, self.treatment]),
                self.paired,
                compare,
                self.output,
            ]
        )

    def features(self) -> object:
        """Load the per-FOV tables of the listed runs (or of the current run)."""
        listed = [Path(p.strip()) for p in self.runs.value.splitlines() if p.strip()]
        if not listed and self.session.run_dir is None:
            raise InputError("List at least one run folder.")
        features = load_runs(listed or [self.session.run_dir])
        conditions = sorted(features.table["condition"].unique())
        self.control.options = self.treatment.options = conditions
        self.session.analysis["features"] = features
        return features

    def pca(self) -> None:
        """Run and display the exploratory PCA."""
        features = self.features()
        settings = PcaSettings(tuple(self.families.value), self.axial.value, self.missing.value)
        result = analyse(features, settings)
        self.session.analysis.update(pca=result, pca_settings=settings)
        display(replicate_counts(features.table))
        for warning in result.prepared.warnings:
            print("⚠️", warning)
        print(
            f"{result.prepared.matrix.shape[1]} features used; "
            f"{len(result.prepared.excluded_features)} excluded (listed in the export)."
        )
        show(figures.pca_scatter(result.scores, result.explained_variance_ratio))
        show(figures.pca_loadings(result.loadings, "PC1"))
        show(figures.correlation_heatmap(result.prepared.matrix.corr()))

    def compare(self) -> None:
        """Compare the two chosen conditions on the default readouts."""
        features = self.session.analysis.get("features") or self.features()
        if self.control.value == self.treatment.value:
            raise InputError("Choose two different conditions.")
        table = compare_conditions(
            features, self.control.value, self.treatment.value, self.paired.value
        )
        self.session.analysis["comparison"] = table
        display(
            table[
                [
                    "role",
                    "readout",
                    "n_repeats_control",
                    "n_repeats_treatment",
                    "mean_control",
                    "mean_treatment",
                    "difference",
                    "hedges_g",
                    "test",
                    "p_value",
                ]
            ]
        )
        for _, row in table[table["role"] == "readout"].iterrows():
            unit = features.units["lateral"] if "speed" in row["feature"] else ""
            show(figures.condition_plot(features.table, row["feature"], row["readout"], unit))


class ExportStep:
    """Step 5: write the analysis tables and figures into a new analysis folder."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.name = text("Analysis name", "analysis-1")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the step's widget tree."""
        export = button("Export results")
        export.on_click(guarded(self.output, self.export))
        return widgets.VBox([self.name, export, self.output])

    def export(self) -> None:
        """Export PCA, comparison, settings and figures; never overwrite an analysis."""
        analysis = self.session.analysis
        if "pca" not in analysis:
            raise InputError("Run the PCA in step 4 first.")
        out = self.session.run_dir / "analysis" / self.name.value.strip()
        if out.exists():
            raise InputError(f"{out} exists; choose another analysis name.")
        features, result = analysis["features"], analysis["pca"]
        export_analysis(out, features, analysis["pca_settings"], result, analysis.get("comparison"))
        figures.save(
            figures.pca_scatter(result.scores, result.explained_variance_ratio),
            out / "figures" / "pca_pc1_pc2.png",
        )
        figures.save(figures.pca_loadings(result.loadings), out / "figures" / "pca_loadings.png")
        figures.save(
            figures.correlation_heatmap(result.prepared.matrix.corr()),
            out / "figures" / "feature_correlation.png",
        )
        comparison = analysis.get("comparison")
        if comparison is not None:
            for _, row in comparison[comparison["role"] == "readout"].iterrows():
                figures.save(
                    figures.condition_plot(features.table, row["feature"], row["readout"]),
                    out / "figures" / f"condition_{row['feature']}.png",
                )
        print(
            f"Exported to {out}. Feature tables, the feature dictionary and the run "
            f"manifest are in {self.session.run_dir}."
        )


class ExternalStep:
    """Optional: features from a folder written earlier by upstream ``process_flow``."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.folder = text("Upstream result folder", placeholder=".../OpticalFlow3D/<name>")
        self.name = text("Upstream name (imNameSave)")
        self.fields = {f: text(f, "unassigned") for f in METADATA_FIELDS}
        self.image = text("Original image (record only)", "unknown")
        self.parent = text("Results folder")
        self.run_name = text("Run name (optional)")
        self.output = widgets.Output()

    def widget(self, feature_step: FeatureStep, load_step: LoadStep) -> widgets.Widget:
        """Return the widget tree; feature and calibration settings come from steps 3 and 1."""
        run = button("Extract features (external)")
        run.on_click(guarded(self.output, lambda: self.extract(feature_step, load_step)))
        return widgets.VBox(
            [
                self.folder,
                self.name,
                *self.fields.values(),
                self.image,
                self.parent,
                self.run_name,
                run,
                self.output,
            ]
        )

    def extract(self, feature_step: FeatureStep, load_step: LoadStep) -> None:
        """Extract features from the upstream folder into a new run."""
        features, foreground = feature_step.settings()
        settings = RunSettings(
            "", None, load_step.calibration(), features=features, foreground=foreground
        )
        row = {f: w.value for f, w in self.fields.items()} | {"input_path": self.image.value}
        run_dir = create_run(Path(self.parent.value.strip()), self.run_name.value.strip() or None)
        manifest = external_features(
            Path(self.folder.value.strip()), self.name.value.strip(), row, settings, run_dir
        )
        self.session.run_dir = run_dir
        print(
            f"Features of {manifest['fovs'][0]['fov_uid']} written to {run_dir}; the source "
            "image of an external result is not verified."
        )


def build(session: Session | None = None) -> dict[str, object]:
    """Return the five step objects sharing one session (used by the notebook)."""
    session = session or Session()
    return {
        "session": session,
        "load": LoadStep(session),
        "flow": FlowStep(session),
        "features": FeatureStep(session),
        "compare": CompareStep(session),
        "export": ExportStep(session),
        "external": ExternalStep(session),
    }
