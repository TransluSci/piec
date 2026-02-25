import os
import tkinter as tk
from tkinter import ttk
import numpy as np
import pandas as pd
from piec.measurement.discrete_waveform import HysteresisLoop, ThreePulsePund
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.measurement.gui_utils import MeasurementApp

DEFAULTS = {"awg_address":"VIRTUAL",
            "osc_address":"VIRTUAL",
            "save_dir":r"\\files22.brown.edu\Research\ENG_Caretta_Shared\Group\probe_station\test",
            "vdiv":0.01,
            "area":'1.0e-5**2',
            "time_offset":140,
            "frequency": 1.0e6,
            "amplitude": 1.0,
            "offset": 0.0,
            "n_cycles": 2,
            "reset_amp": 1.0,
            "reset_width": 1.0e-7,
            "reset_delay": 1.0e-7,
            "p_u_amp": 1.0,
            "p_u_width": 1.0e-7,
            "p_u_delay": 1.0e-7,
            }



class FEMeasurementApp(MeasurementApp):
    def __init__(self, root):
        super().__init__(root, title="Ferroelectric Measurement GUI", geometry="1200x700")
        print("Welcome to the FE testing GUI! Please select a measurement type and choose your awg and osc addresses.")
        print("Ctrl+Enter: Run Measurement")
        print("Ctrl+1: Hysteresis Loop")
        print("Ctrl+2: Three Pulse Pund")
        print("Ctrl+r: Change V/div")
        print("Ctrl+t: Change Time Offset")

        visa_resources = self.get_visa_resources()

        # Static Inputs (Save Dir is at row 0 in base)
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])
        ttk.Label(self.static_frame, text="AWG Address:").grid(row=1, column=0, sticky="w")
        self.awg_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"]+list(visa_resources), state="readonly")
        self.awg_address_entry.grid(row=1, column=1, padx=5, pady=5)
        self.awg_address_entry.set(DEFAULTS["awg_address"])
        ttk.Button(self.static_frame, text="Refresh", command=self.refresh_instruments, style="TButton").grid(row=1, column=2, rowspan=2, padx=5)

        ttk.Label(self.static_frame, text="Oscilloscope Address:").grid(row=2, column=0, sticky="w")
        self.osc_address_entry = ttk.Combobox(self.static_frame, values=["VIRTUAL"]+list(visa_resources), state="readonly")
        self.osc_address_entry.grid(row=2, column=1, padx=5, pady=5)
        self.osc_address_entry.set(DEFAULTS["osc_address"])

        ttk.Label(self.static_frame, text="Oscilloscope V/div:").grid(row=3, column=0, sticky="w")
        self.vdiv_entry = ttk.Entry(self.static_frame, width=24)
        self.vdiv_entry.grid(row=3, column=1, padx=5, pady=5)
        self.vdiv_entry.insert(0, DEFAULTS["vdiv"])

        ttk.Label(self.static_frame, text="Sample Area (m^2):").grid(row=4, column=0, sticky="w")
        self.area_entry = ttk.Entry(self.static_frame, width=24)
        self.area_entry.grid(row=4, column=1, padx=5, pady=5)
        self.area_entry.insert(0, DEFAULTS["area"])

        ttk.Label(self.static_frame, text="Time Offset (ns):").grid(row=5, column=0, sticky="w")
        self.timeshift_entry = ttk.Entry(self.static_frame, width=24)
        self.timeshift_entry.grid(row=5, column=1, padx=5, pady=5)
        self.timeshift_entry.insert(0, DEFAULTS["time_offset"])

        # Add a checkbox for auto_timeshift
        self.auto_timeshift_entry = tk.BooleanVar(value=False)  # Default state is checked
        self.auto_timeshift_checkbox = ttk.Checkbutton(
            self.static_frame,
            text="Automatic?",
            variable=self.auto_timeshift_entry,
            onvalue=True,
            offvalue=False
        )
        self.auto_timeshift_checkbox.grid(row=5, column=2, columnspan=1, pady=5, sticky="w")

        # Measurement type selection
        ttk.Label(self.static_frame, text="Measurement Type:").grid(row=6, column=0, sticky="w")
        self.measurement_type = ttk.Combobox(self.static_frame, values=["HysteresisLoop", "ThreePulsePund"], state="readonly")
        self.measurement_type.grid(row=6, column=1, padx=5, pady=5)
        self.measurement_type.bind("<<ComboboxSelected>>", self.update_dynamic_inputs)

        # Dynamic inputs section (Uses inherited self.dynamic_frame)
        
        # Placeholder for dynamic inputs
        self.dynamic_inputs = {}
        self._saved_dynamic = {}  # Cache for saved dynamic values per measurement type

        # Plot configuration section (Uses inherited self.plot_config_frame)
        ttk.Label(self.plot_config_frame, text="X-axis:").grid(row=0, column=0, sticky="w")
        self.x_axis = ttk.Combobox(self.plot_config_frame, values=["time (s)", "applied voltage (V)", "current (A)", "polarization (uC/cm^2)"], state="readonly")
        self.x_axis.grid(row=0, column=1, padx=5, pady=5)
        self.x_axis.set("applied voltage (V)")
        self.x_axis.bind("<<ComboboxSelected>>", self.plot_data)

        ttk.Label(self.plot_config_frame, text="Y-axis:").grid(row=1, column=0, sticky="w")
        self.y_axis = ttk.Combobox(self.plot_config_frame, values=["time (s)", "applied voltage (V)", "current (A)", "polarization (uC/cm^2)"], state="readonly")
        self.y_axis.grid(row=1, column=1, padx=5, pady=5)
        self.y_axis.set("current (A)")
        self.y_axis.bind("<<ComboboxSelected>>", self.plot_data)

        # Add a checkbox for plot saving
        self.saveplots_entry = tk.BooleanVar(value=False)  # Default state is unchecked
        self.enable_feature_checkbox = ttk.Checkbutton(
            self.plot_config_frame,
            text="Save Plots?",
            variable=self.saveplots_entry,
            onvalue=True,
            offvalue=False
        )
        self.enable_feature_checkbox.grid(row=2, column=0, columnspan=2, pady=5, sticky="w")

        # Update shortcuts
        self.keyboard_shortcuts.update({
            "<Control-Key-1>": lambda event: self.select_measurement("HysteresisLoop", event),
            "<Control-Key-2>": lambda event: self.select_measurement("ThreePulsePund", event),
            "<Control-r>": lambda event: self.vdiv_entry.focus_set(),
            "<Control-t>": lambda event: self.timeshift_entry.focus_set()
        })
        self.setup_shortcuts()

    def save_settings(self):
        """Override to save all cached dynamic input sets, not just the currently visible one."""
        import json
        
        # Snapshot current dynamic values into cache before saving
        dynamic_title = self.dynamic_frame.cget("text").strip()
        if dynamic_title and self.dynamic_inputs:
            current_vals = {}
            children = self.dynamic_frame.winfo_children()
            for i, widget in enumerate(children):
                if isinstance(widget, ttk.Label) and i + 1 < len(children):
                    next_widget = children[i + 1]
                    if isinstance(next_widget, ttk.Entry):
                        current_vals[widget.cget("text").rstrip(":")] = next_widget.get()
            if current_vals:
                self._saved_dynamic[dynamic_title] = current_vals

        # Now call the parent save, which will write the current dynamic frame
        # But we need to override the dynamic section with our full cache
        super().save_settings()

        # Re-read the file and replace the dynamic section with our full cache
        filepath = self.get_settings_file_path()
        if filepath and os.path.exists(filepath) and self._saved_dynamic:
            try:
                with open(filepath, 'r') as f:
                    settings = json.load(f)
                settings["dynamic"] = self._saved_dynamic
                with open(filepath, 'w') as f:
                    json.dump(settings, f, indent=4)
            except Exception:
                pass

    def load_settings(self):
        """Override to explicitly trigger measurement type selection before restoring dynamic values."""
        import json, os
        filepath = self.get_settings_file_path()
        if not filepath or not os.path.exists(filepath):
            return
        try:
            with open(filepath, 'r') as f:
                settings = json.load(f)
        except Exception as e:
            print(f"Failed to load settings: {e}")
            return

        # Apply static settings manually (skip the Measurement Type combobox event)
        if "static" in settings:
            static_data = settings["static"]
            for widget_pair in [(self.save_dir_entry, "Save Directory"),
                                (self.awg_address_entry, "AWG Address"),
                                (self.osc_address_entry, "Oscilloscope Address"),
                                (self.vdiv_entry, "Oscilloscope V/div"),
                                (self.area_entry, "Sample Area (m^2)"),
                                (self.timeshift_entry, "Time Offset (ns)")]:
                widget, key = widget_pair
                if key in static_data:
                    if isinstance(widget, ttk.Combobox):
                        widget.set(static_data[key])
                    else:
                        widget.delete(0, tk.END)
                        widget.insert(0, static_data[key])

            # Now explicitly trigger measurement type selection so dynamic inputs are created
            meas_type = static_data.get("Measurement Type", "")
            if meas_type:
                self.select_measurement(meas_type)

        # Cache all saved dynamic settings for use when switching measurement types
        if "dynamic" in settings:
            saved_dynamic = settings["dynamic"]
            # Store in new format (keyed by title)
            if saved_dynamic and isinstance(next(iter(saved_dynamic.values()), None), dict):
                self._saved_dynamic = saved_dynamic
            else:
                # Old flat format - no title key available
                self._saved_dynamic = saved_dynamic

        # Apply dynamic settings to the now-created fields
        self._apply_saved_dynamic()

        # Apply plot settings
        if "plot" in settings:
            plot_data = settings["plot"]
            if "X-axis" in plot_data:
                self.x_axis.set(plot_data["X-axis"])
            if "Y-axis" in plot_data:
                self.y_axis.set(plot_data["Y-axis"])

        print(f"Settings loaded from {filepath}")

    def _apply_saved_dynamic(self):
        """Apply saved dynamic values to the current dynamic frame, if available."""
        if not self._saved_dynamic:
            return
        dynamic_title = self.dynamic_frame.cget("text").strip()
        
        dynamic_data = None
        if dynamic_title and dynamic_title in self._saved_dynamic:
            dynamic_data = self._saved_dynamic[dynamic_title]
        elif not isinstance(next(iter(self._saved_dynamic.values()), None), dict):
            dynamic_data = self._saved_dynamic  # backward compat

        if dynamic_data:
            children = self.dynamic_frame.winfo_children()
            for key, val in dynamic_data.items():
                key_clean = key.rstrip(":")
                for i, widget in enumerate(children):
                    if isinstance(widget, ttk.Label):
                        label_text = widget.cget("text").rstrip(":")
                        if label_text == key_clean and i + 1 < len(children):
                            next_widget = children[i + 1]
                            if isinstance(next_widget, ttk.Entry):
                                next_widget.delete(0, tk.END)
                                next_widget.insert(0, val)

    def select_measurement(self, meas_type, event=None):
        print(f"Selected measurement type: {meas_type}")

        self.measurement_type.set(meas_type)
        self.update_dynamic_inputs(None)

    def update_dynamic_inputs(self, event):
        # Save current dynamic values before clearing (so switching back preserves edits)
        dynamic_title = self.dynamic_frame.cget("text").strip()
        if dynamic_title and self.dynamic_inputs:
            current_vals = {}
            children = self.dynamic_frame.winfo_children()
            for i, widget in enumerate(children):
                if isinstance(widget, ttk.Label) and i + 1 < len(children):
                    next_widget = children[i + 1]
                    if isinstance(next_widget, ttk.Entry):
                        current_vals[widget.cget("text").rstrip(":")] = next_widget.get()
            if current_vals:
                self._saved_dynamic[dynamic_title] = current_vals

        # Clear previous dynamic inputs
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()
        self.dynamic_inputs = {}
        self.dynamic_frame.config(text=f"{str(self.measurement_type.get())} INPUTS")
        measurement_type = self.measurement_type.get()
        if measurement_type == "HysteresisLoop":
            self.setup_hysteresis_inputs()
        elif measurement_type == "ThreePulsePund":
            self.setup_pund_inputs()
        
        # Apply any saved values over the defaults
        self._apply_saved_dynamic()

    def update_dynamic_defaults(self):
        # Update defaults to currently selected values
        for key in self.dynamic_inputs:
            DEFAULTS[key] = self.dynamic_inputs[key].get()

    def refresh_instruments(self):
        print('Refreshing VISA instruments...')
        visa_resources = self.get_visa_resources()
        
        self.awg_address_entry["values"] = ["VIRTUAL"] + visa_resources
        self.osc_address_entry["values"] = ["VIRTUAL"] + visa_resources
        
        self.awg_address_entry.set("VIRTUAL")
        self.osc_address_entry.set("VIRTUAL")

    def setup_hysteresis_inputs(self):
        ttk.Label(self.dynamic_frame, text="Frequency (Hz):").grid(row=0, column=0, sticky="w")
        self.dynamic_inputs["frequency"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["frequency"].grid(row=0, column=1, padx=5, pady=5)
        self.dynamic_inputs["frequency"].insert(0, DEFAULTS["frequency"])

        ttk.Label(self.dynamic_frame, text="Amplitude (V):").grid(row=1, column=0, sticky="w")
        self.dynamic_inputs["amplitude"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["amplitude"].grid(row=1, column=1, padx=5, pady=5)
        self.dynamic_inputs["amplitude"].insert(0, DEFAULTS["amplitude"])

        ttk.Label(self.dynamic_frame, text="Offset (V):").grid(row=2, column=0, sticky="w")
        self.dynamic_inputs["offset"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["offset"].grid(row=2, column=1, padx=5, pady=5)
        self.dynamic_inputs["offset"].insert(0, DEFAULTS["offset"])

        ttk.Label(self.dynamic_frame, text="Number of Cycles:").grid(row=3, column=0, sticky="w")
        self.dynamic_inputs["n_cycles"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["n_cycles"].grid(row=3, column=1, padx=5, pady=5)
        self.dynamic_inputs["n_cycles"].insert(0, DEFAULTS["n_cycles"])

    def setup_pund_inputs(self):
        ttk.Label(self.dynamic_frame, text="Reset Amplitude (V):").grid(row=0, column=0, sticky="w")
        self.dynamic_inputs["reset_amp"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["reset_amp"].grid(row=0, column=1, padx=5, pady=5)
        self.dynamic_inputs["reset_amp"].insert(0, DEFAULTS["reset_amp"])

        ttk.Label(self.dynamic_frame, text="Reset Width (s):").grid(row=1, column=0, sticky="w")
        self.dynamic_inputs["reset_width"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["reset_width"].grid(row=1, column=1, padx=5, pady=5)
        self.dynamic_inputs["reset_width"].insert(0, DEFAULTS["reset_width"])

        ttk.Label(self.dynamic_frame, text="Reset Delay (s):").grid(row=2, column=0, sticky="w")
        self.dynamic_inputs["reset_delay"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["reset_delay"].grid(row=2, column=1, padx=5, pady=5)
        self.dynamic_inputs["reset_delay"].insert(0, DEFAULTS["reset_delay"])

        ttk.Label(self.dynamic_frame, text="P/U Amplitude (V):").grid(row=3, column=0, sticky="w")
        self.dynamic_inputs["p_u_amp"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["p_u_amp"].grid(row=3, column=1, padx=5, pady=5)
        self.dynamic_inputs["p_u_amp"].insert(0, DEFAULTS["p_u_amp"])

        ttk.Label(self.dynamic_frame, text="P/U Width (s):").grid(row=4, column=0, sticky="w")
        self.dynamic_inputs["p_u_width"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["p_u_width"].grid(row=4, column=1, padx=5, pady=5)
        self.dynamic_inputs["p_u_width"].insert(0, DEFAULTS["p_u_width"])

        ttk.Label(self.dynamic_frame, text="P/U Delay (s):").grid(row=5, column=0, sticky="w")
        self.dynamic_inputs["p_u_delay"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["p_u_delay"].grid(row=5, column=1, padx=5, pady=5)
        self.dynamic_inputs["p_u_delay"].insert(0, DEFAULTS["p_u_delay"])

        ttk.Label(self.dynamic_frame, text="Offset (V):").grid(row=6, column=0, sticky="w")
        self.dynamic_inputs["offset"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["offset"].grid(row=6, column=1, padx=5, pady=5)
        self.dynamic_inputs["offset"].insert(0, DEFAULTS["offset"])

    def run_measurement(self):
        if not self.measurement_type.get():
            print("No measurement type selected.")
            return

        print(f"Running {self.measurement_type.get()} measurement...")
        # get static inputs for passthrough to measurment object
        awg_address = self.awg_address_entry.get()
        osc_address = self.osc_address_entry.get()
        save_dir = self.save_dir_entry.get()
        measurement_type = self.measurement_type.get()
        if awg_address == "VIRTUAL":
            awg = VirtualAwg(awg_address)
        else:
            awg = Keysight81150a(awg_address)
        if osc_address == "VIRTUAL": 
            osc = VirtualScope(osc_address)
        else:
            osc = KeysightDSOX3024a(osc_address)

        v_div = float(self.vdiv_entry.get())
        area = float(eval(str(self.area_entry.get())))
        time_offset = float(self.timeshift_entry.get())*1.0e-9
        save_plots = bool(self.saveplots_entry.get())
        show_plots = save_plots
        auto_timeshift = bool(self.auto_timeshift_entry.get())

        if measurement_type == "HysteresisLoop":
            # get hyst specific inputs for passthrough to measurment object
            frequency = float(self.dynamic_inputs["frequency"].get())
            amplitude = float(self.dynamic_inputs["amplitude"].get())
            offset = float(self.dynamic_inputs["offset"].get())
            n_cycles = int(self.dynamic_inputs["n_cycles"].get())
            # initiate hyst object
            self.experiment = HysteresisLoop(awg=awg, osc=osc,
                                             frequency=frequency, amplitude=amplitude,
                                             offset=offset, n_cycles=n_cycles,
                                             save_dir=save_dir, v_div=v_div, time_offset=time_offset, area=area,
                                             save_plots=save_plots, show_plots=show_plots, auto_timeshift=auto_timeshift)
            
        elif measurement_type == "ThreePulsePund":
            # get pund specific inputs for passthrough to measurment object
            reset_amp = float(self.dynamic_inputs["reset_amp"].get())
            reset_width = float(self.dynamic_inputs["reset_width"].get())
            reset_delay = float(self.dynamic_inputs["reset_delay"].get())
            p_u_amp = float(self.dynamic_inputs["p_u_amp"].get())
            p_u_width = float(self.dynamic_inputs["p_u_width"].get())
            p_u_delay = float(self.dynamic_inputs["p_u_delay"].get())
            offset = float(self.dynamic_inputs["offset"].get())
            # initiate pund object
            self.experiment = ThreePulsePund(awg=awg, osc=osc,
                                             reset_amp=reset_amp, reset_width=reset_width, reset_delay=reset_delay,
                                             p_u_amp=p_u_amp, p_u_width=p_u_width, p_u_delay=p_u_delay,
                                             save_dir=save_dir, v_div=v_div, time_offset=time_offset, area=area, offset=offset,
                                             save_plots=save_plots, show_plots=show_plots, auto_timeshift=auto_timeshift)
        self.experiment.run_experiment()
        self.update_dynamic_defaults()
        self.plot_data(self.experiment.filename)

    def plot_data(self, event=None):
        self.ax.clear()
        metadata, data = standard_csv_to_metadata_and_data(self.experiment.filename)
        x_data = data[self.x_axis.get()]
        y_data = data[self.y_axis.get()]
        self.timeshift_entry.delete(0, tk.END)
        self.timeshift_entry.insert(0, metadata["time_offset"].values[0]*1e9) # update time offset input in case auto is used

        self.ax.plot(x_data, y_data, marker='.',color='k', label=f"{self.y_axis.get()} vs {self.x_axis.get()}")
        self.ax.set_xlabel(self.x_axis.get())
        self.ax.set_ylabel(self.y_axis.get())
        # self.ax.legend()
        self.canvas.draw()

if __name__ == "__main__":
    root = tk.Tk()
    app = FEMeasurementApp(root)
    root.mainloop()