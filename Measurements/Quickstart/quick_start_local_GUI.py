"""Quickstart GUI for PIEC: Test virtual or physical AWG and Oscilloscope measurements.

Launch locally from repository root:
    python Measurements/Quickstart/quick_start_local_GUI.py
"""
import os
import sys
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# DPI awareness on Windows if available
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import time
from piec.measurement.gui_utils import MeasurementApp
from piec.simulation.fe_material import Resistor

DEFAULTS = {
    "save_dir": r"scratch",
    "waveform": "SIN",
    "frequency": 1000.0,
    "amplitude": 1.0,
    "offset": 0.0,
}


class QuickstartApp(MeasurementApp):
    """Quickstart GUI application inheriting from PIEC's standard MeasurementApp."""

    _instruments = ('awg', 'oscilloscope')

    def __init__(self, root):
        super().__init__(root, title="PIEC — Quickstart Measurement GUI", geometry="1300x750")

        print("Welcome to the PIEC Quickstart GUI!")
        print("Ctrl+Enter: Capture Waveform")
        print("Select 'VIRTUAL' or choose a connected instrument from the dropdowns.")

        # 1. Static Inputs (Save Directory is row 0 in base MeasurementApp)
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])

        # 2. Dynamic Inputs — Signal configuration
        self.dynamic_frame.config(text="SIGNAL CONFIGURATION")
        self.dynamic_inputs = {}

        ttk.Label(self.dynamic_frame, text="Waveform:").grid(row=0, column=0, sticky="w")
        self.waveform_entry = ttk.Combobox(
            self.dynamic_frame,
            values=["SIN", "SQU", "RAMP"],
            state="readonly",
            width=20,
        )
        self.waveform_entry.grid(row=0, column=1, padx=5, pady=5)
        self.waveform_entry.set(DEFAULTS["waveform"])
        self.dynamic_inputs["waveform"] = self.waveform_entry

        ttk.Label(self.dynamic_frame, text="Frequency (Hz):").grid(row=1, column=0, sticky="w")
        self.frequency_entry = ttk.Entry(self.dynamic_frame, width=20)
        self.frequency_entry.grid(row=1, column=1, padx=5, pady=5)
        self.frequency_entry.insert(0, str(DEFAULTS["frequency"]))
        self.dynamic_inputs["frequency"] = self.frequency_entry

        ttk.Label(self.dynamic_frame, text="Amplitude (V):").grid(row=2, column=0, sticky="w")
        self.amplitude_entry = ttk.Entry(self.dynamic_frame, width=20)
        self.amplitude_entry.grid(row=2, column=1, padx=5, pady=5)
        self.amplitude_entry.insert(0, str(DEFAULTS["amplitude"]))
        self.dynamic_inputs["amplitude"] = self.amplitude_entry

        ttk.Label(self.dynamic_frame, text="Offset (V):").grid(row=3, column=0, sticky="w")
        self.offset_entry = ttk.Entry(self.dynamic_frame, width=20)
        self.offset_entry.grid(row=3, column=1, padx=5, pady=5)
        self.offset_entry.insert(0, str(DEFAULTS["offset"]))
        self.dynamic_inputs["offset"] = self.offset_entry

        # 3. Plot & Export Configuration
        self.plot_config_frame.config(text="PLOT & EXPORT")
        self.auto_save_entry = tk.BooleanVar(value=True)
        self.save_csv_checkbox = ttk.Checkbutton(
            self.plot_config_frame,
            text="Save CSV on capture?",
            variable=self.auto_save_entry,
            onvalue=True,
            offvalue=False,
        )
        self.save_csv_checkbox.grid(row=0, column=0, columnspan=2, pady=5, sticky="w")

        ttk.Label(
            self.plot_config_frame,
            text=(
                "• VIRTUAL mode simulates AWG output & ferroelectric sample response.\n"
                "• Physical mode captures oscilloscope CH1 (AWG CH1 → Scope CH1).\n"
                "• Click 'Autodetect' to automatically identify connected instruments."
            ),
            wraplength=350,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, pady=5, sticky="w")

        # Configure action button text
        self.run_button.configure(text="CAPTURE WAVEFORM")

        # Initial plot styling
        self.ax.set_title("Choose signal parameters and click Capture")
        self.ax.set_xlabel("Time (ms)")
        self.ax.set_ylabel("Voltage (V)")
        self.canvas.draw()

    def run_measurement(self):
        """Executes waveform generation and capture."""
        awg_address = self.instrument_address_entries['awg'].get().strip()
        osc_address = self.instrument_address_entries['oscilloscope'].get().strip()
        save_dir = self.save_dir_entry.get().strip()
        waveform = self.waveform_entry.get().strip().upper()

        try:
            frequency = float(self.frequency_entry.get())
            amplitude = float(self.amplitude_entry.get())
            offset = float(self.offset_entry.get())
        except ValueError:
            print("ERROR: Frequency, Amplitude, and Offset must be valid numbers.")
            return

        print(f"Capturing {waveform} waveform ({frequency:g} Hz, {amplitude:g} V)...")

        try:
            instruments = self.connect_instruments(virtual_options={'awg': {'simulation_points': 1000}})
        except Exception as error:
            print(f"Could not connect instruments: {error}")
            return
        awg = instruments['awg']
        scope = instruments['oscilloscope']
        if osc_address == 'VIRTUAL':
            scope.sample = Resistor(50.0)

        # Execute measurement
        try:
            if awg_address == "VIRTUAL" and osc_address == "VIRTUAL":
                # Keep existing virtual behavior unchanged
                awg.configure_waveform(
                    1, waveform,
                    frequency=frequency,
                    amplitude=amplitude,
                    offset=offset,
                )
                awg.output(1, on=True)

                scope.arm()
                awg.send_software_trigger()
                data = scope.get_data()

            else:
                # Physical instruments — use known-working driver commands
                awg.initialize()
                awg.configure_waveform(
                    1, waveform,
                    frequency=frequency,
                    amplitude=amplitude,
                    offset=offset,
                )
                awg.output(1, on=True)

                scope.initialize()
                scope.autoscale()
                scope.operation_complete()
                scope.set_acquisition_channel(1)
                data = scope.get_data()

        except Exception as e:
            print(f"ERROR during capture: {e}")
            return

        finally:
            self.close_instruments()
        # Plot result
        self.ax.clear()
        time_ms = data["Time"] * 1000.0
        voltage_v = data["Voltage"]

        self.ax.plot(time_ms, voltage_v, color="C0", linewidth=1.8, label=f"{waveform} ({frequency:g} Hz)")
        self.ax.set_xlabel("Time (ms)")
        self.ax.set_ylabel("Voltage (V)")
        mode_label = "Virtual Response" if (awg_address == "VIRTUAL") else "Physical Scope Capture"
        self.ax.set_title(f"{waveform} Waveform — {mode_label}")
        self.ax.grid(True, alpha=0.3)
        self.canvas.draw()

        # Save to CSV if enabled
        if self.auto_save_entry.get() and save_dir:
            try:
                os.makedirs(save_dir, exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"quickstart_{waveform.lower()}_{timestamp}.csv"
                filepath = os.path.join(save_dir, filename)
                data.to_csv(filepath, index=False)
                print(f"Saved data to {filepath}")
            except Exception as e:
                print(f"WARNING: Could not save CSV: {e}")

        print("Capture complete.")


if __name__ == "__main__":
    root = tk.Tk()
    app = QuickstartApp(root)
    root.mainloop()
