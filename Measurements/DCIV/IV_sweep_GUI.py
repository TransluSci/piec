import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import numpy as np
import pandas as pd

from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement.contracts import SafetyAlertEvent, TerminalEvent
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

        self.experiment = None
        self.runner = None
        self._terminal_event = None
        self.is_measuring = False
        self._close_when_safe = False
        self._instruments = []

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

        # Status label
        self.status_label = ttk.Label(self.plot_config_frame, text="Idle")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        # Stop button
        self.stop_button = ttk.Button(
            self.right_panel, text="STOP", command=self.stop_measurement, state="disabled", style="TButton"
        )
        self.stop_button.grid(row=1, column=1, pady=10, padx=5)

        self._poll_runner_id = self.root.after(50, self._poll_runner)

    def _close_instruments(self):
        instruments = getattr(self, "_instruments", [])
        seen = set()
        for instrument in instruments:
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

    def refresh_instruments(self):
        if getattr(self, "is_measuring", False):
            print("Cannot refresh instruments while a measurement is active.")
            return
        print("Refreshing VISA instruments...")
        visa_resources = self.get_visa_resources()
        self.sm_address_entry["values"] = ["VIRTUAL"] + list(visa_resources)
        self.sm_address_entry.set("VIRTUAL")

    def run_measurement(self):
        if getattr(self, "is_measuring", False) or (
            getattr(self, "runner", None) is not None and not self.runner.can_close()
        ):
            return

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
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Invalid Input", f"Invalid numeric input: {exc}")
            print(f"ERROR: Invalid numeric input: {exc}")
            return

        # Update defaults to current values
        DEFAULTS["v_start"] = v_start
        DEFAULTS["v_stop"] = v_stop
        DEFAULTS["num_steps"] = num_steps
        DEFAULTS["current_compliance"] = current_compliance
        DEFAULTS["dwell_time"] = dwell_time
        DEFAULTS["sense_mode"] = sense_mode

        try:
            if sm_address == "VIRTUAL":
                sourcemeter = VirtualSourcemeter()
            else:
                sourcemeter = Keithley2400(sm_address)
            self._instruments = [sourcemeter]
        except Exception as error:
            messagebox.showerror("Sourcemeter connection error", str(error))
            print(f"Sourcemeter connection error: {error}")
            self._close_instruments()
            return

        effective_output_dir = (
            save_dir if (save_dir and save_dir != r"your\default\save\directory") else None
        )

        try:
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
        except Exception as error:
            messagebox.showerror("IV Sweep setup error", str(error))
            print(f"IV Sweep setup error: {error}")
            self._close_instruments()
            return

        self.runner = MeasurementRunner(self.experiment)
        self.is_measuring = True
        self._terminal_event = None

        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.config(text="Running...")
        if hasattr(self, "run_button") and self.run_button is not None:
            self.run_button.config(state="disabled")
        if hasattr(self, "stop_button") and self.stop_button is not None:
            self.stop_button.config(state="normal")

        try:
            self.runner.start(save=bool(effective_output_dir is not None))
        except BaseException as error:
            messagebox.showerror("IV Sweep start error", str(error))
            print(f"Failed to start measurement: {error}")
            self.is_measuring = False
            if self.runner.can_close():
                self._close_instruments()
                if hasattr(self, "run_button") and self.run_button is not None:
                    self.run_button.config(state="normal")
            if hasattr(self, "stop_button") and self.stop_button is not None:
                self.stop_button.config(state="disabled")

        if getattr(self, "_poll_runner_id", None) is None:
            if hasattr(self, "root") and getattr(self.root, "winfo_exists", None) and self.root.winfo_exists():
                self._poll_runner_id = self.root.after(50, self._poll_runner)

    def stop_measurement(self):
        if getattr(self, "is_measuring", False) and getattr(self, "runner", None) is not None:
            print("Requesting measurement stop...")
            if hasattr(self, "status_label") and self.status_label is not None:
                self.status_label.config(text="Stopping and returning output to zero...")
            if hasattr(self, "stop_button") and self.stop_button is not None:
                self.stop_button.config(state="disabled")
            self.runner.request_stop()

    def _poll_runner(self):
        if getattr(self, "runner", None) is not None:
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

            # 2. Drain control queue for terminal / lifecycle / safety events
            try:
                while True:
                    event = self.runner.control_queue.get_nowait()
                    if isinstance(event, SafetyAlertEvent):
                        if hasattr(self, "status_label") and self.status_label is not None:
                            self.status_label.config(
                                text="Hardware unsafe: retain connections for recovery"
                            )
                    elif isinstance(event, TerminalEvent):
                        self._terminal_event = event
                        if event.data is not None and not event.data.empty:
                            self._plot_dataframe(event.data)
                        elif event.final_snapshot is not None:
                            final_raw = event.final_snapshot.get_view("raw")
                            if final_raw is not None and not final_raw.empty:
                                self._plot_dataframe(final_raw)
                        elif (
                            getattr(self, "experiment", None) is not None
                            and self.experiment.data is not None
                            and not self.experiment.data.empty
                        ):
                            self._plot_dataframe(self.experiment.data)

                        print(
                            f"Measurement finished with state {event.state.value}, "
                            f"safety {event.safety.status.value}"
                        )
                        if event.filename:
                            print(f"Data saved to: {event.filename}")
                        elif event.partial_filename:
                            print(f"Partial data saved to: {event.partial_filename}")

                        if getattr(event, "recoverable_staging_paths", None):
                            print(f"Recoverable data staging paths: {event.recoverable_staging_paths}")

                        if event.primary_error_message:
                            messagebox.showerror("IV Sweep measurement failed", event.primary_error_message)
            except queue.Empty:
                pass

            # Terminal delivery can precede worker exit. Retain ownership until both finish.
            if getattr(self, "_terminal_event", None) is not None and not self.runner.is_worker_alive:
                event = self._terminal_event
                self._terminal_event = None
                self.is_measuring = False
                if hasattr(self, "stop_button") and self.stop_button is not None:
                    self.stop_button.config(state="disabled")
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(
                        text=f"{event.state.value}: safety {event.safety.status.value}"
                    )
                if self.runner.can_close():
                    self._close_instruments()
                    if hasattr(self, "run_button") and self.run_button is not None:
                        self.run_button.config(state="normal")

            if getattr(self, "_close_when_safe", False) and self.runner.can_close():
                self._finish_close()
                return

        if hasattr(self, "root") and getattr(self.root, "winfo_exists", None) and self.root.winfo_exists():
            self._poll_runner_id = self.root.after(50, self._poll_runner)
        else:
            self._poll_runner_id = None

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

    def on_closing(self):
        if getattr(self, "runner", None) is not None:
            self._close_when_safe = True
            self.runner.request_close()
            if not self.runner.can_close():
                if hasattr(self, "status_label") and self.status_label is not None:
                    self.status_label.config(
                        text="Waiting for worker exit and confirmed hardware safety..."
                    )
                return
        self._close_instruments()
        self._finish_close()

    def _finish_close(self):
        self._close_when_safe = False
        if getattr(self, "_poll_runner_id", None) is not None:
            try:
                self.root.after_cancel(self._poll_runner_id)
            except Exception:
                pass
            self._poll_runner_id = None
        super().on_closing()


if __name__ == "__main__":
    root = tk.Tk()
    app = IVSweepApp(root)
    root.mainloop()
