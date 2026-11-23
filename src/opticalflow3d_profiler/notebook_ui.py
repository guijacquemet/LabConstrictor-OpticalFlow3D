"""ipywidgets interface of notebook sections 1 and 2: load the data, choose settings (UI).

The widgets collect choices and call the package; they compute nothing themselves. State
shared between sections lives in one :class:`Session`. Errors are shown as messages in the
section's output area, never as tracebacks.

- Section 1 (:class:`LoadStep`): the experiment folder (MorphoBricks layout) and the results
  folder; a random example image whose header is shown; the confirmed axes and calibration,
  checked against every image header; a preview.
- Section 2 (:class:`SettingsStep`): optical flow (2D per slice, 3D or automatic), the
  foreground, reliability and feature settings, a resource estimate, and the processing of
  the example field of view with its figures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import ipywidgets as widgets
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display
from matplotlib.figure import Figure

from . import figures
from .config import Calibration, FeatureSettings, FlowParameters, ForegroundSpec, ImageSpec
from .experiment import read_experiment_folder
from .experiment_check import (
    check_headers,
    header_notes,
    header_problems,
    header_summary,
    pick_example,
)
from .flow_backend import estimate_resources
from .flow_store import open_result
from .image_io import ImageHeader, dimensions, inspect_tiff, read_frames, validate_image
from .naming import find_column
from .pipeline import RunSettings, run_experiment
from .results import create_run
from .validation import (
    InputError,
    check_calibration,
    check_time_and_depth,
    to_micrometres,
    to_minutes,
)

WIDE = widgets.Layout(width="90%")
STYLE = {"description_width": "180px"}


@dataclass
class Session:
    """Choices and results shared by the notebook sections."""

    metadata: pd.DataFrame | None = None
    results_root: Path | None = None
    example: pd.Series | None = None
    header: ImageHeader | None = None
    spec: ImageSpec | None = None
    settings: RunSettings | None = None
    run_dir: Path | None = None
    analysis: dict = field(default_factory=dict)


def text(description: str, value: str = "", placeholder: str = "") -> widgets.Text:
    """Return a wide text field."""
    return widgets.Text(
        value=value, description=description, placeholder=placeholder, layout=WIDE, style=STYLE
    )


def number(value: str) -> float | None:
    """Return a float from a text field, ``None`` when empty."""
    value = value.strip()
    return float(value) if value else None


def guarded(output: widgets.Output, action: Callable[[], None]) -> Callable:
    """Return a button callback that runs ``action`` and reports errors plainly."""

    def callback(_button: widgets.Button | None = None) -> None:
        with output:
            output.clear_output()
            try:
                action()
            except (InputError, ValueError, OSError) as error:
                print(f"⚠️ {error}")

    return callback


def show(figure: Figure) -> None:
    """Display a figure in the current output and release it."""
    display(figure)
    plt.close(figure)


def button(description: str, style: str = "primary") -> widgets.Button:
    """Return a button."""
    return widgets.Button(
        description=description, button_style=style, layout=widgets.Layout(width="260px")
    )


class LoadStep:
    """Section 1: experiment and results folders, an example image, axes and calibration."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.experiment = text(
            "Experiment folder", placeholder="<condition>/<repeat>/<technical repeat>/<image>.tif"
        )
        self.results = text("Results folder", placeholder="outside the experiment folder")
        self.axes = text("Confirmed axes (file order)", placeholder="for example TZYX")
        self.cal = {
            k: text(label)
            for k, label in (
                ("x", "X pixel size"),
                ("y", "Y pixel size"),
                ("z", "Z spacing"),
                ("t", "Frame interval"),
            )
        }
        self.length_unit = widgets.Dropdown(
            options=["µm", "nm"], description="Length unit", style=STYLE
        )
        self.time_unit = widgets.Dropdown(
            options=["min", "s", "h"], description="Time unit", style=STYLE
        )
        self.output = widgets.Output()
        self.preview = widgets.Output()
        self.t = widgets.IntSlider(description="Time point", continuous_update=False)
        self.z = widgets.IntSlider(description="Z slice", continuous_update=False)

    def widget(self) -> widgets.Widget:
        """Return the section's widget tree."""
        load, again = button("1. Load the experiment"), button("Another example image", "info")
        confirm = button("2. Confirm axes and calibration")
        load.on_click(guarded(self.output, self.load))
        again.on_click(guarded(self.output, self.pick))
        confirm.on_click(guarded(self.output, self.confirm))
        for slider in (self.t, self.z):
            slider.observe(lambda _c: self.show_preview(), names="value")
        return widgets.VBox(
            [
                self.experiment,
                self.results,
                widgets.HBox([load, again]),
                self.axes,
                widgets.HTML("Single-channel videos only (a C axis of length 1 is accepted)."),
                *self.cal.values(),
                widgets.HBox([self.length_unit, self.time_unit]),
                widgets.HTML(
                    "The values are pre-filled from the example's header; check each one. "
                    "Leave a value empty when unknown: results then stay in pixels (slices) "
                    "per frame. Nothing is assumed."
                ),
                confirm,
                self.output,
                widgets.HBox([self.t, self.z]),
                self.preview,
            ]
        )

    def load(self) -> None:
        """Discover the experiment, show its design and an example image's header."""
        if not self.experiment.value.strip() or not self.results.value.strip():
            raise InputError("Give the experiment folder and the results folder.")
        root = Path(self.experiment.value.strip()).resolve()
        results = Path(self.results.value.strip()).resolve()
        if results.is_relative_to(root):
            raise InputError("The results folder must be outside the experiment folder.")
        metadata = read_experiment_folder(root)
        self.session.metadata, self.session.results_root = metadata, results
        design = metadata.groupby(["condition", "biological_repeat"]).size().unstack(fill_value=0)
        print(f"{len(metadata)} fields of view (images). Fields of view per condition and repeat:")
        display(design)
        self.pick()

    def pick(self) -> None:
        """Open a random image of the experiment and pre-fill its header values."""
        if self.session.metadata is None:
            raise InputError("Load the experiment first.")
        row, seed = pick_example(self.session.metadata)
        header = inspect_tiff(Path(row["image_path"]))
        self.session.example, self.session.header, self.session.spec = row, header, None
        print(f"Example image (random, seed {seed}):")
        display(header_summary(header, row).style.hide(axis="index"))
        self.axes.value = "" if header.axes_ambiguous else header.header_axes
        cal = header.calibration_suggestion
        values = (cal.pixel_size_x, cal.pixel_size_y, cal.pixel_size_z, cal.frame_interval)
        for widget, value in zip(self.cal.values(), values, strict=True):
            widget.value = "" if value is None else f"{value:g}"
        self.length_unit.value, self.time_unit.value = "µm", "min"

    def calibration(self) -> Calibration:
        """Return the confirmed calibration in µm and minutes."""
        unit, t_unit = self.length_unit.value, self.time_unit.value
        return Calibration(
            to_micrometres(number(self.cal["x"].value), unit),
            to_micrometres(number(self.cal["y"].value), unit),
            to_micrometres(number(self.cal["z"].value), unit),
            to_minutes(number(self.cal["t"].value), t_unit),
            source="confirmed by user",
        )

    def confirm(self) -> None:
        """Validate the axes and calibration on every image header, then preview."""
        if self.session.header is None:
            raise InputError("Load the experiment first.")
        axes = self.axes.value.strip().upper()
        spec = ImageSpec(self.session.header.path, axes, None, self.calibration())
        validate_image(spec, self.session.header)
        table = check_headers(self.session.metadata, axes)
        problems = header_problems(table)
        if problems:
            display(table[table["problem"] != ""])
            raise InputError("Some images cannot be processed: " + " | ".join(problems[:5]))
        for note in header_notes(table):
            print("•", note)
        dims = dimensions(spec, self.session.header)
        self.session.spec = spec
        print(f"Confirmed for all {len(table)} images: {dims} (single channel).")
        for issue in check_calibration(spec.calibration) + check_time_and_depth(
            dims["T"], dims["Z"], FlowParameters(mode="xy_per_slice")
        ):
            print(f"{issue.severity.upper()}: {issue.message} {issue.action}")
        self.t.max, self.z.max = dims["T"] - 1, dims["Z"] - 1
        self.z.value = dims["Z"] // 2
        self.show_preview()

    def show_preview(self) -> None:
        """Show one slice of the example image (read on demand, raw intensities)."""
        if self.session.spec is None:
            return
        with self.preview:
            self.preview.clear_output(wait=True)
            volume = read_frames(self.session.spec, self.session.header, [self.t.value])[0]
            title = f"t={self.t.value}, z={self.z.value}"
            show(figures.image_preview(volume, self.z.value, title))


