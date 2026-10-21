import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import tkinter as tk
from tkinter import ttk
import numpy as np
import pandas as pd
import time
import os
from piec.measurement.amr import AMR
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.gui_utils import MeasurementApp

import threading

DEFAULTS = {
    "save_dir": r"scratch",
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
    _instruments = ('dmm', 'dc_calibrator', 'stepper_motor', 'lockin')

    def __init__(self, root):
        super().__init__(root, title="AMR Measurement GUI", geometry="1600x900")
        print("Welcome to the AMR Measurement GUI!")
        print("Ctrl+Enter: Run Measurement")
        
        self.measurement_thread = None
        self.is_measuring = False

        # Static Inputs
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])

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

    def run_measurement(self):
        if self.is_measuring:
            print("Measurement already in progress...")
            return

        print("Running AMR measurement...")

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

        try:
            instruments = self.connect_instruments(
                virtual_options={'dc_calibrator': {'voltage_callibration': float(DEFAULTS['voltage_calibration'])}},
            )
        except Exception as error:
            print(f"Could not connect instruments: {error}")
            return

        # Instantiate experiment
        self.experiment = AMR(
            dmm=instruments['dmm'],
            calibrator=instruments['dc_calibrator'],
            arduino=instruments['stepper_motor'],
            lockin=instruments['lockin'],
            field=field,
            angle_step=angle_step,
            total_angle=int(total_angle),
            amplitude=amplitude,
            frequency=frequency,
            measure_time=measure_time,
            sensitivity=sensitivity,
            save_dir=save_dir,
            live_plot=False,
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
        if self.experiment is None or self.experiment.filename is None:
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
