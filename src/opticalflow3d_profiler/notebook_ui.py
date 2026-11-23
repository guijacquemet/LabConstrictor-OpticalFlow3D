"""ipywidgets interface of steps 1 and 2 of the notebook: load images, calculate flow (UI).

The widgets collect choices and call the package; they compute nothing themselves. State
shared between steps lives in one :class:`Session`. Errors are shown as messages in the
step's output area, never as tracebacks.
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
from .config import Calibration, FlowParameters, ImageSpec
from .discovery import position_id
from .experiment import read_experiment_folder, read_metadata, validate_metadata
from .flow_backend import estimate_resources
from .flow_store import open_result
from .image_io import ImageHeader, dimensions, inspect_tiff, read_frames, validate_image
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
METADATA_FIELDS = ("condition", "biological_repeat", "technical_repeat")


@dataclass
class Session:
    """Choices and results shared by the notebook steps."""

    spec: ImageSpec | None = None
    header: ImageHeader | None = None
    metadata: pd.DataFrame | None = None
    run_dir: Path | None = None
    flow: FlowParameters = field(default_factory=FlowParameters)
    settings: RunSettings | None = None
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
    """Step 1: inspect a TIFF, confirm axes, channel and calibration, preview it."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.path = text("Image file", placeholder="/path/to/fov.ome.tif")
        self.axes = text("Confirmed axes (file order)", placeholder="for example TZYX")
        self.channel = widgets.Dropdown(
            options=[("no C axis", None)], description="Channel", style=STYLE
        )
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
        """Return the step's widget tree."""
        inspect, confirm = button("1. Inspect header"), button("2. Confirm and preview")
        inspect.on_click(guarded(self.output, self.inspect))
        confirm.on_click(guarded(self.output, self.confirm))
        for slider in (self.t, self.z):
            slider.observe(lambda _c: self.show_preview(), names="value")
        return widgets.VBox(
            [
                self.path,
                inspect,
                self.axes,
                self.channel,
                *self.cal.values(),
                widgets.HBox([self.length_unit, self.time_unit]),
                widgets.HTML(
                    "Leave calibration empty when unknown: results then stay in "
                    "pixels (slices) per frame. Nothing is assumed."
                ),
                confirm,
                self.output,
                widgets.HBox([self.t, self.z]),
                self.preview,
            ]
        )

    def inspect(self) -> None:
        """Read the header and pre-fill only what the header states."""
        header = inspect_tiff(Path(self.path.value.strip()))
        self.session.header = header
        print(
            f"{header.format}, shape {header.shape}, {header.dtype}, header axes "
            f"'{header.header_axes}', {header.file_size / 1e9:.2f} GB"
        )
        for note in header.notes:
            print("•", note)
        self.axes.value = "" if header.axes_ambiguous else header.header_axes
        suggestion = header.calibration_suggestion
        values = (
            suggestion.pixel_size_x,
            suggestion.pixel_size_y,
            suggestion.pixel_size_z,
            suggestion.frame_interval,
        )
        for widget, value in zip(self.cal.values(), values, strict=True):
            widget.value = "" if value is None else f"{value:g}"
        self.length_unit.value, self.time_unit.value = "µm", "min"
        print(f"Calibration pre-filled from {suggestion.source}; check every value.")
        self.update_channels()

    def update_channels(self) -> None:
        """Offer a channel choice when the header has a C axis (no default)."""
        header = self.session.header
        axes = self.axes.value.upper() or header.header_axes
        if "C" in axes and len(axes) == len(header.shape):
            n = header.shape[axes.index("C")]
            self.channel.options = [("choose…", None)] + [(str(i), i) for i in range(n)]
        else:
            self.channel.options = [("no C axis", None)]

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
        """Validate the confirmed interpretation and show the preview."""
        if self.session.header is None:
            raise InputError("Inspect the header first.")
        self.update_channels()
        spec = ImageSpec(
            self.session.header.path,
            self.axes.value.strip().upper(),
            self.channel.value,
            self.calibration(),
        )
        validate_image(spec, self.session.header)
        dims = dimensions(spec, self.session.header)
        self.session.spec = spec
        print(f"Confirmed: {dims}, channel {spec.channel}.")
        for issue in check_calibration(spec.calibration) + check_time_and_depth(
            dims["T"], dims["Z"], self.session.flow
        ):
            print(f"{issue.severity.upper()}: {issue.message} {issue.action}")
        self.t.max, self.z.max = dims["T"] - 1, dims["Z"] - 1
        self.z.value = dims["Z"] // 2
        self.show_preview()

    def show_preview(self) -> None:
        """Show one slice of the confirmed image (read on demand)."""
        if self.session.spec is None:
            return
        with self.preview:
            self.preview.clear_output(wait=True)
            volume = read_frames(self.session.spec, self.session.header, [self.t.value])[0]
            figure = figures.image_preview(
                volume, self.z.value, f"t={self.t.value}, z={self.z.value}"
            )
            show(figure)