class SettingsStep:
    """Section 2: optical-flow and feature settings, resource estimate, the example run."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.mode = widgets.Dropdown(
            options=[
                ("automatic: 2D per slice if Z step > 3x XY pixel, else 3D", "auto"),
                ("2D optical flow, slice per slice (calc_flow2D)", "xy_per_slice"),
                ("3D optical flow (calc_flow3D)", "xyz"),
            ],
            description="Optical flow",
            style=STYLE,
            layout=WIDE,
        )
        self.xyz = widgets.FloatText(value=3.0, description="xyzSig (voxels)", style=STYLE)
        self.tsig = widgets.FloatText(value=1.0, description="tSig (frames)", style=STYLE)
        self.wsig = widgets.FloatText(value=4.0, description="wSig (voxels)", style=STYLE)
        self.equalise = widgets.Dropdown(
            options=[
                ("none: raw intensities (default)", "none"),
                ("equalise the global mean brightness per window", "global_mean"),
                ("match histograms within each window", "histogram_match"),
            ],
            description="Brightness",
            style=STYLE,
            layout=WIDE,
        )
        self.dtype = widgets.Dropdown(
            options=["float64", "float32"], style=STYLE, description="Saved precision"
        )
        self.fg_mode = widgets.Dropdown(
            options=[("intensity threshold", "threshold"), ("none (whole image)", "none")],
            description="Foreground",
            style=STYLE,
        )
        self.threshold = text("Raw-intensity threshold")
        self.object_set = text("Foreground name", "Nuclei")
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
        self.intensity = widgets.Checkbox(description="Also report intensity-based QC (opt-in)")
        self.output = widgets.Output()

    def widget(self) -> widgets.Widget:
        """Return the section's widget tree."""
        estimate, example = button("Estimate resources", "info"), button("Process the example")
        estimate.on_click(guarded(self.output, self.estimate))
        example.on_click(guarded(self.output, self.process_example))
        return widgets.VBox(
            [
                widgets.HTML("<b>Optical flow</b> (defaults of the original algorithm)"),
                self.mode,
                widgets.HBox([self.xyz, self.tsig, self.wsig]),
                self.equalise,
                self.dtype,
                widgets.HTML("<b>Features</b>"),
                self.fg_mode,
                self.threshold,
                self.object_set,
                self.rel_mode,
                self.rel_value,
                self.speed,
                widgets.HBox([self.region, self.window]),
                self.motion,
                self.intensity,
                widgets.HBox([estimate, example]),
                self.output,
            ]
        )

    def run_settings(self) -> RunSettings:
        """Return the run settings from section 1's confirmation and these widgets."""
        spec = self.session.spec
        if spec is None:
            raise InputError("Confirm the axes and calibration in section 1 first.")
        flow = FlowParameters(
            self.xyz.value,
            self.tsig.value,
            self.wsig.value,
            self.dtype.value,
            self.equalise.value,
            self.mode.value,
        )
        features = FeatureSettings(
            speed_mode=self.speed.value,
            reliability_mode=self.rel_mode.value,
            reliability_value=number(self.rel_value.value),
            region_size_px=self.region.value,
            local_window_px=self.window.value,
            motion_threshold=number(self.motion.value),
            intensity_features=self.intensity.value,
        )
        foreground = ForegroundSpec(self.fg_mode.value, number(self.threshold.value))
        return RunSettings(
            spec.axes,
            None,
            spec.calibration,
            flow,
            features,
            foreground,
            object_set=self.object_set.value.strip(),
        )

    def estimate(self) -> None:
        """Print the memory, disk and time estimate for one field of view."""
        settings = self.run_settings()
        header = self.session.header
        found = estimate_resources(
            dimensions(self.session.spec, header),
            np.dtype(header.dtype).itemsize,
            settings.flow,
            self.session.results_root or Path("."),
        )
        print(
            f"{found.n_outputs} optical-flow outputs per field of view; peak memory "
            f"≈ {found.peak_ram_bytes / 1e9:.1f} GB; output ≈ {found.output_bytes / 1e9:.1f} "
            f"GB; time ≈ {found.seconds / 60:.0f} min (rough)."
        )
        for warning in found.warnings():
            print("⚠️", warning)

    def process_example(self) -> None:
        """Run optical flow and features on the example image; show what it gives."""
        settings = self.run_settings()
        row = self.session.example
        metadata = self.session.metadata
        one = metadata[metadata["fov_uid"] == row["fov_uid"]]
        run = create_run(self.session.results_root / "examples")
        manifest = run_experiment(one, settings, run, progress=print)
        self.session.settings = settings
        status = manifest["fovs"][0]
        print(f"Example run: {run}\nStatus: {status['status']} {status['message']}")
        for warning in filter(None, str(status.get("warnings", "")).split(" | ")):
            print("⚠️", warning)
        if status["status"] == "complete":
            show_example(run, row, settings)


