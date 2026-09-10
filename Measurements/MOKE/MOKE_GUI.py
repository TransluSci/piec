"""Tk GUI for the general calibrated-source/DMM MOKE measurement."""

import ctypes
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.autodetect import autodetect
from piec.drivers.dmm.dmm import DMM
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement.gui_utils import MeasurementApp
from piec.measurement.moke import MokeMeasurement
from piec.measurement import MeasurementRunner, TerminalEvent, SafetyAlertEvent
from piec.simulation.hysteretic_magnetic_material import HystereticMagneticMaterial


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    pass


HERE = Path(__file__).resolve().parent
DEFAULTS = {
    "source_address": "VIRTUAL",
    "detector_address": "VIRTUAL",
    "field_reader_address": "NONE",
    "geometry": "in-plane",
    "calibration_path": str(HERE / "example_calibration.csv"),
    "save_dir": str(Path.cwd()),
    "output_min": -5.0,
    "output_max": 5.0,
    "points_per_cycle": 201,
    "n_cycles": 3,
    "average_cycles": 3,
    "compliance": 0.01,
    "max_output_step": 0.25,
    "dwell_time": 0.02,
    "ramp_delay": 0.002,
    "raw_window_points": 1000,
    "source_channel": "",
    "field_per_volt": 1.0,
    "field_offset": 0.0,
}


@dataclass(frozen=True)
class MokeSetupProfile:
    """Validated, run-specific geometry setup; no instrument I/O during creation."""

    geometry: str
    settings: object
    shutdown_handler: object = None

    def __post_init__(self):
        if self.geometry not in ("in-plane", "out-of-plane"):
            raise ValueError("Unknown MOKE geometry")
        if self.shutdown_handler is not None and not callable(self.shutdown_handler):
            raise TypeError("shutdown_handler must be callable")
        settings = dict(self.settings)
        calibration = settings["calibration"]
        settings["calibration"] = FieldCalibration(**calibration.to_dict())
        settings["outputs"] = tuple(float(v) for v in settings["outputs"])
        calibration.field_at_output(settings["outputs"])
        for key in ("compliance", "max_output_step"):
            if not np.isfinite(settings[key]) or settings[key] <= 0:
                raise ValueError(f"{key} must be positive and finite")
        for key in ("dwell_time", "ramp_delay"):
            if not np.isfinite(settings[key]) or settings[key] < 0:
                raise ValueError(f"{key} must be nonnegative and finite")
        for key in ("n_cycles", "average_cycles", "raw_window_points"):
            if settings[key] < 1:
                raise ValueError(f"{key} must be positive")
        if settings["source_channel"] is not None and settings["source_channel"] < 1:
            raise ValueError("Source channel must be positive")
        if not all(np.isfinite(settings[k]) for k in ("field_per_volt", "field_offset")):
            raise ValueError("Field-reader conversion must be finite")
        object.__setattr__(self, "settings", MappingProxyType(settings))


def make_output_cycle(output_min, output_max, points):
    """Return one closed low-high-low cycle with exactly ``points`` values."""
    output_min = float(output_min)
    output_max = float(output_max)
    points = int(points)
    if not output_min < output_max:
        raise ValueError("Output minimum must be below output maximum")
    if points < 5:
        raise ValueError("Points per cycle must be at least 5")
    up_count = points // 2 + 1
    down_count = points - up_count + 1
    return np.r_[
        np.linspace(output_min, output_max, up_count),
        np.linspace(output_max, output_min, down_count)[1:],
    ]


def connect_virtual_detector(
    source, detector, calibration, *, detector_gain=0.02,
    detector_offset=0.0, noise=0.0002, seed=0,
):
    """Wire generic virtual instruments to the separate magnetic model."""
    material = HystereticMagneticMaterial(
        coercive_field=50.0,
        switching_width=10.0,
    )
    generator = np.random.default_rng(seed)
    source_key = (
        "source_voltage" if calibration.output_unit == "V" else "source_current"
    )

    def read_detector_voltage():
        output = source.state[source_key]
        field = calibration.field_at_output(output)
        magnetization = material.apply_field(field)
        return (
            float(detector_offset)
            + float(detector_gain) * magnetization
            + generator.normal(0.0, float(noise))
        )

    detector.set_voltage_reader(read_detector_voltage)
    return material


