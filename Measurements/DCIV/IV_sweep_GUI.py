import os
import queue
import tkinter as tk
from tkinter import ttk

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import numpy as np
import pandas as pd

from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement.contracts import TerminalEvent
from piec.measurement.gui_utils import MeasurementApp
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.persistence import read_measurement_csv
from piec.measurement.runner import MeasurementRunner

DEFAULTS = {
    "sm_address": "VIRTUAL",
    "save_dir": r"your\default\save\directory",
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
            values=["voltage", "current"],
            state="readonly",
        )
        self.x_axis.grid(row=0, column=1, padx=5, pady=5)
        self.x_axis.set("voltage")
        self.x_axis.bind("<<ComboboxSelected>>", self.plot_data)

        ttk.Label(self.plot_config_frame, text="Y-axis:").grid(row=1, column=0, sticky="w")
        self.y_axis = ttk.Combobox(
            self.plot_config_frame,
            values=["voltage", "current"],
            state="readonly",
        )
        self.y_axis.grid(row=1, column=1, padx=5, pady=5)
        self.y_axis.set("current")
        self.y_axis.bind("<<ComboboxSelected>>", self.plot_data)

        # Stop button
        self.stop_button = ttk.Button(
            self.right_panel, text="STOP", command=self.stop_measurement, style="TButton"
        )
        self.stop_button.grid(row=1, column=1, pady=10, padx=5)

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

        try:
            v_start = float(self.dynamic_inputs["v_start"].get())
            v_stop = float(self.dynamic_inputs["v_stop"].get())
            num_steps = int(self.dynamic_inputs["num_steps"].get())
            current_compliance = float(self.dynamic_inputs["current_compliance"].get())
            dwell_time = float(self.dynamic_inputs["dwell_time"].get())
        except ValueError as exc:
            print(f"ERROR: Invalid numeric input: {exc}")
            return

        # Update defaults to current values
        DEFAULTS["v_start"] = v_start
        DEFAULTS["v_stop"] = v_stop
        DEFAULTS["num_steps"] = num_steps
        DEFAULTS["current_compliance"] = current_compliance
        DEFAULTS["dwell_time"] = dwell_time
        DEFAULTS["sense_mode"] = sense_mode

        if sm_address == "VIRTUAL":
            sourcemeter = VirtualSourcemeter()
        else:
            sourcemeter = Keithley2400(sm_address)

        effective_output_dir = (
            save_dir if (save_dir and save_dir != r"your\default\save\directory") else None
        )

        self.experiment = IVSweep(
            sourcemeter=sourcemeter,
            v_start=v_start,
            v_stop=v_stop,
            num_steps=num_steps,
            current_compliance=current_compliance,
            dwell_time=dwell_time,
            sense_mode=sense_mode,
            output_dir=effective_output_dir,
        )

        self.runner = MeasurementRunner(self.experiment)
        self.run_button.config(state="disabled")
        try:
            self.runner.start(save=bool(effective_output_dir is not None))
            self.root.after(50, self._poll_runner)
        except Exception as exc:
            print(f"Failed to start measurement: {exc}")
            self.run_button.config(state="normal")

    def stop_measurement(self):
        if hasattr(self, "runner") and self.runner.is_worker_alive:
            print("Requesting measurement stop...")
            self.runner.request_stop()

    def _poll_runner(self):
        if not hasattr(self, "runner"):
            return

        # 1. Drain display queue for live snapshots
        latest_snap = None
        try:
            while True:
                latest_snap = self.runner.display_queue.get_nowait()
        except queue.Empty:
            pass

        if latest_snap is not None:
            raw_view = latest_snap.get_view("raw")
            if raw_view is not None and not raw_view.empty:
                self._plot_dataframe(raw_view)

        # 2. Drain control queue for terminal / lifecycle events
        is_done = False
        try:
            while True:
                event = self.runner.control_queue.get_nowait()
                if isinstance(event, TerminalEvent):
                    is_done = True
                    if event.final_snapshot is not None:
                        final_raw = event.final_snapshot.get_view("raw")
                        if final_raw is not None and not final_raw.empty:
                            self._plot_dataframe(final_raw)
                    elif self.experiment.data is not None and not self.experiment.data.empty:
                        self._plot_dataframe(self.experiment.data)
                    print(
                        f"Measurement finished with state {event.state.value}, "
                        f"safety {event.safety.status.value}"
                    )
                    if event.filename:
                        print(f"Data saved to: {event.filename}")
                    elif event.partial_filename:
                        print(f"Partial data saved to: {event.partial_filename}")
        except queue.Empty:
            pass

        if is_done or not self.runner.is_worker_alive:
            self.run_button.config(state="normal")
        else:
            self.root.after(50, self._poll_runner)

    def _plot_dataframe(self, df: pd.DataFrame):
        x_col = self.x_axis.get()
        y_col = self.y_axis.get()
        if x_col not in df.columns or y_col not in df.columns:
            return

        self.ax.clear()
        units = getattr(self.experiment, "column_units", {})
        x_unit = units.get(x_col, "")
        y_unit = units.get(y_col, "")
        x_label = f"{x_col} ({x_unit})" if x_unit else x_col
        y_label = f"{y_col} ({y_unit})" if y_unit else y_col

        self.ax.plot(df[x_col], df[y_col], marker=".", color="k", label=f"{y_col} vs {x_col}")
        self.ax.set_xlabel(x_label)
        self.ax.set_ylabel(y_label)
        self.canvas.draw()

    def plot_data(self, event=None):
        if hasattr(self, "experiment"):
            if self.experiment.data is not None and not self.experiment.data.empty:
                self._plot_dataframe(self.experiment.data)
            elif self.experiment.filename and os.path.exists(self.experiment.filename):
                _, data, _ = read_measurement_csv(self.experiment.filename)
                self._plot_dataframe(data)


if __name__ == "__main__":
    root = tk.Tk()
    app = IVSweepApp(root)
    root.mainloop()
