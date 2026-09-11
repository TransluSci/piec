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
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.measurement.amr import AMR
from piec.measurement import MeasurementRunner
from piec.measurement.contracts import SafetyAlertEvent, SafetyStatus, TerminalEvent
from piec.measurement.gui_utils import MeasurementApp

DEFAULTS = {
    "dmm_address": "VIRTUAL",
    "calibrator_address": "VIRTUAL",
    "stepper_address": "VIRTUAL",
    "lockin_address": "VIRTUAL",
    "save_dir": r"your\default\save\directory",
    "field": 100.0,
    "angle_step": 10.0,
    "total_angle": 360.0,
    "amplitude": 1.0,
    "frequency": 10.0,
    "measure_time": 1.0,
    "sensitivity": "50uv/pa",
    "voltage_calibration": 10000.0,
    "initialize_lockin": False,
}

class AMRApp(MeasurementApp):
    def __init__(self, root, *, excitation_shutdown_handler=None):
        super().__init__(root, title="AMR Measurement GUI", geometry="1600x900")
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

        # Instrument selection row 1
        ttk.Label(self.static_frame, text="DMM Address:").grid(row=1, column=0, sticky="w")
        self.dmm_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.dmm_address_entry.grid(row=1, column=1, padx=5, pady=5)
        self.dmm_address_entry.set(DEFAULTS["dmm_address"])

        ttk.Label(self.static_frame, text="Calibrator Address:").grid(row=2, column=0, sticky="w")
        self.calibrator_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.calibrator_address_entry.grid(row=2, column=1, padx=5, pady=5)
        self.calibrator_address_entry.set(DEFAULTS["calibrator_address"])

        # Instrument selection row 2
        ttk.Label(self.static_frame, text="Stepper Address:").grid(row=3, column=0, sticky="w")
        self.stepper_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.stepper_address_entry.grid(row=3, column=1, padx=5, pady=5)
        self.stepper_address_entry.set(DEFAULTS["stepper_address"])

        ttk.Label(self.static_frame, text="Lock-in Address:").grid(row=4, column=0, sticky="w")
        self.lockin_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"] + list(visa_resources), state="readonly")
        self.lockin_address_entry.grid(row=4, column=1, padx=5, pady=5)
        self.lockin_address_entry.set(DEFAULTS["lockin_address"])

        ttk.Button(self.static_frame, text="Refresh", command=self.refresh_instruments, style="TButton").grid(row=1, column=2, padx=5)
        ttk.Button(self.static_frame, text="Autodetect", command=self.autodetect_instruments, style="TButton").grid(row=2, column=2, padx=5)
        ttk.Button(self.static_frame, text="Test Stepper", command=self.test_stepper, style="TButton").grid(row=3, column=2, padx=5)

        # Initialize dynamic inputs and plot config
        self.setup_dynamic_inputs()

        # Status label
        self.status_label = ttk.Label(self.plot_config_frame, text="Ready")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        # Periodic runner polling
        self._poll_id = self.root.after(50, self._poll_runner)

    def setup_dynamic_inputs(self):
        """Initializes the measurement parameters and plot configuration."""
        # Dynamic Inputs - AMR parameters
        self.dynamic_frame.config(text="AMR MEASUREMENT INPUTS")
        self.dynamic_inputs = {}

        ttk.Label(self.dynamic_frame, text="Magnetic Field (Oe):").grid(row=0, column=0, sticky="w")
        self.dynamic_inputs["field"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["field"].grid(row=0, column=1, padx=5, pady=5)
        self.dynamic_inputs["field"].insert(0, DEFAULTS["field"])

        ttk.Label(self.dynamic_frame, text="Angle Step (deg):").grid(row=1, column=0, sticky="w")
        self.dynamic_inputs["angle_step"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["angle_step"].grid(row=1, column=1, padx=5, pady=5)
        self.dynamic_inputs["angle_step"].insert(0, DEFAULTS["angle_step"])

        ttk.Label(self.dynamic_frame, text="Total Angle (deg):").grid(row=2, column=0, sticky="w")
        self.dynamic_inputs["total_angle"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["total_angle"].grid(row=2, column=1, padx=5, pady=5)
        self.dynamic_inputs["total_angle"].insert(0, DEFAULTS["total_angle"])

        ttk.Label(self.dynamic_frame, text="Amplitude (V):").grid(row=3, column=0, sticky="w")
        self.dynamic_inputs["amplitude"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["amplitude"].grid(row=3, column=1, padx=5, pady=5)
        self.dynamic_inputs["amplitude"].insert(0, DEFAULTS["amplitude"])

        ttk.Label(self.dynamic_frame, text="Frequency (Hz):").grid(row=4, column=0, sticky="w")
        self.dynamic_inputs["frequency"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["frequency"].grid(row=4, column=1, padx=5, pady=5)
        self.dynamic_inputs["frequency"].insert(0, DEFAULTS["frequency"])

        ttk.Label(self.dynamic_frame, text="Measure Time (s):").grid(row=5, column=0, sticky="w")
        self.dynamic_inputs["measure_time"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["measure_time"].grid(row=5, column=1, padx=5, pady=5)
        self.dynamic_inputs["measure_time"].insert(0, DEFAULTS["measure_time"])

        ttk.Label(self.dynamic_frame, text="Sensitivity:").grid(row=6, column=0, sticky="w")
        self.dynamic_inputs["sensitivity"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["sensitivity"].grid(row=6, column=1, padx=5, pady=5)
        self.dynamic_inputs["sensitivity"].insert(0, DEFAULTS["sensitivity"])

        # Checkbox for optional lock-in initialization (defaults to False to preserve manual settings)
        self.initialize_lockin_var = tk.BooleanVar(value=DEFAULTS["initialize_lockin"])
        self.initialize_lockin_checkbox = ttk.Checkbutton(
            self.dynamic_frame,
            text="Initialize Lock-in?",
            variable=self.initialize_lockin_var
        )
        self.initialize_lockin_checkbox.grid(row=7, column=0, columnspan=2, pady=5, sticky="w")

        # Plot configuration
        ttk.Label(self.plot_config_frame, text="X-axis:").grid(row=0, column=0, sticky="w")
        self.x_axis = ttk.Combobox(self.plot_config_frame, values=["angle", "field", "x", "y"], state="readonly")
        self.x_axis.grid(row=0, column=1, padx=5, pady=5)
        self.x_axis.set("angle")
        self.x_axis.bind("<<ComboboxSelected>>", self.plot_data)

        ttk.Label(self.plot_config_frame, text="Y-axis:").grid(row=1, column=0, sticky="w")
        self.y_axis = ttk.Combobox(self.plot_config_frame, values=["angle", "field", "x", "y"], state="readonly")
        self.y_axis.grid(row=1, column=1, padx=5, pady=5)
        self.y_axis.set("x")
        self.y_axis.bind("<<ComboboxSelected>>", self.plot_data)

    def test_stepper(self):
        if self.is_measuring:
            print("ERROR: Cannot test stepper while measurement is running.")
            return

        addr = self.stepper_address_entry.get()
        if not addr:
            print("ERROR: No address selected for Stepper.")
            return

        print(f"Testing Stepper at {addr}...")
        from piec.drivers.autodetect import _safe_close
        
        try:
            inst = Geos_Stepper(address=addr)
            res = inst.idn()
            if "Not connected" not in res:
                print(f"SUCCESS: {res}")
            else:
                print(f"FAILURE: Stepper at {addr} returned '{res}'")
            _safe_close(inst)
        except Exception as e:
            print(f"ERROR: Stepper test failed: {e}")

    def refresh_instruments(self):
        if self.is_measuring:
            print("WARNING: Cannot refresh instruments while measurement is in progress.")
            return

        print("Refreshing VISA instruments...")
        visa_resources = self.get_visa_resources()
        self.dmm_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.calibrator_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.stepper_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.lockin_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)

    def autodetect_instruments(self):
        if self.is_measuring:
            print("WARNING: Cannot autodetect instruments while measurement is in progress.")
            return

        print("Autodetecting instruments... this may take a moment.")
        from piec.drivers.autodetect import autodetect, _safe_close
        from piec.drivers.dmm.dmm import DMM
        from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
        from piec.drivers.stepper_motor.stepper_motor import Stepper
        from piec.drivers.lockin.lockin import Lockin

        inst = autodetect(address="dmm", verbose=True, required_type=DMM)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.dmm_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected DMM at {addr}")

        inst = autodetect(address="dc_calibrator", verbose=True, required_type=DCCalibrator)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.calibrator_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected Calibrator at {addr}")

        inst = autodetect(address="stepper_motor", verbose=True, required_type=Stepper)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.stepper_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected Stepper at {addr}")

        inst = autodetect(address="lockin", verbose=True, required_type=Lockin)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.lockin_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected Lockin at {addr}")

        print("Autodetect complete.")

    def _simulation_excitation_shutdown(self):
        """Simulation-only excitation shutdown policy for virtual lock-in."""
        lockin = getattr(self, "_active_lockin", None)
        if lockin is not None and hasattr(lockin, "configure_reference"):
            try:
                lockin.configure_reference(voltage=0.0)
            except Exception:
                pass

    def run_measurement(self):
        if self.is_measuring or (self.runner is not None and not self.runner.can_close()):
            print("Measurement already in progress...")
            return

        # Get addresses
        dmm_addr = self.dmm_address_entry.get().strip()
        cal_addr = self.calibrator_address_entry.get().strip()
        step_addr = self.stepper_address_entry.get().strip()
        lock_addr = self.lockin_address_entry.get().strip()
        raw_save_dir = self.save_dir_entry.get().strip()
        save_dir = raw_save_dir if (raw_save_dir and raw_save_dir != r"your\default\save\directory") else None

        # Check virtual mode vs physical mode
        is_virtual = all(addr.upper() == "VIRTUAL" for addr in (dmm_addr, cal_addr, step_addr, lock_addr))

        # Setup excitation shutdown handler:
        # Simulation-only policy is strictly restricted to virtual instruments.
        shutdown_handler = self.excitation_shutdown_handler
        if shutdown_handler is None and is_virtual:
            shutdown_handler = self._simulation_excitation_shutdown

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

            amplitude = float(self.dynamic_inputs["amplitude"].get())
            if not math.isfinite(amplitude) or amplitude <= 0:
                raise ValueError(f"amplitude must be positive, got {amplitude}")

            frequency = float(self.dynamic_inputs["frequency"].get())
            if not math.isfinite(frequency) or frequency <= 0:
                raise ValueError(f"frequency must be positive, got {frequency}")

            measure_time = float(self.dynamic_inputs["measure_time"].get())
            if not math.isfinite(measure_time) or measure_time < 0:
                raise ValueError(f"measure_time must be non-negative, got {measure_time}")

            sensitivity = str(self.dynamic_inputs["sensitivity"].get()).strip()
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

        print("Running AMR measurement...")

        # Initialize drivers
        if dmm_addr.upper() == "VIRTUAL":
            dmm = VirtualDMM(dmm_addr)
        else:
            dmm = Keithley193a(dmm_addr)
            
        if cal_addr.upper() == "VIRTUAL":
            calibrator = VirtualCalibrator(cal_addr, voltage_callibration=float(DEFAULTS["voltage_calibration"]))
        else:
            calibrator = EDC522(cal_addr)
            
        if step_addr.upper() == "VIRTUAL":
            stepper = VirtualStepper(step_addr)
        else:
            stepper = Geos_Stepper(step_addr)
            
        if lock_addr.upper() == "VIRTUAL":
            lockin = VirtualLockin(lock_addr)
        else:
            lockin = SRS830(lock_addr)

        self._active_lockin = lockin
        self._instruments = [dmm, calibrator, stepper, lockin]

        # Instantiate experiment
        try:
            self.experiment = AMR(
                dmm=dmm,
                calibrator=calibrator,
                stepper=stepper,
                lockin=lockin,
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
            self.is_measuring = False
            self._awaiting_terminal = False
            self.cleanup_controls()
            if self.runner.can_close():
                self._close_instruments()

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
        print("Measurement paused." if self.paused else "Measurement resumed.")

    def stop_measurement(self):
        if not self.is_measuring or self.runner is None:
            return
            
        print("Stopping measurement...")
        if hasattr(self, 'stop_button') and self.stop_button is not None:
            self.stop_button.config(state='disabled')
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.config(text="Stopping and returning field to zero...")
        self.runner.request_stop()

    def cleanup_controls(self):
        """Removes control buttons and restores the run button."""
        if hasattr(self, 'control_frame') and self.control_frame is not None:
            try:
                self.control_frame.destroy()
            except Exception:
                pass
            self.control_frame = None
        if hasattr(self, 'run_button') and self.run_button is not None:
            self.run_button.grid()
            self.run_button.config(state='normal')

    def plot_data(self, event=None):
        self._plot_data()

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
                    elif isinstance(event, TerminalEvent):
                        terminal_seen = True
                        self._terminal_event = event
                        # Authoritative terminal data view
                        terminal_df = None
                        if event.final_snapshot is not None:
                            terminal_df = event.final_snapshot.get_view("data")
                        if terminal_df is None:
                            terminal_df = event.data
                        if terminal_df is not None and not terminal_df.empty:
                            self._current_plot_data = terminal_df
                            self._plot_data(terminal_df)
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
                    self._plot_data(raw_window)

            # Terminal delivery can precede worker exit. Retain ownership until both finish.
            if self._terminal_event is not None and not self.runner.is_worker_alive:
                event = self._terminal_event
                self._terminal_event = None
                self._awaiting_terminal = False
                self.is_measuring = False
                self.cleanup_controls()
                if event.safety.status == SafetyStatus.SAFE and self.runner.can_close():
                    self._close_instruments()
                else:
                    print("Retaining open connections due to non-safe status or runner close gate.")

            if (self._closing or self._close_when_safe) and self.runner.can_close() and not self._awaiting_terminal:
                if self.runner.safety_status == SafetyStatus.SAFE:
                    self._close_instruments()
                self._finish_close()
                return

        if hasattr(self, "root") and getattr(self.root, "winfo_exists", None) and self.root.winfo_exists():
            self._poll_id = self.root.after(50, self._poll_runner)
        else:
            self._poll_id = None

    def _close_instruments(self):
        """Safely close instrument connections without crashing on errors."""
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
        if self.runner is None or self.runner.safety_status == SafetyStatus.SAFE:
            self._close_instruments()
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