class MokeMeasurementApp(MeasurementApp):
    def __init__(self, root, *, shutdown_handlers=None):
        super().__init__(root, title="MOKE Measurement GUI", geometry="1600x950")
        print("Welcome to the MOKE measurement GUI!")
        print("Ctrl+Enter: run measurement")

        self.experiment = None
        self.runner = None
        self._terminal_event = None
        self.is_measuring = False
        self._close_when_safe = False
        self._instruments = []
        self._geometry_settings = {}
        self._selected_geometry = DEFAULTS["geometry"]
        self._shutdown_handlers = dict(shutdown_handlers or {})

        resources = self.get_visa_resources()
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])
        self._add_static_inputs(resources)
        self._add_dynamic_inputs()
        self._add_plot_controls()
        self._replace_run_controls()
        self._poll_events_id = self.root.after(50, self._poll_events)

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _labeled_entry(self, frame, row, label, default, width=18):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(frame, width=width)
        entry.grid(row=row, column=1, padx=5, pady=3, sticky="ew")
        entry.insert(0, default)
        return entry

    def _labeled_combo(self, frame, row, label, values, default):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
        combo = ttk.Combobox(frame, values=values, state="readonly", width=25)
        combo.grid(row=row, column=1, padx=5, pady=3, sticky="ew")
        combo.set(default)
        return combo

    def _add_static_inputs(self, resources):
        addresses = ["VIRTUAL"] + list(resources)
        self.source_address_entry = self._labeled_combo(
            self.static_frame, 1, "Sourcemeter Address:", addresses,
            DEFAULTS["source_address"],
        )
        self.detector_address_entry = self._labeled_combo(
            self.static_frame, 2, "Detector DMM Address:", addresses,
            DEFAULTS["detector_address"],
        )
        self.field_reader_address_entry = self._labeled_combo(
            self.static_frame, 3, "Field-reader DMM:",
            ["NONE", "VIRTUAL"] + list(resources),
            DEFAULTS["field_reader_address"],
        )
        ttk.Button(
            self.static_frame, text="Refresh", command=self.refresh_instruments,
            style="TButton",
        ).grid(row=1, column=2, rowspan=3, padx=5)

        self.geometry_entry = self._labeled_combo(
            self.static_frame, 4, "Geometry:", ["in-plane", "out-of-plane"],
            DEFAULTS["geometry"],
        )
        self.geometry_entry.bind("<<ComboboxSelected>>", self._on_geometry_changed)
        self.calibration_entry = self._labeled_entry(
            self.static_frame, 5, "Calibration CSV:",
            DEFAULTS["calibration_path"], width=32,
        )
        ttk.Button(
            self.static_frame, text="Browse", command=self.browse_calibration,
            style="TButton",
        ).grid(row=5, column=2, padx=5)
        self.source_channel_entry = self._labeled_entry(
            self.static_frame, 6, "Source Channel (optional):",
            DEFAULTS["source_channel"],
        )
        self.field_per_volt_entry = self._labeled_entry(
            self.static_frame, 7, "Field per reader volt:",
            DEFAULTS["field_per_volt"],
        )
        self.field_offset_entry = self._labeled_entry(
            self.static_frame, 8, "Field-reader offset:",
            DEFAULTS["field_offset"],
        )

    def _add_dynamic_inputs(self):
        self.dynamic_frame.config(text="MOKE LOOP INPUTS")
        definitions = [
            ("output_min", "Output Minimum:", DEFAULTS["output_min"]),
            ("output_max", "Output Maximum:", DEFAULTS["output_max"]),
            ("points_per_cycle", "Points per Cycle:", DEFAULTS["points_per_cycle"]),
            ("n_cycles", "Number of Cycles:", DEFAULTS["n_cycles"]),
            ("average_cycles", "Cycles to Average:", DEFAULTS["average_cycles"]),
            ("compliance", "Compliance:", DEFAULTS["compliance"]),
            ("max_output_step", "Maximum Output Step:", DEFAULTS["max_output_step"]),
            ("dwell_time", "Dwell Time (s):", DEFAULTS["dwell_time"]),
            ("ramp_delay", "Ramp Delay (s):", DEFAULTS["ramp_delay"]),
            ("raw_window_points", "Raw Window Points:", DEFAULTS["raw_window_points"]),
        ]
        self.dynamic_inputs = {
            name: self._labeled_entry(self.dynamic_frame, row, label, default)
            for row, (name, label, default) in enumerate(definitions)
        }

    def _add_plot_controls(self):
        self.show_raw = tk.BooleanVar(value=True)
        self.show_last = tk.BooleanVar(value=True)
        self.show_average = tk.BooleanVar(value=True)
        for row, (text, variable) in enumerate(
            [
                ("Show real-time raw", self.show_raw),
                ("Show last complete cycle", self.show_last),
                ("Show cycle average", self.show_average),
            ]
        ):
            ttk.Checkbutton(
                self.plot_config_frame,
                text=text,
                variable=variable,
                command=self._redraw_current,
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        self.save_data = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.plot_config_frame,
            text="Save acquired data",
            variable=self.save_data,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        self.status_label = ttk.Label(self.plot_config_frame, text="Idle")
        self.status_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=5)

    def _replace_run_controls(self):
        self.run_button.destroy()
        controls = ttk.Frame(self.right_panel, style="TFrame")
        controls.grid(row=1, column=0, pady=10)
        self.run_button = ttk.Button(
            controls, text="RUN MEASUREMENT", command=self.run_measurement,
            style="TButton",
        )
        self.run_button.pack(side="left", padx=5)
        self.stop_button = ttk.Button(
            controls, text="STOP AND ZERO", command=self.stop_measurement,
            state="disabled", style="TButton",
        )
        self.stop_button.pack(side="left", padx=5)

    def browse_calibration(self):
        if getattr(self, "is_measuring", False):
            print("Cannot change calibration while a measurement is active.")
            return
        filename = filedialog.askopenfilename(
            title="Select field calibration",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filename:
            self._set_entry(self.calibration_entry, filename)

    def refresh_instruments(self):
        if getattr(self, "is_measuring", False):
            print("Cannot refresh instruments while a measurement is active.")
            return
        resources = self.get_visa_resources()
        addresses = ["VIRTUAL"] + resources
        current_source = self.source_address_entry.get()
        current_detector = self.detector_address_entry.get()
        current_field = self.field_reader_address_entry.get()
        self.source_address_entry["values"] = addresses
        self.detector_address_entry["values"] = addresses
        self.field_reader_address_entry["values"] = ["NONE", "VIRTUAL"] + resources
        self.source_address_entry.set(
            current_source if current_source in addresses else "VIRTUAL"
        )
        self.detector_address_entry.set(
            current_detector if current_detector in addresses else "VIRTUAL"
        )
        field_values = self.field_reader_address_entry["values"]
        self.field_reader_address_entry.set(
            current_field if current_field in field_values else "NONE"
        )
        print("Instrument list refreshed")

    @staticmethod
    def _connect(address, instrument_type, virtual_class):
        if address.upper() == "VIRTUAL":
            return virtual_class(address="VIRTUAL")
        instrument = autodetect(address=address, required_type=instrument_type)
        if instrument is None:
            raise ConnectionError(
                f"Could not identify {address!r} as {instrument_type.__name__}"
            )
        return instrument

    def _profile_widgets(self):
        return {
            **self.dynamic_inputs,
            **{key: getattr(self, key + "_entry") for key in (
                "source_address", "detector_address", "field_reader_address",
                "source_channel", "field_per_volt", "field_offset",
            )},
            "calibration_path": self.calibration_entry,
        }

    def _on_geometry_changed(self, event=None):
        """Keep independent session-local setups; new geometries start in demo mode."""
        if self.is_measuring or (self.runner is not None and not self.runner.can_close()):
            self.geometry_entry.set(self._selected_geometry)
            return
        geometry = self.geometry_entry.get()
        if geometry == self._selected_geometry:
            return
        widgets = self._profile_widgets()
        self._geometry_settings[self._selected_geometry] = {
            key: widget.get() for key, widget in widgets.items()
        }
        settings = self._geometry_settings.get(geometry, DEFAULTS)
        for key, widget in widgets.items():
            if key.endswith("address"):
                widget.set(settings[key])
            else:
                self._set_entry(widget, settings[key])
        self._selected_geometry = geometry
        self.status_label.config(text=f"{geometry} setup selected; verify settings before running")

    def _settings(self):
        calibration = FieldCalibration.load_csv(self.calibration_entry.get())
        outputs = make_output_cycle(
            self.dynamic_inputs["output_min"].get(),
            self.dynamic_inputs["output_max"].get(),
            self.dynamic_inputs["points_per_cycle"].get(),
        )
        calibration.field_at_output(outputs)
        source_channel_text = self.source_channel_entry.get().strip()
        save_dir = Path(self.save_dir_entry.get()).expanduser()
        if self.save_data.get() and not save_dir.is_dir():
            raise ValueError("Save directory must already exist")
        return {
            "source_address": self.source_address_entry.get(),
            "detector_address": self.detector_address_entry.get(),
            "field_reader_address": self.field_reader_address_entry.get(),
            "field_per_volt": float(self.field_per_volt_entry.get()),
            "field_offset": float(self.field_offset_entry.get()),
            "calibration": calibration,
            "outputs": outputs,
            "source_channel": (
                None if not source_channel_text else int(source_channel_text)
            ),
            "save_dir": str(save_dir),
            "n_cycles": int(self.dynamic_inputs["n_cycles"].get()),
            "average_cycles": int(self.dynamic_inputs["average_cycles"].get()),
            "compliance": float(self.dynamic_inputs["compliance"].get()),
            "max_output_step": float(self.dynamic_inputs["max_output_step"].get()),
            "dwell_time": float(self.dynamic_inputs["dwell_time"].get()),
            "ramp_delay": float(self.dynamic_inputs["ramp_delay"].get()),
            "raw_window_points": int(self.dynamic_inputs["raw_window_points"].get()),
        }

    def _create_experiment(self):
        geometry = self.geometry_entry.get()
        profile = MokeSetupProfile(
            geometry, self._settings(), self._shutdown_handlers.get(geometry)
        )
        settings = profile.settings
        source_address = settings["source_address"]
        detector_address = settings["detector_address"]
        field_address = settings["field_reader_address"]
        if detector_address == "VIRTUAL" and source_address != "VIRTUAL":
            raise ValueError(
                "The virtual detector requires the virtual source; select a real "
                "detector DMM for physical-source operation"
            )
        if field_address == "VIRTUAL" and source_address != "VIRTUAL":
            raise ValueError("The virtual field reader requires the virtual source")
        if field_address not in ("NONE", "VIRTUAL") and field_address == detector_address:
            raise ValueError("Detector and field reader require separate DMMs")
        self._active_profile = profile

        source = self._connect(source_address, Sourcemeter, VirtualSourcemeter)
        self._instruments = [source]
        detector = self._connect(detector_address, DMM, VirtualDMM)
        self._instruments.append(detector)
        if source_address == "VIRTUAL" and detector_address == "VIRTUAL":
            connect_virtual_detector(source, detector, settings["calibration"])

        field_reader = None
        field_reader_name = ""
        if field_address == "VIRTUAL":
            source_key = (
                "source_voltage"
                if settings["calibration"].output_unit == "V"
                else "source_current"
            )

            def field_reader():
                return settings["calibration"].field_at_output(
                    source.state[source_key]
                )

            field_reader_name = "ideal virtual field reader"
        elif field_address != "NONE":
            if field_address == detector_address:
                raise ValueError(
                    "Detector and field reader require separate DMMs"
                )
            field_dmm = self._connect(field_address, DMM, VirtualDMM)
            self._instruments.append(field_dmm)
            field_dmm.set_sense_function(sense_func="VOLT")
            field_dmm.set_measurement_coupling(coupling="DC")
            field_per_volt = settings["field_per_volt"]
            field_offset = settings["field_offset"]

            def field_reader():
                return field_dmm.get_voltage() * field_per_volt + field_offset

            field_reader_name = field_dmm.idn()

        return MokeMeasurement(
            sourcemeter=source,
            dmm=detector,
            calibration=settings["calibration"],
            output_values=settings["outputs"],
            compliance=settings["compliance"],
            max_output_step=settings["max_output_step"],
            dwell_time=settings["dwell_time"],
            ramp_delay=settings["ramp_delay"],
            n_cycles=settings["n_cycles"],
            average_cycles=settings["average_cycles"],
            raw_window_points=settings["raw_window_points"],
            source_channel=settings["source_channel"],
            geometry=profile.geometry,
            shutdown_handler=profile.shutdown_handler,
            field_reader=field_reader,
            field_reader_unit=(
                settings["calibration"].field_unit if field_reader else None
            ),
            field_reader_name=field_reader_name,
            output_dir=settings["save_dir"],
        )

    def run_measurement(self):
        if self.is_measuring or (self.runner is not None and not self.runner.can_close()):
            return
        try:
            self.experiment = self._create_experiment()
        except Exception as error:
            messagebox.showerror("MOKE setup error", str(error))
            print(f"MOKE setup error: {error}")
            self._close_instruments()
            return

        self.is_measuring = True
        self._save_this_run = bool(self.save_data.get())
        self.status_label.config(text="Running: 0 complete cycles")
        self.run_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self._terminal_event = None
        self.runner = MeasurementRunner(self.experiment)
        try:
            self.runner.start(save=self._save_this_run)
        except BaseException as error:
            messagebox.showerror("MOKE start error", str(error))
            self.is_measuring = False
            if self.runner.can_close():
                self._close_instruments()
                self.run_button.config(state="normal")
            self.stop_button.config(state="disabled")

    def _close_instruments(self):
        seen = set()
        for instrument in self._instruments:
            if id(instrument) in seen:
                continue
            seen.add(id(instrument))
            close = getattr(instrument, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._instruments = []

    def stop_measurement(self):
        if getattr(self, "is_measuring", False) and getattr(self, "runner", None) is not None:
            self.status_label.config(text="Stopping and returning output to zero...")
            self.stop_button.config(state="disabled")
            self.runner.request_stop()

    def _poll_events(self):
        if self.runner is not None:
            terminal_received = self._terminal_event is not None
            try:
                while True:
                    event = self.runner.control_queue.get_nowait()
                    if isinstance(event, SafetyAlertEvent):
                        self.status_label.config(text="Hardware unsafe: retain connections for recovery")
                    elif isinstance(event, TerminalEvent):
                        terminal_received = True
                        self._terminal_event = event
                        if event.final_snapshot is not None:
                            self._plot_snapshot(event.final_snapshot)
                        print(
                            f"Measurement finished with state {event.state.value}, "
                            f"safety {event.safety.status.value}"
                        )
                        if event.filename:
                            print(f"Data saved to: {event.filename}")
                        elif event.partial_filename:
                            print(f"Partial data saved to: {event.partial_filename}")

                        recovery_paths = (
                            event.record.metadata.get("recoverable_staging_paths", ())
                            if event.record is not None else ()
                        )
                        if recovery_paths:
                            print(f"Recoverable data staging paths: {recovery_paths}")

                        if event.primary_error_message:
                            messagebox.showerror("MOKE measurement failed", event.primary_error_message)
            except queue.Empty:
                pass
            # The display queue already coalesces updates. Bound rendering per tick
            # so a fast producer cannot monopolize Tk or delay control delivery.
            try:
                snapshot = self.runner.display_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                if not terminal_received:
                    self._plot_snapshot(snapshot)
            # Terminal delivery can precede worker exit. Retain ownership until both finish.
            if self._terminal_event is not None and not self.runner.is_worker_alive:
                event = self._terminal_event
                self._terminal_event = None
                self.is_measuring = False
                if hasattr(self, "stop_button") and self.stop_button is not None:
                    self.stop_button.config(state="disabled")
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(text=f"{event.state.value}: safety {event.safety.status.value}")
                if self.runner.can_close():
                    self._close_instruments()
                    if hasattr(self, "run_button") and self.run_button is not None:
                        self.run_button.config(state="normal")
            if self._close_when_safe and self.runner.can_close():
                self._close_instruments()
                self._finish_close()
                return
        if self.root.winfo_exists():
            self._poll_events_id = self.root.after(50, self._poll_events)

    def _plot_snapshot(self, snapshot):
        self._last_snapshot = snapshot
        self.ax.clear()
        x_column = getattr(snapshot, "field_column", None) or "field_calibrated"
        y_column = "detector_voltage"

        units = getattr(self.experiment, "column_units", {}) if getattr(self, "experiment", None) is not None else {}
        x_unit = units.get(x_column)
        y_unit = units.get(y_column, "V")

        x_label = f"{x_column} ({x_unit})" if x_unit else (x_column or "field")
        y_label = f"{y_column} ({y_unit})" if y_unit else y_column

        show_raw = getattr(self, "show_raw", None)
        show_last = getattr(self, "show_last", None)
        show_average = getattr(self, "show_average", None)

        if (show_raw is None or show_raw.get()) and getattr(snapshot, "raw", None) is not None and not snapshot.raw.empty:
            self.ax.plot(
                snapshot.raw[x_column], snapshot.raw[y_column],
                color="#888888", alpha=0.45, linewidth=1, label="real-time raw",
            )
        if (show_last is None or show_last.get()) and getattr(snapshot, "last_cycle", None) is not None and not snapshot.last_cycle.empty:
            self.ax.plot(
                snapshot.last_cycle[x_column], snapshot.last_cycle[y_column],
                color="#4C9AFF", linewidth=2, label="last complete cycle",
            )
        if (show_average is None or show_average.get()) and getattr(snapshot, "cycle_average", None) is not None and not snapshot.cycle_average.empty:
            self.ax.plot(
                snapshot.cycle_average[x_column],
                snapshot.cycle_average[y_column],
                color="#FFB020", linewidth=3, label="cycle average",
            )
        self.ax.set_xlabel(x_label)
        self.ax.set_ylabel(y_label)
        geometry = snapshot.get("geometry", getattr(self.experiment, "geometry", "unspecified"))
        self.ax.set_title(f"MOKE loop: {geometry}")
        if self.ax.lines:
            self.ax.legend()
        if getattr(self, "canvas", None) is not None:
            self.canvas.draw_idle()

    def _redraw_current(self):
        if getattr(self, "_last_snapshot", None) is not None:
            self._plot_snapshot(self._last_snapshot)

    def on_closing(self):
        if getattr(self, "runner", None) is not None:
            self._close_when_safe = True
            self.runner.request_close()
            if not self.runner.can_close():
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(text="Waiting for worker exit and confirmed hardware safety...")
                return
        self._close_instruments()
        self._finish_close()

    def _finish_close(self):
        self._close_when_safe = False
        if self._poll_events_id is not None:
            try:
                self.root.after_cancel(self._poll_events_id)
            except Exception:
                pass
            self._poll_events_id = None
        super().on_closing()


if __name__ == "__main__":
    root = tk.Tk()
    app = MokeMeasurementApp(root)
    root.mainloop()
