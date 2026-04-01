import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import tkinter as tk
from tkinter import ttk
import numpy as np
import pandas as pd
import time
import os
from piec.drivers.dmm.keithley193a import Keithley193a
from piec.drivers.dc_callibrator.edc522 import EDC522
from piec.drivers.stepper_motor.arduino_stepper import Geos_Stepper
from piec.drivers.lockin.srs830 import SRS830
from piec.measurement.magneto_transport import AMR
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.gui_utils import MeasurementApp

import threading

DEFAULTS = {
    "dmm_address": "VIRTUAL",
    "calibrator_address": "VIRTUAL",
    "stepper_address": "VIRTUAL",
    "lockin_address": "VIRTUAL",
    "save_dir": r"\\files22.brown.edu\research\ENG_Caretta_Shared\Group\big_magnet\amr\test",
    "field": 100.0,
    "angle_step": 10.0,
    "total_angle": 360.0,
    "amplitude": 1.0,
    "frequency": 10.0,
    "measure_time": 1.0,
    "sensitivity": "50uv/pa",
    "voltage_calibration": 10000.0,
    "initialize_lockin": True
}

class AMRApp(MeasurementApp):
    def __init__(self, root):
        super().__init__(root, title="AMR Measurement GUI", geometry="1600x900")
        print("Welcome to the AMR Measurement GUI!")
        print("Ctrl+Enter: Run Measurement")
        
        self.measurement_thread = None
        self.is_measuring = False

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

        # Checkbox for optional lock-in initialization
        self.initialize_lockin_var = tk.BooleanVar(value=DEFAULTS["initialize_lockin"])
        self.initialize_lockin_checkbox = ttk.Checkbutton(
            self.dynamic_frame,
            text="Initialize Lock-in?",
            variable=self.initialize_lockin_var
        )
        self.initialize_lockin_checkbox.grid(row=7, column=0, columnspan=2, pady=5, sticky="w")

        # Plot configuration
        ttk.Label(self.plot_config_frame, text="X-axis:").grid(row=0, column=0, sticky="w")
        self.x_axis = ttk.Combobox(self.plot_config_frame, values=["angle", "field", "X", "Y"], state="readonly")
        self.x_axis.grid(row=0, column=1, padx=5, pady=5)
        self.x_axis.set("angle")
        self.x_axis.bind("<<ComboboxSelected>>", self.plot_data)

        ttk.Label(self.plot_config_frame, text="Y-axis:").grid(row=1, column=0, sticky="w")
        self.y_axis = ttk.Combobox(self.plot_config_frame, values=["angle", "field", "X", "Y"], state="readonly")
        self.y_axis.grid(row=1, column=1, padx=5, pady=5)
        self.y_axis.set("X")
        self.y_axis.bind("<<ComboboxSelected>>", self.plot_data)

    def test_stepper(self):
        addr = self.stepper_address_entry.get()
        if not addr:
            print("ERROR: No address selected for Stepper.")
            return

        print(f"Testing Stepper at {addr}...")
        from piec.drivers.autodetect import _safe_close
        
        try:
            # Create the specific Geos_Stepper instance
            # This handles virtual mode automatically if addr is "VIRTUAL"
            inst = Geos_Stepper(address=addr)
            
            # Use the instrument's own idn method which sends '0,0' for Geos hardware
            res = inst.idn()
            
            if "Not connected" not in res:
                print(f"SUCCESS: {res}")
            else:
                print(f"FAILURE: Stepper at {addr} returned '{res}'")
            
            _safe_close(inst)
        except Exception as e:
            print(f"ERROR: Stepper test failed: {e}")


    def refresh_instruments(self):
        print("Refreshing VISA instruments...")
        visa_resources = self.get_visa_resources()
        self.dmm_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.calibrator_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.stepper_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.lockin_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)

    def autodetect_instruments(self):
        print("Autodetecting instruments... this may take a moment.")
        from piec.drivers.autodetect import autodetect, _safe_close
        from piec.drivers.dmm.dmm import DMM
        from piec.drivers.dc_callibrator.dc_callibrator import DCCalibrator
        from piec.drivers.stepper_motor.stepper_motor import Stepper
        from piec.drivers.lockin.lockin import Lockin

        # DMM
        inst = autodetect(address="dmm", verbose=True, required_type=DMM)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.dmm_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected DMM at {addr}")

        # Calibrator
        inst = autodetect(address="dc_callibrator", verbose=True, required_type=DCCalibrator)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.calibrator_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected Calibrator at {addr}")

        # Stepper
        inst = autodetect(address="stepper_motor", verbose=True, required_type=Stepper)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.stepper_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected Stepper at {addr}")

        # Lockin
        inst = autodetect(address="lockin", verbose=True, required_type=Lockin)
        if inst:
            addr = inst.instrument.resource_name if hasattr(inst, 'instrument') else "VIRTUAL"
            self.lockin_address_entry.set(addr)
            _safe_close(inst)
            print(f"Detected Lockin at {addr}")

        print("Autodetect complete.")

    def run_measurement(self):
        if self.is_measuring:
            print("Measurement already in progress...")
            return

        print("Running AMR measurement...")

        # Get addresses
        dmm_addr = self.dmm_address_entry.get()
        cal_addr = self.calibrator_address_entry.get()
        step_addr = self.stepper_address_entry.get()
        lock_addr = self.lockin_address_entry.get()
        save_dir = self.save_dir_entry.get()

        # Get parameters
        field = float(self.dynamic_inputs["field"].get())
        angle_step = float(self.dynamic_inputs["angle_step"].get())
        total_angle = float(self.dynamic_inputs["total_angle"].get())
        amplitude = float(self.dynamic_inputs["amplitude"].get())
        frequency = float(self.dynamic_inputs["frequency"].get())
        measure_time = float(self.dynamic_inputs["measure_time"].get())
        sensitivity = self.dynamic_inputs["sensitivity"].get()
        initialize_lockin = self.initialize_lockin_var.get()

        # Update defaults
        DEFAULTS["field"] = field
        DEFAULTS["angle_step"] = angle_step
        DEFAULTS["total_angle"] = total_angle
        DEFAULTS["amplitude"] = amplitude
        DEFAULTS["frequency"] = frequency
        DEFAULTS["measure_time"] = measure_time
        DEFAULTS["sensitivity"] = sensitivity
        DEFAULTS["initialize_lockin"] = initialize_lockin

        from piec.drivers.dmm.virtual_dmm import VirtualDMM
        from piec.drivers.dc_callibrator.virtual_calibrator import VirtualCalibrator
        from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
        from piec.drivers.lockin.virtual_lockin import VirtualLockin

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

        # Instantiate experiment
        self.experiment = AMR(
            dmm=dmm,
            calibrator=calibrator,
            arduino=stepper,
            lockin=lockin,
            field=field,
            angle_step=angle_step,
            total_angle=int(total_angle),
            amplitude=amplitude,
            frequency=frequency,
            measure_time=measure_time,
            sensitivity=sensitivity,
            save_dir=save_dir
        )

        self.is_measuring = True
        self.paused = False
        if hasattr(self, 'run_button'):
            self.run_button.config(state='disabled')
        
        # Add stop and pause buttons during measurement
        self.add_control_buttons()

        # Run experiment in a background thread
        self.measurement_thread = threading.Thread(
            target=self.experiment.run_experiment,
            kwargs={'configure_lockin': initialize_lockin},
            daemon=True
        )
        self.measurement_thread.start()
        
        # Start the plot auto-update loop
        self.update_plot_loop()

    def add_control_buttons(self):
        """Adds Stop and Pause buttons to the GUI."""
        self.control_frame = ttk.Frame(self.right_panel, style="TFrame")
        self.control_frame.grid(row=1, column=0, pady=10)
        
        self.pause_button = ttk.Button(self.control_frame, text="PAUSE", command=self.toggle_pause, style="TButton")
        self.pause_button.pack(side="left", padx=5)
        
        self.stop_button = ttk.Button(self.control_frame, text="STOP", command=self.stop_measurement, style="TButton")
        self.stop_button.pack(side="left", padx=5)
        
        # Hide the main run button
        self.run_button.grid_remove()

    def toggle_pause(self):
        if not self.is_measuring or not self.experiment:
            return
            
        self.paused = not self.paused
        self.experiment.pause_requested = self.paused
        self.pause_button.config(text="RESUME" if self.paused else "PAUSE")
        print("Measurement paused." if self.paused else "Measurement resumed.")

    def stop_measurement(self):
        if not self.is_measuring or not self.experiment:
            return
            
        print("Stopping measurement...")
        self.experiment.abort_requested = True
        self.stop_button.config(state='disabled')

    def cleanup_controls(self):
        """Removes control buttons and restores the run button."""
        if hasattr(self, 'control_frame'):
            self.control_frame.destroy()
        self.run_button.grid()
        self.run_button.config(state='normal')

    def update_plot_loop(self):
        """Periodically updates the plot from the CSV file."""
        if not self.is_measuring:
            return

        self.plot_data()
        
        if self.measurement_thread and self.measurement_thread.is_alive():
            # Check back in 2 seconds
            self.root.after(2000, self.update_plot_loop)
        else:
            self.is_measuring = False
            self.cleanup_controls()
            print("Measurement complete.")
            self.plot_data() # Final update

    def plot_data(self, event=None):
        if not hasattr(self, 'experiment') or self.experiment.filename is None:
            return
            
        if not os.path.exists(self.experiment.filename):
            return

        try:
            metadata, data = standard_csv_to_metadata_and_data(self.experiment.filename)
            if data is None or data.empty:
                return

            self.ax.clear()
            x_col = self.x_axis.get()
            y_col = self.y_axis.get()
            
            if x_col in data.columns and y_col in data.columns:
                self.ax.plot(data[x_col], data[y_col], marker="o", color="blue", label=f"{y_col} vs {x_col}")
                self.ax.set_xlabel(x_col)
                self.ax.set_ylabel(y_col)
                self.ax.set_title("AMR Measurement Data")
                self.canvas.draw()
        except Exception:
            # File might be busy, just skip this update
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = AMRApp(root)
    root.mainloop()
