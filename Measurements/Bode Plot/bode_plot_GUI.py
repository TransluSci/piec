import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import tkinter as tk
from tkinter import ttk
import threading
import time
import numpy as np
import pandas as pd

from piec.drivers.autodetect import autodetect, _safe_close
from piec.drivers.awg.awg import Awg
from piec.drivers.oscilloscope.oscilloscope import Oscilloscope
from piec.drivers.analog_discovery import AnalogDiscovery
from piec.drivers.oscilloscope.analog_discovery_2 import AnalogDiscovery2Oscilloscope
from piec.measurement.frequency_response import FrequencyResponse
from piec.measurement.gui_utils import MeasurementApp


class _LiveFrequencyResponse(FrequencyResponse):
    """FrequencyResponse subclass that tracks data live for GUI updates.

    Uses underscore-prefixed attributes so _update_metadata() ignores them.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._live_freq = []
        self._live_mag = []
        self._live_phase = []
        self.pause_requested = False
        self.abort_requested = False

    def sweep(self):
        frequencies = self._frequency_points()
        rows = []
        self._live_freq = []
        self._live_mag = []
        self._live_phase = []

        print(f"Starting frequency response sweep: {self.f_start:.4g} Hz to {self.f_stop:.4g} Hz, "
              f"{len(frequencies)} points...")

        for i, frequency in enumerate(frequencies):
            while self.pause_requested and not self.abort_requested:
                time.sleep(0.1)
            if self.abort_requested:
                print("Measurement aborted by user.")
                break

            vin_c, vout_c = self.measure_point(frequency)
            vin_mag = abs(vin_c)
            vout_mag = abs(vout_c)

            if vin_mag == 0:
                print(f"  [WARN] No input signal detected at {frequency:.5g} Hz; skipping point.")
                continue

            gain_c = vout_c / vin_c
            magnitude_db = 20.0 * np.log10(abs(gain_c))
            phase_deg = np.degrees(np.angle(gain_c))
            rows.append((frequency, magnitude_db, phase_deg, vin_mag, vout_mag))

            self._live_freq.append(frequency)
            self._live_mag.append(magnitude_db)
            # Keep the live phase trace continuous the same way the final data is unwrapped.
            self._live_phase = list(np.degrees(np.unwrap(np.radians(
                [row[2] for row in rows]))))

            if (i + 1) % max(1, len(frequencies) // 10) == 0 or i == len(frequencies) - 1:
                print(f"  {i + 1}/{len(frequencies)}: f={frequency:.5g} Hz  "
                      f"gain={magnitude_db:.2f} dB  phase={self._live_phase[-1]:.1f} deg")

        self.data = pd.DataFrame(rows, columns=[
            "Frequency (Hz)", "Magnitude (dB)", "Phase (deg)", "Vin (V)", "Vout (V)"
        ])
        if not self.data.empty:
            self.data["Phase (deg)"] = np.degrees(np.unwrap(np.radians(self.data["Phase (deg)"])))
        print("Sweep complete.")


DEFAULTS = {
    "save_dir": r"your\default\save\directory",
    "awg_channel": "1",
    "input_channel": "1",
    "output_channel": "2",
    "f_start": 10.0,
    "f_stop": 25e6,
    "points_per_decade": 10,
    "amplitude": 0.5,
    "input_range": 2.0,
    "output_range": 10.0,
    "autorange": True,
}


class BodePlotApp(MeasurementApp):
    def __init__(self, root):
        super().__init__(root, title="Amplifier Bode Plot GUI", geometry="1600x900")
        print("Welcome to the Bode Plot GUI!")
        print("Ctrl+Enter: Run Measurement")
        print("Wiring: AWG CH<n> -> DUT input | Scope CH<input> -> DUT input node | Scope CH<output> -> DUT output")

        self.measurement_thread = None
        self.is_measuring = False
        self._ad2_device = None
        self._ad2_device_index = None
        self._awg_entries = {}   # label -> ('visa', resource, driver_class)
        self._osc_entries = {}   # label -> ('visa', resource, driver_class) | ('ad2', index, None)

        # Static Inputs (Save Dir is at row 0 in base)
        self.save_dir_entry.insert(0, DEFAULTS["save_dir"])

        ttk.Label(self.static_frame, text="AWG:").grid(row=1, column=0, sticky="w")
        self.awg_entry = ttk.Combobox(self.static_frame, values=[], state="readonly", width=45)
        self.awg_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(
            self.static_frame, text="Refresh", command=self.refresh_instruments, style="TButton"
        ).grid(row=1, column=2, rowspan=2, padx=5)

        ttk.Label(self.static_frame, text="Oscilloscope:").grid(row=2, column=0, sticky="w")
        self.osc_entry = ttk.Combobox(self.static_frame, values=[], state="readonly", width=45)
        self.osc_entry.grid(row=2, column=1, padx=5, pady=5)

        # Dynamic Inputs — sweep parameters
        self.dynamic_frame.config(text="BODE SWEEP INPUTS")
        self.dynamic_inputs = {}

        ttk.Label(self.dynamic_frame, text="AWG Channel:").grid(row=0, column=0, sticky="w")
        self.dynamic_inputs["awg_channel"] = ttk.Combobox(self.dynamic_frame, values=["1", "2"],
                                                            state="readonly", width=17)
        self.dynamic_inputs["awg_channel"].grid(row=0, column=1, padx=5, pady=5)
        self.dynamic_inputs["awg_channel"].set(DEFAULTS["awg_channel"])

        ttk.Label(self.dynamic_frame, text="Input Scope Channel:").grid(row=1, column=0, sticky="w")
        self.dynamic_inputs["input_channel"] = ttk.Combobox(self.dynamic_frame, values=["1", "2"],
                                                              state="readonly", width=17)
        self.dynamic_inputs["input_channel"].grid(row=1, column=1, padx=5, pady=5)
        self.dynamic_inputs["input_channel"].set(DEFAULTS["input_channel"])

        ttk.Label(self.dynamic_frame, text="Output Scope Channel:").grid(row=2, column=0, sticky="w")
        self.dynamic_inputs["output_channel"] = ttk.Combobox(self.dynamic_frame, values=["1", "2"],
                                                               state="readonly", width=17)
        self.dynamic_inputs["output_channel"].grid(row=2, column=1, padx=5, pady=5)
        self.dynamic_inputs["output_channel"].set(DEFAULTS["output_channel"])

        ttk.Label(self.dynamic_frame, text="Start Frequency (Hz):").grid(row=3, column=0, sticky="w")
        self.dynamic_inputs["f_start"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["f_start"].grid(row=3, column=1, padx=5, pady=5)
        self.dynamic_inputs["f_start"].insert(0, DEFAULTS["f_start"])

        ttk.Label(self.dynamic_frame, text="Stop Frequency (Hz):").grid(row=4, column=0, sticky="w")
        self.dynamic_inputs["f_stop"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["f_stop"].grid(row=4, column=1, padx=5, pady=5)
        self.dynamic_inputs["f_stop"].insert(0, DEFAULTS["f_stop"])

        ttk.Label(self.dynamic_frame, text="Points per Decade:").grid(row=5, column=0, sticky="w")
        self.dynamic_inputs["points_per_decade"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["points_per_decade"].grid(row=5, column=1, padx=5, pady=5)
        self.dynamic_inputs["points_per_decade"].insert(0, DEFAULTS["points_per_decade"])

        ttk.Label(self.dynamic_frame, text="Drive Amplitude (Vpp):").grid(row=6, column=0, sticky="w")
        self.dynamic_inputs["amplitude"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["amplitude"].grid(row=6, column=1, padx=5, pady=5)
        self.dynamic_inputs["amplitude"].insert(0, DEFAULTS["amplitude"])

        ttk.Label(self.dynamic_frame, text="Input Ch Start Range (V):").grid(row=7, column=0, sticky="w")
        self.dynamic_inputs["input_range"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["input_range"].grid(row=7, column=1, padx=5, pady=5)
        self.dynamic_inputs["input_range"].insert(0, DEFAULTS["input_range"])

        ttk.Label(self.dynamic_frame, text="Output Ch Start Range (V):").grid(row=8, column=0, sticky="w")
        self.dynamic_inputs["output_range"] = ttk.Entry(self.dynamic_frame, width=20)
        self.dynamic_inputs["output_range"].grid(row=8, column=1, padx=5, pady=5)
        self.dynamic_inputs["output_range"].insert(0, DEFAULTS["output_range"])

        self.autorange_entry = tk.BooleanVar(value=DEFAULTS["autorange"])
        ttk.Checkbutton(
            self.dynamic_frame, text="Autorange channels during sweep",
            variable=self.autorange_entry, onvalue=True, offvalue=False,
        ).grid(row=9, column=0, columnspan=2, pady=5, sticky="w")

        # No dynamic axis choices for a Bode plot (always freq vs mag/phase) --
        # hide the otherwise-empty plot configuration card.
        self.plot_config_frame.pack_forget()

        # Scan after the window is up (this is a live probe of every connected
        # instrument, not just an enumeration, so it isn't instant) -- run it
        # slightly after load_settings so a saved selection can survive if the
        # same device is still connected.
        self.root.after(300, self.refresh_instruments)

    # --- Instrument discovery ---

    def _scan_connected_instruments(self):
        """
        Probes every connected VISA resource once and classifies it as an
        Awg, an Oscilloscope, or neither (via autodetect(), which already
        knows every registered piec driver -- no separate model list to
        maintain here), plus enumerates any connected Analog Discovery
        devices. Each VISA probe opens, queries *IDN?, and closes again;
        nothing is left connected by a scan.
        """
        awg_entries = {}
        osc_entries = {}

        for resource in self.get_visa_resources():
            try:
                inst = autodetect(address=resource, verbose=False)
            except Exception as e:
                print(f"  (could not probe {resource}: {e})")
                continue
            if inst is None:
                continue

            cls = type(inst)
            try:
                idn = inst.idn()
            except Exception:
                idn = ""
            finally:
                _safe_close(inst)

            label = f"{cls.__name__} ({(idn or resource).strip()})"
            is_awg = issubclass(cls, Awg)
            is_osc = issubclass(cls, Oscilloscope)
            if is_awg:
                awg_entries[label] = ("visa", resource, cls)
            if is_osc:
                osc_entries[label] = ("visa", resource, cls)
            if not is_awg and not is_osc:
                print(f"  (found {cls.__name__} at {resource}, but it's neither an AWG nor an "
                      "oscilloscope driver -- not offered here)")

        try:
            for dev in AnalogDiscovery.list_devices():
                label = f"Analog Discovery 2 [{dev['index']}] {dev['name']} ({dev['serial']})"
                osc_entries[label] = ("ad2", dev["index"], None)
        except ImportError:
            pass  # WaveForms runtime not installed -- no AD2 devices to offer
        except Exception as e:
            print(f"  (could not enumerate Analog Discovery devices: {e})")

        return awg_entries, osc_entries

    def refresh_instruments(self):
        print("Scanning for connected instruments (this probes each device, so it may take a moment)...")
        awg_entries, osc_entries = self._scan_connected_instruments()
        self._awg_entries = awg_entries
        self._osc_entries = osc_entries

        self._set_combobox_values(self.awg_entry, list(awg_entries.keys()))
        self._set_combobox_values(self.osc_entry, list(osc_entries.keys()))

        print(f"Found {len(awg_entries)} AWG(s) and {len(osc_entries)} oscilloscope(s).")

    @staticmethod
    def _set_combobox_values(combobox, labels):
        """Updates a combobox's choices, keeping the current selection if it's still valid."""
        current = combobox.get()
        combobox["values"] = labels
        if current in labels:
            combobox.set(current)
        elif labels:
            combobox.set(labels[0])
        else:
            combobox.set("")

    def setup_plot(self, parent):
        """Overrides the single-axes base plot with a magnitude/phase Bode pair."""
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

        self.plot_frame = ttk.LabelFrame(parent, text="BODE PLOT", padding=5, style="Card.TLabelframe")
        self.plot_frame.grid(row=0, column=0, sticky="nsew")

        self.fig, (self.ax_mag, self.ax_phase) = plt.subplots(2, 1, sharex=True)
        self.ax_mag.set_ylabel("Magnitude (dB)")
        self.ax_phase.set_ylabel("Phase (deg)")
        self.ax_phase.set_xlabel("Frequency (Hz)")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --- Instrument construction ---

    def _get_or_open_ad2(self, index):
        """Opens (or reuses) the Analog Discovery 2 -- WaveForms only allows
        one open handle per device, so repeated runs must not reopen it."""
        if self._ad2_device is not None:
            if self._ad2_device_index == index:
                return self._ad2_device
            try:
                self._ad2_device.close()
            except Exception:
                pass
            self._ad2_device = None

        self._ad2_device = AnalogDiscovery(address=index, verbose=False)
        self._ad2_device_index = index
        return self._ad2_device

    def _make_awg(self, label):
        _, address, cls = self._awg_entries[label]
        return cls(address=address, verbose=False)

    def _make_oscilloscope(self, label):
        kind, address, cls = self._osc_entries[label]
        if kind == "ad2":
            device = self._get_or_open_ad2(address)
            return AnalogDiscovery2Oscilloscope(device, verbose=False)
        return cls(address=address, verbose=False)

    def run_measurement(self):
        if self.is_measuring:
            print("Measurement already in progress...")
            return

        print("Running Bode plot measurement...")

        awg_label = self.awg_entry.get()
        osc_label = self.osc_entry.get()
        if not awg_label or awg_label not in self._awg_entries:
            print("ERROR: No AWG selected (click Refresh to scan for connected instruments).")
            return
        if not osc_label or osc_label not in self._osc_entries:
            print("ERROR: No oscilloscope selected (click Refresh to scan for connected instruments).")
            return

        save_dir = self.save_dir_entry.get()
        awg_channel = int(self.dynamic_inputs["awg_channel"].get())
        input_channel = int(self.dynamic_inputs["input_channel"].get())
        output_channel = int(self.dynamic_inputs["output_channel"].get())
        f_start = float(self.dynamic_inputs["f_start"].get())
        f_stop = float(self.dynamic_inputs["f_stop"].get())
        points_per_decade = int(self.dynamic_inputs["points_per_decade"].get())
        amplitude = float(self.dynamic_inputs["amplitude"].get())
        input_range = float(self.dynamic_inputs["input_range"].get())
        output_range = float(self.dynamic_inputs["output_range"].get())
        autorange = bool(self.autorange_entry.get())

        # Update defaults to current values
        DEFAULTS.update({
            "awg_channel": str(awg_channel), "input_channel": str(input_channel),
            "output_channel": str(output_channel), "f_start": f_start, "f_stop": f_stop,
            "points_per_decade": points_per_decade, "amplitude": amplitude,
            "input_range": input_range, "output_range": output_range, "autorange": autorange,
        })

        try:
            awg = self._make_awg(awg_label)
            osc = self._make_oscilloscope(osc_label)
        except Exception as e:
            print(f"ERROR: Could not connect to instruments: {e}")
            return

        try:
            self.experiment = _LiveFrequencyResponse(
                awg=awg, osc=osc,
                awg_channel=awg_channel, input_channel=input_channel, output_channel=output_channel,
                f_start=f_start, f_stop=f_stop, points_per_decade=points_per_decade,
                amplitude=amplitude, input_range=input_range, output_range=output_range,
                autorange=autorange, save_dir=save_dir,
            )
        except TypeError as e:
            print(f"ERROR: {e}")
            return

        self.is_measuring = True
        self.paused = False
        self.add_control_buttons()

        def _run():
            self.experiment.configure_scope()
            self.experiment.configure_awg()
            try:
                self.experiment.sweep()
            finally:
                self.experiment.awg.output(self.experiment.awg_channel, False)
            self.experiment.save_data()

        self.measurement_thread = threading.Thread(target=_run, daemon=True)
        self.measurement_thread.start()
        self.update_plot_loop()

    def add_control_buttons(self):
        """Show pause and stop controls while a sweep is running."""
        self.control_frame = ttk.Frame(self.right_panel, style="TFrame")
        self.control_frame.grid(row=1, column=0, pady=10)

        self.pause_button = ttk.Button(
            self.control_frame, text="PAUSE", command=self.toggle_pause, style="TButton",
        )
        self.pause_button.pack(side="left", padx=5)

        self.stop_button = ttk.Button(
            self.control_frame, text="STOP", command=self.stop_measurement, style="TButton",
        )
        self.stop_button.pack(side="left", padx=5)
        self.run_button.grid_remove()

    def toggle_pause(self):
        if not self.is_measuring or not hasattr(self, "experiment"):
            return
        self.paused = not self.paused
        self.experiment.pause_requested = self.paused
        self.pause_button.config(text="RESUME" if self.paused else "PAUSE")
        print("Measurement paused." if self.paused else "Measurement resumed.")

    def stop_measurement(self):
        if not self.is_measuring or not hasattr(self, "experiment"):
            return
        print("Stopping measurement...")
        self.experiment.abort_requested = True
        self.stop_button.config(state="disabled")

    def cleanup_controls(self):
        """Remove sweep controls and restore the run button."""
        if hasattr(self, "control_frame"):
            self.control_frame.destroy()
        self.run_button.grid()
        self.run_button.config(state="normal")

    def update_plot_loop(self):
        if not self.is_measuring:
            return

        self.plot_data()

        if self.measurement_thread and self.measurement_thread.is_alive():
            self.root.after(500, self.update_plot_loop)
        else:
            self.is_measuring = False
            self.cleanup_controls()
            print("Measurement complete.")
            self.plot_data()

    def plot_data(self, event=None):
        if not hasattr(self, "experiment"):
            return

        freq = self.experiment._live_freq
        mag = self.experiment._live_mag
        phase = self.experiment._live_phase

        if not freq:
            return

        self.ax_mag.clear()
        self.ax_mag.semilogx(freq, mag, marker=".", color="k")
        self.ax_mag.set_ylabel("Magnitude (dB)")
        self.ax_mag.grid(True, which="both", alpha=0.3)

        self.ax_phase.clear()
        self.ax_phase.semilogx(freq, phase, marker=".", color="r")
        self.ax_phase.set_xlabel("Frequency (Hz)")
        self.ax_phase.set_ylabel("Phase (deg)")
        self.ax_phase.grid(True, which="both", alpha=0.3)

        self.canvas.draw()

    def on_closing(self):
        if self._ad2_device is not None:
            try:
                self._ad2_device.close()
            except Exception:
                pass
            self._ad2_device = None
        super().on_closing()


if __name__ == "__main__":
    root = tk.Tk()
    app = BodePlotApp(root)
    root.mainloop()
