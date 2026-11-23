"""ipywidgets interface of notebook sections 3 and 4: process, analyse, report (UI).

As in :mod:`notebook_ui`, the widgets only collect choices and call the package.

- Section 3 (:class:`ProcessStep`): optical flow and features of every field of view of the
  experiment into a new run folder, with optional QC figures.
- Section 4: :class:`ResultsStep` loads the current run or earlier ones;
  :class:`DesignStep` collects the experimental design MorphoCoverage needs (control,
  readout, features, paired repeats, seed); :class:`ReportStep` runs MorphoCoverage and shows
  a link that opens its HTML report in a new tab.
"""

from __future__ import annotations

from pathlib import Path

import ipywidgets as widgets
import pandas as pd
from IPython.display import display

from .analysis import load_runs
from .coverage import Design, coverage_input, default_readout, feature_columns, run_report
from .demo import DemoDesign, run_demo
from .experiment import replicate_counts
from .notebook_ui import (
    LOG_ONLY,
    STYLE,
    WIDE,
    LoadStep,
    Session,
    SettingsStep,
    button,
    guarded,
    text,
)
from .pipeline import checked_settings, run_experiment
from .progress import TqdmTracker
from .qc_export import export_qc_figures
from .report_link import show_link
from .results import create_run
from .validation import InputError


class ProcessStep:
    """Section 3: process every field of view of the experiment into a new run."""

    def __init__(self, session: Session, settings: SettingsStep) -> None:
        self.session, self.settings = session, settings
        self.run_name = text("Run name (optional)", placeholder="default: run-<date>-<time>")
        self.qc = widgets.Checkbox(value=True, description="Save QC figures of every FOV")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the section's widget tree."""
        run = button("Process the experiment")
        run.on_click(guarded(self.output, self.process))
        return widgets.VBox([self.run_name, self.qc, run, self.output])

    def process(self) -> None:
        """Run optical flow and features for every field of view; list the outcome."""
        session = self.session
        if session.metadata is None:
            raise InputError("Load the experiment in section 1 first.")
        settings = self.settings.run_settings()
        checked_settings(settings)  # before the run folder: a refusal never uses up its name
        run = create_run(session.results_root, self.run_name.value.strip() or None)
        print(f"Run folder: {run}")
        manifest = run_experiment(
            session.metadata, settings, run, progress=LOG_ONLY, tracker=TqdmTracker()
        )
        session.run_dir, session.settings = run, settings
        fovs = pd.DataFrame(manifest["fovs"])
        display(fovs[["fov_uid", "status", "warnings", "message"]])
        failed = int((fovs["status"] != "complete").sum())
        print(f"{len(fovs) - failed} complete, {failed} failed (listed above, never skipped).")
        if self.qc.value and failed < len(fovs):
            written = export_qc_figures(run, settings, tracker=TqdmTracker())
            print(f"{len(written)} QC figures saved in {run / 'qc'}.")
        if (run / "features" / "features_per_frame.csv").exists():
            print("Tables: features_per_frame.csv (every time point), features_per_fov.csv.")


class ResultsStep:
    """Section 4a: load the current run or earlier runs (reload previous results)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.runs = widgets.Textarea(
            description="Run folders",
            style=STYLE,
            placeholder="one per line (default: the run of section 3)",
            layout=widgets.Layout(width="90%", height="80px"),
        )
        self.shared = widgets.Checkbox(
            description="Repeat labels mean the same biological repeat in every run"
        )
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the section's widget tree."""
        load = button("Load the results")
        load.on_click(guarded(self.output, self.load))
        explain = widgets.HTML(
            "<small>Tick only when runs share their repeats (for example control and "
            "treatment of one experiment day processed as separate runs): the same label "
            "in several runs then counts as one biological repeat. The software cannot "
            "check this. Unticked, each run's repeats are its own.</small>"
        )
        return widgets.VBox([self.runs, self.shared, explain, load, self.output])

    def load(self) -> None:
        """Load and combine the per-FOV tables; show the design they hold."""
        listed = [Path(p.strip()) for p in self.runs.value.splitlines() if p.strip()]
        if not listed and self.session.run_dir is None:
            raise InputError("List at least one run folder, or process the experiment first.")
        features = load_runs(listed or [self.session.run_dir], self.shared.value)
        self.session.analysis = {"features": features}
        display(replicate_counts(features.table))
        merged = shared_repeats(features.table) if self.shared.value else {}
        for label, runs in merged.items():
            print(
                f"⚠️ Repeat {label} of runs {', '.join(runs)} is counted as ONE biological "
                "repeat (labels shared); untick the box if they are different repeats."
            )
        print(f"{len(features.table)} fields of view from {len(features.sources)} run(s).")