class FlowStep:
    """Step 2: parameters, resource estimate, run, and flow visualisation."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.xyz = widgets.FloatText(value=3.0, description="xyzSig (voxels)", style=STYLE)
        self.tsig = widgets.FloatText(value=1.0, description="tSig (frames)", style=STYLE)
        self.wsig = widgets.FloatText(value=4.0, description="wSig (voxels)", style=STYLE)
        self.mode = widgets.Dropdown(
            options=[
                ("auto: per-slice 2D if Z step > 3x XY pixel, else 3D", "auto"),
                ("3D (calc_flow3D)", "xyz"),
                ("2D per Z slice (calc_flow2D)", "xy_per_slice"),
            ],
            description="Flow mode",
            style=STYLE,
            layout=WIDE,
        )
        self.equalise = widgets.Dropdown(
            options=[
                ("none: raw intensities (default)", "none"),
                ("equalise global brightness per window (opt-in)", "global_mean"),
            ],
            description="Brightness",
            style=STYLE,
            layout=WIDE,
        )
        self.dtype = widgets.Dropdown(
            options=["float64", "float32"], style=STYLE, description="Saved precision"
        )
        self.parent = text("Results folder", placeholder="/path/to/results")
        self.run_name = text("Run name (optional)")
        self.experiment = text(
            "Experiment folder", placeholder="MorphoBricks layout: condition/repeat/technical/"
        )
        self.masks = text("Masks folder (optional)", placeholder="outside the experiment")
        self.mask_type = text("Mask type", placeholder="for example nuclei")
        self.metadata_csv = text("or metadata CSV", placeholder="optional")
        self.fields = {f: text(f, "single") for f in METADATA_FIELDS}
        self.output = widgets.Output()
        self.viewer = widgets.Output()
        self.fov = widgets.Dropdown(description="Field of view", style=STYLE, layout=WIDE)
        self.frame = widgets.IntSlider(description="Output", continuous_update=False)
        self.z = widgets.IntSlider(description="Z slice", continuous_update=False)

    def widget(self) -> widgets.Widget:
        """Return the step's widget tree."""
        estimate, run, show = (
            button("Estimate resources", "info"),
            button("Run optical flow"),
            button("Show flow", "info"),
        )
        estimate.on_click(guarded(self.output, self.estimate))
        run.on_click(guarded(self.output, self.run))
        show.on_click(guarded(self.viewer, self.show))
        single = widgets.VBox(
            [
                widgets.HTML(
                    "<b>Single image</b>: its labels (MorphoBricks: <i>single</i> for a level "
                    "the experiment does not have); position_id is the file name"
                ),
                *self.fields.values(),
            ]
        )
        return widgets.VBox(
            [
                widgets.HBox([self.xyz, self.tsig, self.wsig]),
                self.mode,
                self.dtype,
                self.equalise,
                widgets.HTML(
                    "Brightness equalisation is off unless you choose it. Check "
                    "qc_brightness_change_per_frame first: above 0.02 per frame, part of "
                    "the measured motion is brightness change."
                ),
                self.parent,
                self.run_name,
                widgets.HTML(
                    "<b>Experiment folder</b> (MorphoBricks layout): "
                    "&lt;root&gt;/&lt;condition&gt;/&lt;biological repeat&gt;/"
                    "&lt;technical repeat&gt;/&lt;image&gt;.tif; every level is optional and a "
                    "missing level is recorded as <i>single</i>."
                ),
                self.experiment,
                widgets.HBox([self.masks, self.mask_type]),
                self.metadata_csv,
                single,
                widgets.HBox([estimate, run]),
                self.output,
                widgets.HTML("<b>Inspect the velocity field</b>"),
                self.fov,
                widgets.HBox([self.frame, self.z]),
                show,
                self.viewer,
            ]
        )

    def parameters(self) -> FlowParameters:
        """Return the upstream parameters from the widgets."""
        return FlowParameters(
            self.xyz.value,
            self.tsig.value,
            self.wsig.value,
            self.dtype.value,
            self.equalise.value,
            self.mode.value,
        )

    def metadata(self) -> pd.DataFrame:
        """Return the metadata: from the experiment folder, the CSV, or the confirmed image."""
        if self.experiment.value.strip():
            masks = self.masks.value.strip()
            return read_experiment_folder(
                Path(self.experiment.value.strip()),
                Path(masks) if masks else None,
                self.mask_type.value.strip() or None,
            )
        if self.metadata_csv.value.strip():
            return read_metadata(Path(self.metadata_csv.value.strip()))
        if self.session.spec is None:
            raise InputError("Confirm an image in step 1, or give an experiment folder or CSV.")
        row = {f: w.value.strip() for f, w in self.fields.items()}
        row["position_id"] = position_id(self.session.spec.path.name)
        row["image_path"] = self.session.spec.path.as_posix()
        return validate_metadata(pd.DataFrame([row]))

    def estimate(self) -> None:
        """Print the memory, disk and time estimate for one field of view."""
        if self.session.spec is None:
            raise InputError("Confirm an image in step 1 first.")
        header = self.session.header
        dims = dimensions(self.session.spec, header)
        found = estimate_resources(
            dims,
            np.dtype(header.dtype).itemsize,
            self.parameters(),
            Path(self.parent.value.strip() or "."),
        )
        print(
            f"{found.n_outputs} optical-flow outputs per field of view; peak memory "
            f"≈ {found.peak_ram_bytes / 1e9:.1f} GB; output ≈ {found.output_bytes / 1e9:.1f} "
            f"GB; time ≈ {found.seconds / 60:.0f} min (rough)."
        )
        for warning in found.warnings():
            print("⚠️", warning)

    def run(self) -> None:
        """Create the run folder and calculate the optical flow of every field of view."""
        spec = self.session.spec
        if spec is None:
            raise InputError("Confirm the axes, channel and calibration in step 1 first.")
        if not self.parent.value.strip():
            raise InputError("Choose a results folder.")
        metadata = self.metadata()
        self.session.flow = self.parameters()
        settings = RunSettings(spec.axes, spec.channel, spec.calibration, self.session.flow)
        run_dir = create_run(Path(self.parent.value.strip()), self.run_name.value.strip() or None)
        manifest = run_experiment(metadata, settings, run_dir, progress=print, flow_only=True)
        self.session.metadata, self.session.run_dir = metadata, run_dir
        self.session.settings = settings
        print(f"Run folder: {run_dir}")
        print(pd.DataFrame(manifest["fovs"])[["fov_uid", "status", "message"]].to_string())
        done = [f["fov_uid"] for f in manifest["fovs"] if f["status"] == "flow complete"]
        self.fov.options = done

    def show(self) -> None:
        """Show the image, flow vectors, speed and reliability of one output."""
        if not self.fov.value:
            raise InputError("Run the optical flow first.")
        result = open_result(self.session.run_dir / "flow" / self.fov.value)
        self.frame.max = len(result.frames) - 1
        frame = result.frames[self.frame.value]
        flow = frame.load()
        self.z.max = flow["vx"].shape[0] - 1
        row = self.session.metadata.set_index("fov_uid").loc[self.fov.value]
        spec = ImageSpec(Path(row["image_path"]), self.session.spec.axes, self.session.spec.channel)
        intensity = read_frames(spec, inspect_tiff(spec.path), [frame.source_frame])[0]
        print(f"Source time point {frame.source_frame}; velocities in pixels/frame.")
        show(figures.flow_overview(intensity, flow, self.z.value))
