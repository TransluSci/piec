import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import tkinter as tk
from tkinter import ttk
import numpy as np
from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.sourcemeter.virtual_keithley2400 import VirtualKeithley2400
from piec.measurement.iv_sweep import IVSweep
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.gui_utils import MeasurementApp

DEFAULTS = {
    "sm_address": "VIRTUAL",
    "save_dir": r"C:\Users\Jesalina Phan\OneDrive - Brown University\Desktop\piec\data",
    "v_start": 0.0,
    "v_stop": 1.0,
    "num_steps": 50,
    "current_compliance": 0.1,
    "dwell_time": 0.1,
    "sense_mode": "2W",
}


class IVSweepApp(MeasurementApp):
    def __init__(self, root):
        super().__init__(root, title="IV Sweep Measurement GUI", geometry="1600x900")
        print("Welcome to the IV Sweep GUI!")
        print("Ctrl+Enter: Run Measurement")

        visa_resources = self.get_visa_resources()

        # Static Inputs (Save Dir is at row 0 in base)
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])

        ttk.Label(self.static_frame, text="Sourcemeter Address:").grid(row=1, column=0, sticky="w")
        self.sm_address_entry = ttk.Combobox(
            self.static_frame,
            values=["VIRTUAL"] + list(visa_resources),
            state="readonly",
        )
        self.sm_address_entry.grid(row=1, column=1, padx=5, pady=5)
        self.sm_address_entry.set(DEFAULTS["sm_address"])
        ttk.Button(
            self.static_frame, text="Refresh", command=self.refresh_instruments, style="TButton"
        ).grid(row=1, column=2, padx=5)

        ttk.Label(self.static_frame, text="Sense Mode:").grid(row=2, column=0, sticky="w")
        self.sense_mode_entry = ttk.Combobox(
            self.static_frame, values=["2W", "4W"], state="readonly"
        )
        self.sense_mode_entry.grid(row=2, column=1, padx=5, pady=5)
        self.sense_mode_entry.set(DEFAULTS["sense_mode"])

        # Dynamic Inputs — IV sweep parameters
        self.dynamic_frame.config(text="IV SWEEP INPUTS")
        self.dynamic_inputs = {}

        ttk.Label(self.dynamic_frame, text="V Start (V):").grid(row=0, column=0, sticky="w")
        self.dynamic_inputs["v_start"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["v_start"].grid(row=0, column=1, padx=5, pady=5)
        self.dynamic_inputs["v_start"].insert(0, DEFAULTS["v_start"])

        ttk.Label(self.dynamic_frame, text="V Stop (V):").grid(row=1, column=0, sticky="w")
        self.dynamic_inputs["v_stop"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["v_stop"].grid(row=1, column=1, padx=5, pady=5)
        self.dynamic_inputs["v_stop"].insert(0, DEFAULTS["v_stop"])

        ttk.Label(self.dynamic_frame, text="Number of Steps:").grid(row=2, column=0, sticky="w")
        self.dynamic_inputs["num_steps"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["num_steps"].grid(row=2, column=1, padx=5, pady=5)
        self.dynamic_inputs["num_steps"].insert(0, DEFAULTS["num_steps"])

        ttk.Label(self.dynamic_frame, text="Current Compliance (A):").grid(row=3, column=0, sticky="w")
        self.dynamic_inputs["current_compliance"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["current_compliance"].grid(row=3, column=1, padx=5, pady=5)
        self.dynamic_inputs["current_compliance"].insert(0, DEFAULTS["current_compliance"])

        ttk.Label(self.dynamic_frame, text="Dwell Time (s):").grid(row=4, column=0, sticky="w")
        self.dynamic_inputs["dwell_time"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["dwell_time"].grid(row=4, column=1, padx=5, pady=5)
        self.dynamic_inputs["dwell_time"].insert(0, DEFAULTS["dwell_time"])

        # Plot configuration
        ttk.Label(self.plot_config_frame, text="X-axis:").grid(row=0, column=0, sticky="w")
        self.x_axis = ttk.Combobox(
            self.plot_config_frame,
            values=["voltage (V)", "current (A)"],
            state="readonly",
        )
        self.x_axis.grid(row=0, column=1, padx=5, pady=5)
        self.x_axis.set("voltage (V)")
        self.x_axis.bind("<<ComboboxSelected>>", self.plot_data)

        ttk.Label(self.plot_config_frame, text="Y-axis:").grid(row=1, column=0, sticky="w")
        self.y_axis = ttk.Combobox(
            self.plot_config_frame,
            values=["voltage (V)", "current (A)"],
            state="readonly",
        )
        self.y_axis.grid(row=1, column=1, padx=5, pady=5)
        self.y_axis.set("current (A)")
        self.y_axis.bind("<<ComboboxSelected>>", self.plot_data)

    def refresh_instruments(self):
        print("Refreshing VISA instruments...")
        visa_resources = self.get_visa_resources()
        self.sm_address_entry["values"] = ["VIRTUAL"] + visa_resources
        self.sm_address_entry.set("VIRTUAL")

    def run_measurement(self):
        print("Running IV Sweep measurement...")

        sm_address = self.sm_address_entry.get()
        save_dir = self.save_dir_entry.get()
        sense_mode = self.sense_mode_entry.get()

        v_start = float(self.dynamic_inputs["v_start"].get())
        v_stop = float(self.dynamic_inputs["v_stop"].get())
        num_steps = int(self.dynamic_inputs["num_steps"].get())
        current_compliance = float(self.dynamic_inputs["current_compliance"].get())
        dwell_time = float(self.dynamic_inputs["dwell_time"].get())

        # Update defaults to current values
        DEFAULTS["v_start"] = v_start
        DEFAULTS["v_stop"] = v_stop
        DEFAULTS["num_steps"] = num_steps
        DEFAULTS["current_compliance"] = current_compliance
        DEFAULTS["dwell_time"] = dwell_time
        DEFAULTS["sense_mode"] = sense_mode

        if sm_address == "VIRTUAL":
            sourcemeter = VirtualKeithley2400()
        else:
            sourcemeter = Keithley2400(sm_address)

        self.experiment = IVSweep(
            sourcemeter=sourcemeter,
            v_start=v_start,
            v_stop=v_stop,
            num_steps=num_steps,
            current_compliance=current_compliance,
            dwell_time=dwell_time,
            sense_mode=sense_mode,
            save_dir=save_dir,
        )
        self.experiment.run_experiment()
        self.plot_data()

    def plot_data(self, event=None):
        self.ax.clear()
        metadata, data = standard_csv_to_metadata_and_data(self.experiment.filename)
        x_data = data[self.x_axis.get()]
        y_data = data[self.y_axis.get()]

        self.ax.plot(x_data, y_data, marker=".", color="k", label=f"{self.y_axis.get()} vs {self.x_axis.get()}")
        self.ax.set_xlabel(self.x_axis.get())
        self.ax.set_ylabel(self.y_axis.get())
        self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = IVSweepApp(root)
    root.mainloop()
