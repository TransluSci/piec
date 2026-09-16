import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import math
import os
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import pandas as pd

from piec.drivers.dmm.keithley193a import Keithley193a
from piec.drivers.dc_calibrator.edc522 import EDC522
from piec.drivers.stepper_motor.arduino_stepper import Geos_Stepper
from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation.setups import connect_amr_plant
from piec.measurement.amr import AMR, TuningStatus
from piec.measurement import MeasurementRunner
from piec.measurement.contracts import SafetyAlertEvent, SafetyStatus, TerminalEvent
from piec.measurement.gui_utils import MeasurementApp

DEFAULTS = {
    "dmm_address": "VIRTUAL",
    "calibrator_address": "VIRTUAL",
    "stepper_address": "VIRTUAL",
    "lockin_address": "VIRTUAL",
    "current_source_address": "NONE",
    "excitation_source": "Lock-in Internal (AC)",
    "readout_mode": "Lock-in (AC)",
    "save_dir": r"your\default\save\directory",
    "field": 100.0,
    "angle_step": 10.0,
    "total_angle": 360.0,
    "amplitude": 1.0,
    "frequency": 10.0,
    "current": 1e-4,
    "compliance": 2.0,
    "measure_time": 1.0,
    "sensitivity": "50uv/pa",
    "voltage_calibration": 10000.0,
    "initialize_lockin": False,
}