def shared_repeats(table: pd.DataFrame) -> dict[str, list[str]]:
    """Return each biological-repeat label found in several runs, with those runs."""
    runs = table.groupby("biological_repeat")["run"].unique()
    return {str(k): sorted(map(str, v)) for k, v in runs.items() if len(v) > 1}


class DesignStep:
    """Section 4b: the experimental design given to MorphoCoverage."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.control = widgets.Dropdown(description="Control", style=STYLE)
        self.readout = widgets.Dropdown(description="Readout", style=STYLE, layout=WIDE)
        # The readout lists every feature with values; it is declared even when axial.
        self.axial = widgets.Checkbox(description="Also include experimental axial features")
        self.paired = widgets.Checkbox(
            description="A biological-repeat label is the same repeat in every condition",
            layout=WIDE,
        )
        self.seed = widgets.IntText(value=0, description="Random seed", style=STYLE)
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the section's widget tree."""
        refresh, confirm = button("Read the conditions", "info"), button("Confirm the design")
        refresh.on_click(guarded(self.output, self.refresh))
        confirm.on_click(guarded(self.output, self.confirm))
        return widgets.VBox(
            [
                refresh,
                self.control,
                self.readout,
                self.axial,
                self.paired,
                widgets.HTML(
                    "MorphoCoverage pairs biological repeats across conditions only when you "
                    "confirm it (its <code>repeat_group</code>): tick it when, for example, "
                    "<i>rep1</i> of the control and <i>rep1</i> of the treatment were imaged "
                    "the same day."
                ),
                self.seed,
                confirm,
                self.output,
            ]
        )

    def features(self) -> object:
        """Return the loaded features (section 4a)."""
        features = self.session.analysis.get("features")
        if features is None:
            raise InputError("Load the results first.")
        return features

    def refresh(self) -> None:
        """Offer the conditions and the feature columns of the loaded results."""
        features = self.features()
        self.control.options = sorted(features.table["condition"].unique())
        declared, _ = feature_columns(features, include_axial=True)
        self.readout.options = declared
        self.readout.value = default_readout(features)
        print("Choose the control and the readout, then confirm the design.")

    def confirm(self) -> None:
        """Check the design and show what MorphoCoverage will receive."""
        design = Design(
            self.control.value, self.readout.value, self.paired.value, self.axial.value,
            self.seed.value,
        )  # fmt: skip
        data = coverage_input(self.features(), design)
        self.session.analysis["design"] = design
        print(
            f"MorphoCoverage input: {len(data.objects)} fields of view (the observation), "
            f"{len(data.features)} features, control {design.control}, readout "
            f"{design.readout}."
        )
        for note in data.notes:
            print("•", note)
        display(data.fovs.groupby(["condition", "repeat_group"]).size().unstack(fill_value=0))


class ReportStep:
    """Section 4c: run MorphoCoverage and open its HTML report in a new tab."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.name = text("Report name", "report-1")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the section's widget tree."""
        create = button("Create the HTML report")
        create.on_click(guarded(self.output, self.create))
        return widgets.VBox([self.name, create, self.output])

    def create(self) -> None:
        """Run the MorphoCoverage report into ``<run>/analysis/<name>`` and link it."""
        analysis = self.session.analysis
        if "design" not in analysis:
            raise InputError("Confirm the experimental design first.")
        features = analysis["features"]
        out = Path(features.sources[0]) / "analysis" / self.name.value.strip()
        path, result, _ = run_report(features, analysis["design"], out, TqdmTracker())
        analysis["report"] = result
        print(result.summary().split("\n\n")[1] if "\n\n" in result.summary() else "")
        show_link(path)


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
        checks = run_demo(
            Path(self.folder.value.strip()), design, progress=print, tracker=TqdmTracker()
        )
        display(pd.DataFrame(checks.rows))
        print("All expectations passed." if checks.passed else "Some expectations FAILED.")
        report = Path(self.folder.value.strip()) / "results" / "run-threshold" / "analysis"
        for page in sorted(report.glob("*/report.html")):
            show_link(page, "Open the demo's MorphoCoverage report in a new tab")


def build(session: Session | None = None) -> dict[str, object]:
    """Return the section objects sharing one session (used by the notebook)."""
    session = session or Session()
    settings = SettingsStep(session)
    return {
        "session": session,
        "load": LoadStep(session),
        "settings": settings,
        "process": ProcessStep(session, settings),
        "results": ResultsStep(session),
        "design": DesignStep(session),
        "report": ReportStep(session),
        "demo": DemoStep(session),
    }
