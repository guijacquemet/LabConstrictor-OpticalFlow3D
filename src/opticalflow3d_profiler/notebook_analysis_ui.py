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
from .comparison import ComparisonSettings
from .config import FeatureSettings, ForegroundSpec
from .demo import DemoDesign, run_demo
from .experiment import replicate_counts
from .external import external_features
from .naming import feature_key
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
from .qc_export import export_qc_figures
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
        self.intensity = widgets.Checkbox(
            description="Also report intensity-based QC (opt-in)", style=STYLE
        )
        self.channel_name = text("Channel name", placeholder="stain, for example H2B")
        self.object_set = text("Foreground name", "Nuclei")
        self.new_run = text("New run name (re-extraction)", placeholder="optional")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the step's widget tree."""
        run = button("Extract features")
        run.on_click(guarded(self.output, self.extract))
        qc = button("Save QC figures", "info")
        qc.on_click(guarded(self.output, self.save_qc))
        return widgets.VBox(
            [
                widgets.HTML(
                    "Feature columns are named as in MorphoBricks: "
                    "<code>&lt;channel&gt;__&lt;foreground name or whole&gt;__&lt;feature&gt;"
                    "</code>."
                ),
                self.channel_name,
                self.fg_mode,
                self.object_set,
                self.threshold,
                self.mask_path,
                self.mask_axes,
                self.mask_rule,
                self.rel_mode,
                self.rel_value,
                self.speed,
                widgets.HBox([self.region, self.window]),
                self.motion,
                self.intensity,
                self.new_run,
                widgets.HBox([run, qc]),
                self.output,
            ]
        )

    def save_qc(self) -> None:
        """Save input, foreground and flow figures of every field of view of the run."""
        session = self.session
        if session.run_dir is None or session.settings is None:
            raise InputError("Run step 2 first.")
        settings = self.run_settings()
        written = export_qc_figures(session.run_dir, settings)
        print(f"{len(written)} QC figures saved in {session.run_dir / 'qc'}.")

    def settings(self) -> tuple[FeatureSettings, ForegroundSpec]:
        """Return the feature and foreground settings from the widgets."""
        features = FeatureSettings(
            speed_mode=self.speed.value,
            reliability_mode=self.rel_mode.value,
            reliability_value=number(self.rel_value.value),
            region_size_px=self.region.value,
            local_window_px=self.window.value,
            motion_threshold=number(self.motion.value),
            intensity_features=self.intensity.value,
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

    def run_settings(self) -> RunSettings:
        """Return the session's run settings with this step's choices."""
        features, foreground = self.settings()
        return replace(
            self.session.settings,
            features=features,
            foreground=foreground,
            channel_name=self.channel_name.value.strip() or None,
            object_set=self.object_set.value.strip(),
        )

    def extract(self) -> None:
        """Extract features for every field of view of the run (flow reused, verified)."""
        session = self.session
        if session.run_dir is None or session.settings is None:
            raise InputError("Run step 2 first.")
        settings = self.run_settings()
        features = settings.features
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
            names = settings.column_names()
            keys = [f"{prefix}_median", "coherence_xy_global", "qc_reliable_fraction"]
            show(figures.feature_histograms(frames, [names.column(k) for k in keys]))


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
        self.selection = widgets.Dropdown(
            options=[
                ("core interpretable features (recommended)", "core"),
                ("every feature of the chosen families", "families"),
            ],
            description="PCA inputs",
            style=STYLE,
        )
        self.shared = widgets.Checkbox(
            description="Repeat labels mean the same biological repeat in every run"
        )
        self.missing = widgets.Dropdown(
            options=[
                ("drop features with missing values", "drop_features"),
                ("drop FOVs with missing values", "drop_fovs"),
            ],
            description="Missing values",
            style=STYLE,
        )
        self.control = widgets.Dropdown(description="Control", style=STYLE)
        self.seed = widgets.IntText(value=0, description="Random seed", style=STYLE)
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the step's widget tree."""
        pca, compare = button("Run PCA"), button("Compare conditions")
        pca.on_click(guarded(self.output, self.pca))
        compare.on_click(guarded(self.output, self.compare))
        return widgets.VBox(
            [
                self.runs,
                self.shared,
                self.selection,
                self.families,
                self.axial,
                self.missing,
                pca,
                widgets.HTML(
                    "<b>Compare every condition with the control</b> (MorphoCoverage rules; "
                    "the field of view is the observation, the biological repeat the "
                    "replicate): Cohen's d, the exploratory FOV-level randomization test, and "
                    "the paired t-test on repeat means (from 3 repeats)."
                ),
                widgets.HBox([self.control, self.seed]),
                compare,
                self.output,
            ]
        )

    def features(self) -> object:
        """Load the per-FOV tables of the listed runs (or of the current run)."""
        listed = [Path(p.strip()) for p in self.runs.value.splitlines() if p.strip()]
        if not listed and self.session.run_dir is None:
            raise InputError("List at least one run folder.")
        features = load_runs(listed or [self.session.run_dir], self.shared.value)
        conditions = sorted(features.table["condition"].unique())
        self.control.options = conditions
        self.session.analysis["features"] = features
        return features

    def pca(self) -> None:
        """Run and display the exploratory PCA."""
        features = self.features()
        settings = PcaSettings(
            tuple(self.families.value), self.selection.value, self.axial.value, self.missing.value
        )
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
        """Compare every condition with the control on every tested feature."""
        features = self.session.analysis.get("features") or self.features()
        settings = ComparisonSettings(self.control.value, self.axial.value, seed=self.seed.value)
        tests, per_repeat = compare_conditions(features, settings)
        self.session.analysis.update(comparison=(tests, per_repeat), comparison_settings=settings)
        print(
            "The FOV-level screen treats fields of view as independent: its passing features "
            "are candidates. 'Significant across repeats' also needs the paired test on repeat "
            "means (3 or more biological repeats)."
        )
        display(tests[[c for c in SUMMARY if c in tests.columns]])
        for feature in plotted(tests):
            unit = features.units["lateral"] if "speed" in feature else ""
            show(figures.condition_plot(features.table, feature, feature_key(feature), unit))


def plotted(tests: pd.DataFrame, most: int = 6) -> list[str]:
    """Features to plot: those passing the screen, else the largest |d|, at most ``most``."""
    rows = tests[tests["family"] == "features"].copy()
    rows["size"] = rows["d_fovs"].abs()
    passing = rows[rows["q_screen"] <= 0.05]
    chosen = passing if len(passing) else rows
    return list(dict.fromkeys(chosen.sort_values("size", ascending=False)["feature"]))[:most]


SUMMARY = (
    "family",
    "feature",
    "condition",
    "fovs",
    "control_fovs",
    "repeats_paired",
    "d_fovs",
    "screen_test",
    "q_screen",
    "change",
    "q_repeats",
    "direction_per_repeat",
    "verdict",
)


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
        export_analysis(
            out,
            features,
            analysis["pca_settings"],
            result,
            analysis.get("comparison"),
            analysis.get("comparison_settings"),
        )
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
            for feature in plotted(comparison[0]):
                figures.save(
                    figures.condition_plot(features.table, feature, feature_key(feature)),
                    out / "figures" / f"condition_{feature}.png",
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
        self.fields = {f: text(f, "single") for f in (*METADATA_FIELDS, "position_id")}
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
            "",
            None,
            load_step.calibration(),
            features=features,
            foreground=foreground,
            channel_name=feature_step.channel_name.value.strip() or None,
            object_set=feature_step.object_set.value.strip(),
        )
        row = {f: w.value.strip() for f, w in self.fields.items()} | {
            "image_path": self.image.value
        }
        run_dir = create_run(Path(self.parent.value.strip()), self.run_name.value.strip() or None)
        manifest = external_features(
            Path(self.folder.value.strip()), self.name.value.strip(), row, settings, run_dir
        )
        self.session.run_dir = run_dir
        print(
            f"Features of {manifest['fovs'][0]['fov_uid']} written to {run_dir}; the source "
            "image of an external result is not verified."
        )


class DemoStep:
    """Optional: run every step on a synthetic experiment with a known answer."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.folder = text("New demo folder", placeholder="/path/to/empty/folder")
        self.small = widgets.Checkbox(value=True, description="Small images (quick, ~3 min)")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the widget tree."""
        run = button("Run the synthetic demo")
        run.on_click(guarded(self.output, self.run))
        return widgets.VBox([self.folder, self.small, run, self.output])

    def run(self) -> None:
        """Run the demo and show each expectation with PASS or FAIL."""
        if not self.folder.value.strip():
            raise InputError("Choose a new, empty folder.")
        design = DemoDesign.small() if self.small.value else None
        checks = run_demo(Path(self.folder.value.strip()), design, progress=lambda _l: None)
        display(pd.DataFrame(checks.rows))
        print("All expectations passed." if checks.passed else "Some expectations FAILED.")


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
        "demo": DemoStep(session),
    }