class AMRApp(MeasurementApp):
    def __init__(self, root, *, excitation_shutdown_handler=None):
        super().__init__(root, title="AMR Measurement GUI", geometry="1400x820")
        print("Welcome to the AMR Measurement GUI!")
        print("Ctrl+Enter: Run Measurement")

        self.experiment = None
        self.runner = None
        self._terminal_event = None
        self._awaiting_terminal = False
        self._closing = False
        self._close_when_safe = False
        self._instruments = []
        self._active_lockin = None
        self._current_plot_data = None
        self._last_snapshot = None
        self._save_this_run = False
        self.is_measuring = False
        self.paused = False
        self.excitation_shutdown_handler = excitation_shutdown_handler

        visa_resources = self.get_visa_resources()

        # Static Inputs
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])

        # Row 1: Electromagnet Field Calibrator
        ttk.Label(self.static_frame, text="Calibrator (Field):").grid(row=1, column=0, sticky="w")
        self.calibrator_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.calibrator_address_entry.grid(row=1, column=1, padx=5, pady=2)
        self.calibrator_address_entry.set(DEFAULTS["calibrator_address"])

        ttk.Button(self.static_frame, text="Refresh", command=self.refresh_instruments, style="TButton").grid(row=1, column=2, padx=5)
        ttk.Button(self.static_frame, text="Autodetect", command=self.autodetect_instruments, style="TButton").grid(row=2, column=2, padx=5)
        ttk.Button(self.static_frame, text="Test Stepper", command=self.test_stepper, style="TButton").grid(row=3, column=2, padx=5)

        # Row 2: Sample Rotation Stepper
        ttk.Label(self.static_frame, text="Stepper (Angle):").grid(row=2, column=0, sticky="w")
        self.stepper_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.stepper_address_entry.grid(row=2, column=1, padx=5, pady=2)
        self.stepper_address_entry.set(DEFAULTS["stepper_address"])

        # Row 3: Excitation Source (Lock-in Oscillator vs Sourcemeter)
        ttk.Label(self.static_frame, text="Excitation Source:").grid(row=3, column=0, sticky="w")
        self.excitation_source_entry = ttk.Combobox(
            self.static_frame,
            values=["Lock-in Internal (AC)", "External Sourcemeter (DC)"],
            state="readonly"
        )
        self.excitation_source_entry.grid(row=3, column=1, padx=5, pady=2)
        self.excitation_source_entry.set(DEFAULTS.get("excitation_source", "Lock-in Internal (AC)"))
        self.excitation_source_entry.bind("<<ComboboxSelected>>", self._on_excitation_source_changed)

        # Row 4: External Sourcemeter Address
        ttk.Label(self.static_frame, text="Sourcemeter Address:").grid(row=4, column=0, sticky="w")
        self.current_source_entry = ttk.Combobox(
            self.static_frame,
            values=["NONE", "VIRTUAL"] + list(visa_resources),
            state="readonly"
        )
        self.current_source_entry.grid(row=4, column=1, padx=5, pady=2)
        self.current_source_entry.set(DEFAULTS["current_source_address"])
        self.current_source_entry.bind("<<ComboboxSelected>>", self._on_current_source_changed)

        # Row 5: Voltage Readout Mode (Lock-in AC vs DMM DC)
        ttk.Label(self.static_frame, text="Voltage Readout:").grid(row=5, column=0, sticky="w")
        self.readout_mode_entry = ttk.Combobox(self.static_frame, values=["Lock-in (AC)", "DMM (DC)"], state="readonly")
        self.readout_mode_entry.grid(row=5, column=1, padx=5, pady=2)
        self.readout_mode_entry.set(DEFAULTS["readout_mode"])
        self.readout_mode_entry.bind("<<ComboboxSelected>>", self._update_ui_state)

        # Row 6: Lock-in Address
        ttk.Label(self.static_frame, text="Lock-in Address:").grid(row=6, column=0, sticky="w")
        self.lockin_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.lockin_address_entry.grid(row=6, column=1, padx=5, pady=2)
        self.lockin_address_entry.set(DEFAULTS["lockin_address"])

        # Row 7: DMM Address
        ttk.Label(self.static_frame, text="DMM Address:").grid(row=7, column=0, sticky="w")
        self.dmm_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.dmm_address_entry.grid(row=7, column=1, padx=5, pady=2)
        self.dmm_address_entry.set(DEFAULTS["dmm_address"])

        ttk.Button(self.static_frame, text="Refresh", command=self.refresh_instruments, style="TButton").grid(row=1, column=2, padx=5)
        ttk.Button(self.static_frame, text="Autodetect", command=self.autodetect_instruments, style="TButton").grid(row=2, column=2, padx=5)
        ttk.Button(self.static_frame, text="Test Stepper", command=self.test_stepper, style="TButton").grid(row=3, column=2, padx=5)

        # Initialize dynamic inputs and plot config
        self.setup_dynamic_inputs()

        # Bench Setup & Live Tuning Frame
        self.setup_tuning_frame()

        # Status label
        self.status_label = ttk.Label(self.plot_config_frame, text="Ready")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        # Initial UI enable/disable sync
        self._update_ui_state()

        # Periodic runner polling
        self._poll_id = self.root.after(50, self._poll_runner)

    def _busy(self) -> bool:
        """
        Returns True if an operation is active, awaiting terminal delivery,
        or if hardware ownership is locked due to an unclosed runner or retained unsafe state.
        """
        if getattr(self, "is_measuring", False):
            return True
        if getattr(self, "_awaiting_terminal", False):
            return True
        runner = getattr(self, "runner", None)
        if runner is not None and not runner.can_close():
            return True
        if getattr(self, "_instruments", None):
            return True
        return False

    def setup_dynamic_inputs(self):
        """Initializes the measurement parameters and plot configuration."""
        # Dynamic Inputs - AMR parameters
        self.dynamic_frame.config(text="AMR MEASUREMENT INPUTS")
        self.dynamic_inputs = {}

        ttk.Label(self.dynamic_frame, text="Magnetic Field (Oe):").grid(row=0, column=0, sticky="w")
        self.dynamic_inputs["field"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["field"].grid(row=0, column=1, padx=5, pady=2)
        self.dynamic_inputs["field"].insert(0, DEFAULTS["field"])

        ttk.Label(self.dynamic_frame, text="Angle Step (deg):").grid(row=1, column=0, sticky="w")
        self.dynamic_inputs["angle_step"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["angle_step"].grid(row=1, column=1, padx=5, pady=2)
        self.dynamic_inputs["angle_step"].insert(0, DEFAULTS["angle_step"])

        ttk.Label(self.dynamic_frame, text="Total Angle (deg):").grid(row=2, column=0, sticky="w")
        self.dynamic_inputs["total_angle"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["total_angle"].grid(row=2, column=1, padx=5, pady=2)
        self.dynamic_inputs["total_angle"].insert(0, DEFAULTS["total_angle"])

        ttk.Label(self.dynamic_frame, text="Measure Time (s):").grid(row=3, column=0, sticky="w")
        self.dynamic_inputs["measure_time"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["measure_time"].grid(row=3, column=1, padx=5, pady=2)
        self.dynamic_inputs["measure_time"].insert(0, DEFAULTS["measure_time"])

        ttk.Label(self.dynamic_frame, text="Ext Current (A):").grid(row=4, column=0, sticky="w")
        self.dynamic_inputs["current"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["current"].grid(row=4, column=1, padx=5, pady=2)
        self.dynamic_inputs["current"].insert(0, DEFAULTS["current"])

        ttk.Label(self.dynamic_frame, text="Ext Compliance (V):").grid(row=5, column=0, sticky="w")
        self.dynamic_inputs["compliance"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["compliance"].grid(row=5, column=1, padx=5, pady=2)
        self.dynamic_inputs["compliance"].insert(0, DEFAULTS["compliance"])

        ttk.Label(self.dynamic_frame, text="Lock-in Amplitude (V):").grid(row=6, column=0, sticky="w")
        self.dynamic_inputs["amplitude"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["amplitude"].grid(row=6, column=1, padx=5, pady=2)
        self.dynamic_inputs["amplitude"].insert(0, DEFAULTS["amplitude"])

        ttk.Label(self.dynamic_frame, text="Lock-in Frequency (Hz):").grid(row=7, column=0, sticky="w")
        self.dynamic_inputs["frequency"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["frequency"].grid(row=7, column=1, padx=5, pady=2)
        self.dynamic_inputs["frequency"].insert(0, DEFAULTS["frequency"])

        ttk.Label(self.dynamic_frame, text="Lock-in Sensitivity:").grid(row=8, column=0, sticky="w")
        self.dynamic_inputs["sensitivity"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["sensitivity"].grid(row=8, column=1, padx=5, pady=2)
        self.dynamic_inputs["sensitivity"].insert(0, DEFAULTS["sensitivity"])

        # Checkbox for optional lock-in initialization (defaults to False to preserve manual settings)
        self.initialize_lockin_var = tk.BooleanVar(value=DEFAULTS["initialize_lockin"])
        self.initialize_lockin_checkbox = ttk.Checkbutton(
            self.dynamic_frame,
            text="Initialize Lock-in? (Overwrites manual front-panel settings)",
            variable=self.initialize_lockin_var
        )
        self.initialize_lockin_checkbox.grid(row=9, column=0, columnspan=2, pady=2, sticky="w")

        # Plot configuration
        ttk.Label(self.plot_config_frame, text="X-axis:").grid(row=0, column=0, sticky="w")
        self.x_axis = ttk.Combobox(self.plot_config_frame, values=["angle", "field", "x", "y"], state="readonly")
        self.x_axis.grid(row=0, column=1, padx=5, pady=2)
        self.x_axis.set("angle")
        self.x_axis.bind("<<ComboboxSelected>>", self.plot_data)

        ttk.Label(self.plot_config_frame, text="Y-axis:").grid(row=1, column=0, sticky="w")
        self.y_axis = ttk.Combobox(self.plot_config_frame, values=["angle", "field", "x", "y"], state="readonly")
        self.y_axis.grid(row=1, column=1, padx=5, pady=2)
        self.y_axis.set("x")
        self.y_axis.bind("<<ComboboxSelected>>", self.plot_data)

    def setup_tuning_frame(self):
        """Initializes bench setup & live signal preview / tuning controls."""
        self.tuning_frame = ttk.LabelFrame(self.left_panel, text="BENCH SETUP & LIVE TUNING", padding=10, style="Card.TLabelframe")
        self.tuning_frame.pack(fill=tk.X, expand=False, pady=(0, 10), padx=10)

        # Setup configuration summary badge
        self.tune_mode_summary = ttk.Label(
            self.tuning_frame,
            text="Setup: Excitation = Lock-in Internal (AC) | Readout = Lock-in (AC)",
            font=("Segoe UI", 9, "italic"),
        )
        self.tune_mode_summary.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        btn_frame = ttk.Frame(self.tuning_frame, style="Card.TFrame")
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 5))

        self.test_excitation_btn = ttk.Button(
            btn_frame,
            text="Test Excitation",
            command=self.test_excitation_action,
            style="TButton",
        )
        self.test_excitation_btn.pack(side="left", padx=(0, 5), expand=True, fill=tk.X)

        self.auto_gain_btn = ttk.Button(
            btn_frame,
            text="Auto-Gain",
            command=self.auto_gain_action,
            style="TButton",
        )
        self.auto_gain_btn.pack(side="left", padx=(5, 0), expand=True, fill=tk.X)

        self.tune_signal_label = ttk.Label(self.tuning_frame, text="Signal: --")
        self.tune_signal_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=2)

        self.tune_res_label = ttk.Label(self.tuning_frame, text="Estimated R: --")
        self.tune_res_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        self.tune_status_label = ttk.Label(self.tuning_frame, text="Status: Idle")
        self.tune_status_label.grid(row=4, column=0, sticky="w", pady=2)

        self.tune_settings_label = ttk.Label(self.tuning_frame, text="Active Sens: --")
        self.tune_settings_label.grid(row=4, column=1, sticky="e", pady=2)

    def is_external_excitation(self) -> bool:
        """Returns True if the user selected external excitation (sourcemeter), False for internal Lock-in."""
        if hasattr(self, "excitation_source_entry"):
            mode = self.excitation_source_entry.get().strip()
            if "External" in mode or "Sourcemeter" in mode:
                return True
            if "Lock-in" in mode or "Internal" in mode:
                return False
        if hasattr(self, "current_source_entry"):
            val = self.current_source_entry.get().strip().upper()
            return val not in ("", "NONE")
        return False

    def _on_excitation_source_changed(self, event=None):
        """Called when Excitation Source combobox changes."""
        mode = self.excitation_source_entry.get().strip() if hasattr(self, "excitation_source_entry") else "Lock-in Internal (AC)"
        if "External" in mode or "Sourcemeter" in mode:
            if hasattr(self, "current_source_entry"):
                curr = self.current_source_entry.get().strip().upper()
                if curr in ("", "NONE"):
                    self.current_source_entry.set("VIRTUAL")
        else:
            if hasattr(self, "current_source_entry"):
                self.current_source_entry.set("NONE")
        self._update_ui_state()

    def _on_current_source_changed(self, event=None):
        """Called when Sourcemeter Address combobox changes."""
        if hasattr(self, "current_source_entry") and hasattr(self, "excitation_source_entry"):
            curr = self.current_source_entry.get().strip().upper()
            if curr not in ("", "NONE"):
                self.excitation_source_entry.set("External Sourcemeter (DC)")
            else:
                self.excitation_source_entry.set("Lock-in Internal (AC)")
        self._update_ui_state()

    def _update_ui_state(self, event=None):
        """Updates enabled/disabled states of controls based on readout mode and excitation source."""
        if hasattr(self, "excitation_source_entry") and hasattr(self, "current_source_entry"):
            curr_src = self.current_source_entry.get().strip().upper()
            mode = self.excitation_source_entry.get().strip()
            if curr_src not in ("", "NONE") and ("Internal" in mode or "Lock-in" in mode):
                self.excitation_source_entry.set("External Sourcemeter (DC)")
            elif curr_src in ("", "NONE") and ("External" in mode or "Sourcemeter" in mode):
                self.current_source_entry.set("VIRTUAL")

        is_external = self.is_external_excitation()
        readout_mode = self.readout_mode_entry.get().strip() if hasattr(self, "readout_mode_entry") else "Lock-in (AC)"
        is_dmm_dc = "DMM" in readout_mode

        # Update Live Summary in Tuning card
        if hasattr(self, "tune_mode_summary"):
            exc_desc = "External Sourcemeter (DC)" if is_external else "Lock-in Internal (AC)"
            read_desc = "DMM (DC)" if is_dmm_dc else "Lock-in (AC)"
            self.tune_mode_summary.config(text=f"Setup: Excitation = {exc_desc} | Readout = {read_desc}")

        # External Sourcemeter controls (Address, Current, Compliance)
        sm_state = "normal" if is_external else "disabled"
        if hasattr(self, "current_source_entry"):
            self.current_source_entry.config(state="normal" if is_external else "disabled")
        for key in ("current", "compliance"):
            if key in self.dynamic_inputs:
                self.dynamic_inputs[key].config(state=sm_state)

        # Lock-in controls (Amplitude, Frequency, Sensitivity, Auto-Gain, Initialize checkbox)
        lockin_state = "disabled" if is_dmm_dc else "normal"
        for key in ("amplitude", "frequency", "sensitivity"):
            if key in self.dynamic_inputs:
                self.dynamic_inputs[key].config(state=lockin_state)
        if hasattr(self, "initialize_lockin_checkbox"):
            self.initialize_lockin_checkbox.config(state=lockin_state)
        if hasattr(self, "auto_gain_btn"):
            self.auto_gain_btn.config(state=lockin_state)

        # Lock-in Address is disabled when DMM DC readout is selected
        needs_lockin = not is_dmm_dc
        if hasattr(self, "lockin_address_entry"):
            self.lockin_address_entry.config(state="normal" if needs_lockin else "disabled")

        # DMM Address
        if hasattr(self, "dmm_address_entry"):
            self.dmm_address_entry.config(state="readonly")

    def save_settings(self):
        """Saves current widget values to a JSON file, including checkbox variables."""
        super().save_settings()
        filepath = self.get_settings_file_path()
        if filepath and os.path.exists(filepath):
            try:
                import json
                with open(filepath, "r") as f:
                    settings = json.load(f)
                if "dynamic" not in settings or not isinstance(settings["dynamic"], dict):
                    settings["dynamic"] = {}
                title = self.dynamic_frame.cget("text").strip()
                if title in settings["dynamic"] and isinstance(settings["dynamic"][title], dict):
                    settings["dynamic"][title]["Initialize Lock-in?"] = bool(self.initialize_lockin_var.get())
                else:
                    settings["dynamic"]["Initialize Lock-in?"] = bool(self.initialize_lockin_var.get())
                with open(filepath, "w") as f:
                    json.dump(settings, f, indent=4)
            except Exception as e:
                print(f"Failed to persist AMR checkbox settings: {e}")

    def load_settings(self):
        """Loads settings from JSON and populates widgets, restoring checkbox variables."""
        super().load_settings()
        filepath = self.get_settings_file_path()
        if not filepath or not os.path.exists(filepath):
            return
        try:
            import json
            with open(filepath, "r") as f:
                settings = json.load(f)
            dynamic_data = settings.get("dynamic", {})
            title = self.dynamic_frame.cget("text").strip()
            if isinstance(dynamic_data.get(title), dict):
                val = dynamic_data[title].get("Initialize Lock-in?")
            else:
                val = dynamic_data.get("Initialize Lock-in?")
            if val is not None:
                self.initialize_lockin_var.set(bool(val))
        except Exception as e:
            print(f"Failed to restore AMR checkbox settings: {e}")

    def test_stepper(self):
        if self._busy():
            print("ERROR: Cannot test stepper while hardware is busy or in an unsafe state.")
            return

        addr = self.stepper_address_entry.get().strip()
        if not addr:
            print("ERROR: No address selected for Stepper.")
            messagebox.showerror("Stepper Test Error", "No address selected for Stepper.")
            return

        print(f"Testing Stepper at {addr}...")
        inst = None
        try:
            inst = VirtualStepper(address=addr) if addr.upper() == "VIRTUAL" else Geos_Stepper(address=addr)
            self._instruments.append(inst)
            res = inst.idn()
            if "Not connected" not in res:
                print(f"SUCCESS: {res}")
            else:
                print(f"FAILURE: Stepper at {addr} returned '{res}'")
        except Exception as e:
            print(f"ERROR: Stepper test failed: {e}")
        finally:
            if inst is not None:
                self._close_instruments()

    def refresh_instruments(self):
        if self._busy():
            print("WARNING: Cannot refresh instruments while hardware is busy or in an unsafe state.")
            return

        print("Refreshing VISA instruments...")
        visa_resources = self.get_visa_resources()
        self.dmm_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.calibrator_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.stepper_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.lockin_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.current_source_entry["values"] = ["NONE", "VIRTUAL"] + list(visa_resources)

    def autodetect_instruments(self):
        if self._busy():
            print("WARNING: Cannot autodetect instruments while hardware is busy or in an unsafe state.")
            return

        print("Autodetecting instruments... this may take a moment.")
        try:
            from piec.drivers.autodetect import autodetect
            from piec.drivers.dmm.dmm import DMM
            from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
            from piec.drivers.stepper_motor.stepper_motor import Stepper
            from piec.drivers.lockin.lockin import Lockin
            from piec.drivers.sourcemeter.sourcemeter import Sourcemeter

            for category, driver_type, entry in (
                ("dmm", DMM, self.dmm_address_entry),
                ("dc_calibrator", DCCalibrator, self.calibrator_address_entry),
                ("stepper_motor", Stepper, self.stepper_address_entry),
                ("lockin", Lockin, self.lockin_address_entry),
                ("sourcemeter", Sourcemeter, self.current_source_entry),
            ):
                inst = autodetect(address=category, verbose=True, required_type=driver_type)
                if inst is None:
                    continue
                self._instruments.append(inst)
                try:
                    addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
                    entry.set(addr)
                    print(f"Detected {category} at {addr}")
                finally:
                    self._close_instruments()
                    self.cleanup_controls()
                if self._instruments:
                    raise RuntimeError("Autodetect connection could not be closed; retained for explicit close retry.")

            print("Autodetect complete.")
        except Exception as error:
            print(f"Autodetect failed: {error}")
            messagebox.showerror("Autodetect Error", f"Autodetect failed: {error}")

    def _create_bench_experiment(self):
        """Creates temporary instrument instances and AMR experiment for bench tuning."""
        dmm_addr = self.dmm_address_entry.get().strip()
        cal_addr = self.calibrator_address_entry.get().strip()
        step_addr = self.stepper_address_entry.get().strip()
        lock_addr = self.lockin_address_entry.get().strip()
        is_external = self.is_external_excitation()
        current_src_addr = self.current_source_entry.get().strip() if (hasattr(self, "current_source_entry") and is_external) else "NONE"
        readout_mode = self.readout_mode_entry.get().strip() if hasattr(self, "readout_mode_entry") else "Lock-in (AC)"
        is_dmm_dc = "DMM" in readout_mode

        if not dmm_addr or not cal_addr or not step_addr:
            raise ValueError("DMM, Calibrator, and Stepper addresses must be specified.")
        if not is_dmm_dc and not lock_addr:
            raise ValueError("Lock-in address must be specified for Lock-in readout.")
        if is_external and (not current_src_addr or current_src_addr.upper() == "NONE"):
            raise ValueError("External Sourcemeter excitation is selected, but Sourcemeter Address is NONE.")

        amplitude = float(self.dynamic_inputs["amplitude"].get()) if "amplitude" in self.dynamic_inputs else 1.0
        frequency = float(self.dynamic_inputs["frequency"].get()) if "frequency" in self.dynamic_inputs else 10.0
        current = float(self.dynamic_inputs["current"].get()) if "current" in self.dynamic_inputs else 1e-4
        compliance = float(self.dynamic_inputs["compliance"].get()) if "compliance" in self.dynamic_inputs else 2.0
        sensitivity = str(self.dynamic_inputs["sensitivity"].get()).strip() if "sensitivity" in self.dynamic_inputs else "50uv/pa"

        dmm = VirtualDMM(dmm_addr) if dmm_addr.upper() == "VIRTUAL" else Keithley193a(dmm_addr)
        self._instruments.append(dmm)

        calibrator = VirtualCalibrator(cal_addr, voltage_callibration=float(DEFAULTS["voltage_calibration"])) if cal_addr.upper() == "VIRTUAL" else EDC522(cal_addr)
        self._instruments.append(calibrator)

        stepper = VirtualStepper(step_addr) if step_addr.upper() == "VIRTUAL" else Geos_Stepper(step_addr)
        self._instruments.append(stepper)

        lockin = None
        if not is_dmm_dc or (lock_addr and lock_addr.upper() != "NONE"):
            lockin = VirtualLockin(lock_addr) if lock_addr.upper() == "VIRTUAL" else SRS830(lock_addr)
            self._instruments.append(lockin)
            self._active_lockin = lockin

        current_source = None
        if current_src_addr.upper() != "NONE":
            current_source = VirtualSourcemeter(current_src_addr) if current_src_addr.upper() == "VIRTUAL" else Keithley2400(current_src_addr)
            self._instruments.append(current_source)

        if all(addr.upper() == "VIRTUAL" for addr in (dmm_addr, cal_addr, step_addr, lock_addr if lockin else "VIRTUAL")):
            plant = None
            if lockin is not None:
                plant = connect_amr_plant(
                    calibrator, dmm, stepper, lockin,
                    field_scale=float(DEFAULTS["voltage_calibration"]),
                )
            if current_source is not None and isinstance(current_source, VirtualSourcemeter):
                if plant is not None:
                    current_source.set_load_hook(lambda mode, stimulus, compliance: plant.get_voltage_response(stimulus))
                if is_dmm_dc and plant is not None:
                    dmm.voltage_reader = lambda: plant.get_voltage_response(current_source.state.get("source_current", 0.0))[0]

        readout_inst = dmm if is_dmm_dc else lockin
        exp = AMR(
            dmm=dmm,
            calibrator=calibrator,
            stepper=stepper,
            lockin=lockin,
            readout=readout_inst,
            current_source=current_source,
            current=current if current_source is not None else None,
            compliance=compliance if current_source is not None else None,
            field=0.0,
            amplitude=amplitude,
            frequency=frequency,
            sensitivity=sensitivity,
            shutdown_handler=self.excitation_shutdown_handler or (self._simulation_excitation_shutdown if lockin is not None else None),
        )
        return exp

    def test_excitation_action(self):
        if self._busy():
            print("ERROR: Cannot test excitation while hardware is busy or in an unsafe state.")
            messagebox.showwarning("Busy", "Hardware is currently busy.")
            return

        print("Testing excitation / reading live bench signal...")
        if hasattr(self, "tune_status_label"):
            self.tune_status_label.config(text="Testing...", foreground="yellow")

        try:
            exp = self._create_bench_experiment()
            status = exp.test_excitation()
            if hasattr(self, "tune_signal_label"):
                self.tune_signal_label.config(
                    text=f"Signal: X = {status.x:.3e} V, Y = {status.y:.3e} V (V = {status.voltage:.3e} V)"
                )
            if hasattr(self, "tune_res_label"):
                if status.resistance is not None:
                    self.tune_res_label.config(text=f"Estimated R: {status.resistance:.2f} Ω")
                else:
                    self.tune_res_label.config(text="Estimated R: -- (Internal Lock-in source)")
            if hasattr(self, "tune_status_label"):
                if status.overloaded:
                    self.tune_status_label.config(text="OVERLOAD DETECTED!", foreground="red")
                else:
                    self.tune_status_label.config(text="Signal OK (No Overload)", foreground="green")
            if hasattr(self, "tune_settings_label") and status.active_settings:
                sens = status.active_settings.get("sensitivity", "--")
                self.tune_settings_label.config(text=f"Active Sens: {sens}")
            print(
                f"Excitation test completed: X={status.x:.3e} V, Y={status.y:.3e} V, "
                f"V={status.voltage:.3e} V, R={status.resistance}, overload={status.overloaded}"
            )
        except Exception as err:
            print(f"Excitation test failed: {err}")
            messagebox.showerror("Excitation Test Error", str(err))
            if hasattr(self, "tune_status_label"):
                self.tune_status_label.config(text=f"Error: {err}", foreground="red")
        finally:
            self._close_instruments()

    def auto_gain_action(self):
        if self._busy():
            print("ERROR: Cannot run auto-gain while hardware is busy or in an unsafe state.")
            messagebox.showwarning("Busy", "Hardware is currently busy.")
            return

        print("Running Auto-Gain on Lock-in...")
        try:
            exp = self._create_bench_experiment()
            new_sens = exp.auto_gain()
            if new_sens:
                if "sensitivity" in self.dynamic_inputs:
                    self.dynamic_inputs["sensitivity"].delete(0, tk.END)
                    self.dynamic_inputs["sensitivity"].insert(0, new_sens)
                if hasattr(self, "tune_settings_label"):
                    self.tune_settings_label.config(text=f"Active Sens: {new_sens}")
                print(f"Auto-gain completed. Set sensitivity to: {new_sens}")
                messagebox.showinfo("Auto-Gain", f"Sensitivity updated to: {new_sens}")
            else:
                print("Auto-gain did not return a new sensitivity.")
        except Exception as err:
            print(f"Auto-gain failed: {err}")
            messagebox.showerror("Auto-Gain Error", str(err))
        finally:
            self._close_instruments()

    def _simulation_excitation_shutdown(self):
        """Simulation-only excitation shutdown policy for virtual lock-in."""
        lockin = getattr(self, "_active_lockin", None)
        if lockin is None:
            raise RuntimeError("Simulation excitation shutdown failed: no active lock-in instrument.")
        if not isinstance(lockin, VirtualLockin):
            raise TypeError(
                f"Simulation excitation shutdown policy is restricted to VirtualLockin instances, "
                f"got {type(lockin).__name__}."
            )
        lockin.configure_reference(voltage=0.0)

    def run_measurement(self):
        if self._busy():
            print("Measurement already in progress or hardware retained in unsafe state...")
            return

        # Get addresses
        dmm_addr = self.dmm_address_entry.get().strip()
        cal_addr = self.calibrator_address_entry.get().strip()
        step_addr = self.stepper_address_entry.get().strip()
        lock_addr = self.lockin_address_entry.get().strip()
        current_src_addr = self.current_source_entry.get().strip() if hasattr(self, "current_source_entry") else "NONE"
        is_external = self.is_external_excitation()
        current_src_addr = self.current_source_entry.get().strip() if (hasattr(self, "current_source_entry") and is_external) else "NONE"
        readout_mode = self.readout_mode_entry.get().strip() if hasattr(self, "readout_mode_entry") else "Lock-in (AC)"
        is_dmm_dc = "DMM" in readout_mode
        raw_save_dir = self.save_dir_entry.get().strip()
        save_dir = raw_save_dir if (raw_save_dir and raw_save_dir != r"your\default\save\directory") else None

        if not dmm_addr or not cal_addr or not step_addr:
            msg = "All instrument addresses (DMM, Calibrator, Stepper) must be specified."
            print(msg)
            messagebox.showerror("Parameter Error", msg)
            return

        if not is_dmm_dc and not lock_addr:
            msg = "Lock-in address must be specified for Lock-in readout."
            print(msg)
            messagebox.showerror("Parameter Error", msg)
            return

        if is_dmm_dc and not is_external:
            msg = "DMM DC readout requires an external Current Source (sourcemeter). Please set Excitation Source to 'External Sourcemeter (DC)'."
            print(msg)
            messagebox.showerror("Parameter Error", msg)
            return

        if is_external and (not current_src_addr or current_src_addr.upper() == "NONE"):
            msg = "External Sourcemeter excitation is selected, but Sourcemeter Address is NONE. Please select a VISA address or VIRTUAL."
            print(msg)
            messagebox.showerror("Parameter Error", msg)
            return

        # Check virtual mode vs physical mode
        is_virtual = all(
            addr.upper() == "VIRTUAL"
            for addr in (dmm_addr, cal_addr, step_addr,
                         lock_addr if not is_dmm_dc else "VIRTUAL",
                         current_src_addr if current_src_addr.upper() != "NONE" else "VIRTUAL")
        )

        # Setup excitation shutdown handler:
        shutdown_handler = self.excitation_shutdown_handler
        if current_src_addr.upper() != "NONE":
            # SampleExcitation safely shuts down the external current source automatically
            pass
        else:
            if shutdown_handler is None and is_virtual:
                shutdown_handler = self._simulation_excitation_shutdown

            if not is_virtual and shutdown_handler == self._simulation_excitation_shutdown:
                msg = "Simulation excitation shutdown policy cannot be used for physical instruments."
                print(msg)
                messagebox.showerror("AMR Safety Requirement", msg)
                return

            if not callable(shutdown_handler):
                msg = "AMR setup requires an excitation_shutdown_handler that performs and verifies the bench shutdown action."
                print(msg)
                messagebox.showerror("AMR Safety Requirement", msg)
                return

        # Validate parameters before initializing drivers
        try:
            field = float(self.dynamic_inputs["field"].get())
            if not math.isfinite(field):
                raise ValueError(f"field must be finite, got {field}")

            angle_step = float(self.dynamic_inputs["angle_step"].get())
            if not math.isfinite(angle_step) or angle_step == 0:
                raise ValueError(f"angle_step must be non-zero and finite, got {angle_step}")

            total_angle = float(self.dynamic_inputs["total_angle"].get())
            if not math.isfinite(total_angle):
                raise ValueError(f"total_angle must be finite, got {total_angle}")

            if total_angle != 0 and (total_angle * angle_step < 0):
                raise ValueError(
                    f"angle_step ({angle_step}) direction opposes total_angle ({total_angle})"
                )

            count = abs(total_angle / angle_step)
            if count > 1_000_000:
                raise ValueError("Sweep exceeds one million intervals")

            measure_time = float(self.dynamic_inputs["measure_time"].get())
            if not math.isfinite(measure_time) or measure_time < 0:
                raise ValueError(f"measure_time must be non-negative, got {measure_time}")

            current = None
            compliance = None
            if current_src_addr.upper() != "NONE":
                current = float(self.dynamic_inputs["current"].get())
                if not math.isfinite(current) or current == 0:
                    raise ValueError(f"current must be non-zero and finite, got {current}")
                compliance = float(self.dynamic_inputs["compliance"].get())
                if not math.isfinite(compliance) or compliance <= 0:
                    raise ValueError(f"compliance must be positive and finite, got {compliance}")

            amplitude = 1.0
            frequency = 10.0
            sensitivity = "50uv/pa"
            initialize_lockin = False

            if not is_dmm_dc:
                amplitude = float(self.dynamic_inputs["amplitude"].get())
                if not math.isfinite(amplitude) or amplitude <= 0:
                    raise ValueError(f"amplitude must be positive, got {amplitude}")

                frequency = float(self.dynamic_inputs["frequency"].get())
                if not math.isfinite(frequency) or frequency <= 0:
                    raise ValueError(f"frequency must be positive, got {frequency}")

                sensitivity = str(self.dynamic_inputs["sensitivity"].get()).strip()
                if not sensitivity:
                    raise ValueError("sensitivity cannot be empty")

                initialize_lockin = bool(self.initialize_lockin_var.get())
        except Exception as err:
            print(f"Invalid measurement parameters: {err}")
            messagebox.showerror("Parameter Error", f"Invalid measurement parameters: {err}")
            return

        # Update defaults
        DEFAULTS["field"] = field
        DEFAULTS["angle_step"] = angle_step
        DEFAULTS["total_angle"] = total_angle
        DEFAULTS["amplitude"] = amplitude
        DEFAULTS["frequency"] = frequency
        DEFAULTS["measure_time"] = measure_time
        DEFAULTS["sensitivity"] = sensitivity
        DEFAULTS["initialize_lockin"] = initialize_lockin
        if current is not None:
            DEFAULTS["current"] = current
        if compliance is not None:
            DEFAULTS["compliance"] = compliance

        print("Running AMR measurement...")

        # Initialize drivers with immediate connection tracking and cleanup of partial failures
        self._instruments = []
        try:
            if dmm_addr.upper() == "VIRTUAL":
                dmm = VirtualDMM(dmm_addr)
            else:
                dmm = Keithley193a(dmm_addr)
            self._instruments.append(dmm)
                
            if cal_addr.upper() == "VIRTUAL":
                calibrator = VirtualCalibrator(cal_addr, voltage_callibration=float(DEFAULTS["voltage_calibration"]))
            else:
                calibrator = EDC522(cal_addr)
            self._instruments.append(calibrator)
                
            if step_addr.upper() == "VIRTUAL":
                stepper = VirtualStepper(step_addr)
            else:
                stepper = Geos_Stepper(step_addr)
            self._instruments.append(stepper)
                
            lockin = None
            if not is_dmm_dc or (lock_addr and lock_addr.upper() != "NONE"):
                if lock_addr.upper() == "VIRTUAL":
                    lockin = VirtualLockin(lock_addr)
                else:
                    lockin = SRS830(lock_addr)
                self._instruments.append(lockin)
                self._active_lockin = lockin

            current_source = None
            if current_src_addr.upper() != "NONE":
                if current_src_addr.upper() == "VIRTUAL":
                    current_source = VirtualSourcemeter(current_src_addr)
                else:
                    current_source = Keithley2400(current_src_addr)
                self._instruments.append(current_source)

            if all(addr.upper() == "VIRTUAL" for addr in (dmm_addr, cal_addr, step_addr, lock_addr if lockin else "VIRTUAL")):
                plant = None
                if lockin is not None:
                    plant = connect_amr_plant(
                        calibrator, dmm, stepper, lockin,
                        field_scale=float(DEFAULTS["voltage_calibration"]),
                    )
                    self._virtual_plant = plant
                if current_source is not None and isinstance(current_source, VirtualSourcemeter):
                    if plant is not None:
                        current_source.set_load_hook(lambda mode, stimulus, compliance: plant.get_voltage_response(stimulus))
                    if is_dmm_dc and plant is not None:
                        dmm.voltage_reader = lambda: plant.get_voltage_response(current_source.state.get("source_current", 0.0))[0]
        except Exception as error:
            messagebox.showerror("Driver initialization error", str(error))
            print(f"Driver initialization error: {error}")
            self._close_instruments()
            if hasattr(self, "status_label") and self.status_label is not None:
                self.status_label.config(text="Idle")
            return

        # Instantiate experiment
        try:
            readout_inst = dmm if is_dmm_dc else lockin
            self.experiment = AMR(
                dmm=dmm,
                calibrator=calibrator,
                stepper=stepper,
                lockin=lockin,
                readout=readout_inst,
                current_source=current_source,
                current=current,
                compliance=compliance,
                field=field,
                angle_step=angle_step,
                total_angle=total_angle,
                amplitude=amplitude,
                frequency=frequency,
                measure_time=measure_time,
                sensitivity=sensitivity,
                output_dir=save_dir,
                shutdown_handler=shutdown_handler,
            )
        except Exception as error:
            messagebox.showerror("AMR setup error", str(error))
            print(f"AMR setup error: {error}")
            self._close_instruments()
            if hasattr(self, "status_label") and self.status_label is not None:
                self.status_label.config(text="Idle")
            return

        self.is_measuring = True
        self.paused = False
        self._terminal_event = None
        self._awaiting_terminal = True
        self._current_plot_data = None
        self._save_this_run = bool(save_dir)

        if hasattr(self, 'run_button'):
            self.run_button.config(state='disabled')
        
        # Add stop and pause buttons during measurement
        self.add_control_buttons()
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.config(text="Running")

        # Run experiment via MeasurementRunner
        self.runner = MeasurementRunner(self.experiment)
        try:
            self.runner.start(
                save=self._save_this_run,
                options={'configure_lockin': initialize_lockin},
            )
        except BaseException as error:
            messagebox.showerror("AMR start error", str(error))
            print(f"AMR start error: {error}")
            if self.runner is None or self.runner.can_close():
                self.is_measuring = False
                self._awaiting_terminal = False
                self._terminal_event = None
                self._close_instruments()
                self.cleanup_controls()
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(text="Idle")
            else:
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(text="Start error: active ownership retained")

    def add_control_buttons(self):
        """Adds Stop and Pause buttons to the GUI."""
        if hasattr(self, 'control_frame') and self.control_frame is not None:
            try:
                self.control_frame.destroy()
            except Exception:
                pass

        self.control_frame = ttk.Frame(self.right_panel, style="TFrame")
        self.control_frame.grid(row=1, column=0, pady=10)
        
        self.pause_button = ttk.Button(self.control_frame, text="PAUSE", command=self.toggle_pause, style="TButton")
        self.pause_button.pack(side="left", padx=5)
        
        self.stop_button = ttk.Button(self.control_frame, text="STOP", command=self.stop_measurement, style="TButton")
        self.stop_button.pack(side="left", padx=5)
        
        # Hide the main run button
        self.run_button.grid_remove()

    def toggle_pause(self):
        if not self.is_measuring or self.runner is None:
            return
            
        self.paused = not self.paused
        self.runner.request_pause(self.paused)
        if hasattr(self, 'pause_button') and self.pause_button is not None:
            self.pause_button.config(text="RESUME" if self.paused else "PAUSE")
        if hasattr(self, 'status_label') and self.status_label is not None:
            self.status_label.config(text="Paused" if self.paused else "Running")
        print("Measurement paused." if self.paused else "Measurement resumed.")

    def stop_measurement(self):
        if not self.is_measuring or self.runner is None:
            return
            
        print("Stopping measurement...")
        if hasattr(self, 'stop_button') and self.stop_button is not None:
            self.stop_button.config(state='disabled')
        if hasattr(self, 'pause_button') and self.pause_button is not None:
            self.pause_button.config(state='disabled')
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.config(text="Stopping and returning field to zero...")
        self.runner.request_stop()

    def cleanup_controls(self):
        """Removes control buttons and restores the run button."""
        self.paused = False
        self.pause_button = None
        self.stop_button = None
        if hasattr(self, 'control_frame') and self.control_frame is not None:
            try:
                self.control_frame.destroy()
            except Exception:
                pass
            self.control_frame = None
        if hasattr(self, 'run_button') and self.run_button is not None:
            self.run_button.grid()
            if self._busy():
                self.run_button.config(state='disabled')
            else:
                self.run_button.config(state='normal')

    def plot_data(self, event=None):
        self._render_plot(self._current_plot_data)

    def _render_plot(self, data):
        """Display errors must not interrupt worker terminal handling or cleanup."""
        try:
            if data is None or data.empty:
                self.ax.clear()
                self.canvas.draw_idle()
            else:
                self._plot_data(data)
        except Exception as error:
            print(f"AMR plot error (data retained): {error}")

    def _plot_data(self, df=None):
        """Main-thread plotting with metadata-derived units from experiment."""
        if df is None:
            df = getattr(self, "_current_plot_data", None)
        if df is None or df.empty:
            return

        x_col = self.x_axis.get()
        y_col = self.y_axis.get()
        
        if x_col not in df.columns or y_col not in df.columns:
            return

        units = getattr(self.experiment, "column_units", {}) if self.experiment is not None else {}
        x_unit = units.get(x_col)
        y_unit = units.get(y_col)

        x_label = f"{x_col} ({x_unit})" if x_unit else x_col
        y_label = f"{y_col} ({y_unit})" if y_unit else y_col

        self.ax.clear()
        self.ax.plot(df[x_col], df[y_col], marker="o", color="blue", label=f"{y_col} vs {x_col}")
        self.ax.set_xlabel(x_label)
        self.ax.set_ylabel(y_label)
        self.ax.set_title("AMR Measurement Data")
        if hasattr(self, 'canvas') and self.canvas is not None:
            self.canvas.draw_idle()

    def _poll_runner(self):
        """Periodic main-thread polling for runner control and display events."""
        if self.runner is not None:
            terminal_seen = self._terminal_event is not None
            try:
                while True:
                    event = self.runner.control_queue.get_nowait()
                    if isinstance(event, SafetyAlertEvent):
                        print(f"SAFETY ALERT: {event.message}")
                        if hasattr(self, "status_label") and self.status_label is not None:
                            self.status_label.config(text="Hardware unsafe: connections retained")
                        messagebox.showerror("Safety Alert", f"Unsafe hardware state detected:\n{event.message}")
                    elif isinstance(event, TerminalEvent):
                        terminal_seen = True
                        self._terminal_event = event
                        # Authoritative terminal data view
                        terminal_df = None
                        if event.final_snapshot is not None:
                            terminal_df = event.final_snapshot.get_view("data")
                        if terminal_df is None:
                            terminal_df = event.data
                        self._current_plot_data = terminal_df
                        self._render_plot(terminal_df)
                        if hasattr(self, "status_label") and self.status_label is not None:
                            self.status_label.config(text=f"{event.state.value}: safety {event.safety.status.value}")
                        print(
                            f"Measurement finished with state {event.state.value}, "
                            f"safety {event.safety.status.value}"
                        )
                        if event.filename:
                            print(f"Data saved to: {event.filename}")
                        elif event.partial_filename:
                            print(f"Partial data saved to: {event.partial_filename}")

                        if event.primary_error_message:
                            messagebox.showerror("AMR measurement error", event.primary_error_message)
            except queue.Empty:
                pass

            # Drain display queue (bounded live snapshots)
            latest_snapshot = None
            try:
                while True:
                    latest_snapshot = self.runner.display_queue.get_nowait()
            except queue.Empty:
                pass

            if latest_snapshot is not None and not terminal_seen:
                self._last_snapshot = latest_snapshot
                raw_window = latest_snapshot.get_view("raw_window")
                if raw_window is not None and not raw_window.empty:
                    self._current_plot_data = raw_window
                    self._render_plot(raw_window)

            # Terminal delivery can precede worker exit. Retain ownership until both finish.
            if self._terminal_event is not None and not self.runner.is_worker_alive:
                event = self._terminal_event
                self._terminal_event = None
                self._awaiting_terminal = False
                self.is_measuring = False
                if self.runner.can_close():
                    self._close_instruments()
                    self.cleanup_controls()
                else:
                    self.cleanup_controls()
                    if hasattr(self, "status_label") and self.status_label is not None:
                        self.status_label.config(text="Unsafe shutdown: connections retained")
                    print("Retaining open connections due to non-safe status or runner close gate.")

            if (self._closing or self._close_when_safe) and self.runner.can_close() and not self._awaiting_terminal:
                self._close_instruments()
                if not self._instruments:
                    self._finish_close()
                    return

        if hasattr(self, "root") and getattr(self.root, "winfo_exists", None) and self.root.winfo_exists():
            self._poll_id = self.root.after(50, self._poll_runner)
        else:
            self._poll_id = None

    def _close_instruments(self):
        """Safely close instrument connections without crashing on errors."""
        seen = set()
        retained = []
        for instrument in self._instruments:
            if id(instrument) in seen:
                continue
            seen.add(id(instrument))
            close = getattr(instrument, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:
                    retained.append(instrument)
                    print(f"Instrument close failed; connection retained for retry: {error}")
        self._instruments = retained
        if retained:
            # Avoid repeatedly issuing failed close calls every polling tick.
            self._closing = self._close_when_safe = False
        else:
            self._active_lockin = None

    def on_closing(self):
        """Handle window close event with graceful runner stop and safe shutdown."""
        if getattr(self, "runner", None) is not None:
            self._closing = True
            self._close_when_safe = True
            self.runner.request_close()
            if not self.runner.can_close() or self._awaiting_terminal:
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(text="Waiting for worker exit and confirmed safety...")
                return
        if self.runner is None or self.runner.can_close():
            self._close_instruments()
        if not self._instruments:
            self._finish_close()

    def _finish_close(self):
        """Cancel pending polling and invoke parent window destruction."""
        self._closing = False
        self._close_when_safe = False
        if getattr(self, "_poll_id", None) is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        super().on_closing()

if __name__ == "__main__":
    root = tk.Tk()
    app = AMRApp(root)
    root.mainloop()