def show_example(run: Path, row: pd.Series, settings: RunSettings) -> None:
    """Show the middle optical-flow output and the per-frame features of the example."""
    result = open_result(run / "flow" / str(row["fov_uid"]))
    frame = result.frames[len(result.frames) // 2]
    spec = ImageSpec(Path(row["image_path"]), settings.axes, None)
    intensity = read_frames(spec, inspect_tiff(spec.path), [frame.source_frame])[0]
    z = intensity.shape[0] // 2
    step = max(4, intensity.shape[2] // 40)
    figure = figures.flow_overview(intensity, frame.load(), z, step=step)
    figure.suptitle(f"Source time point {frame.source_frame}, z={z}; velocities in pixels/frame")
    show(figure)
    frames = pd.read_csv(run / "features" / "features_per_frame.csv")
    speed = find_column(frames.columns, "speed_3d_median") or find_column(
        frames.columns, "speed_xy_median"
    )
    coherence = find_column(frames.columns, "coherence_xy_global")
    wanted = (speed, coherence, "qc_reliable_fraction", "qc_brightness_change_per_frame")
    columns = [c for c in wanted if c and c in frames.columns]
    show(figures.feature_timeseries(frames, columns, "t"))
    per_fov = pd.read_csv(run / "features" / "features_per_fov.csv")
    display(per_fov[columns].T.rename(columns={0: "time average"}))
