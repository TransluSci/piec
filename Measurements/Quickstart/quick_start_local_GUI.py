"""Launch locally: python Measurements/Quickstart/awg_scope_GUI.py."""
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from piec.measurement.gui_utils import MeasurementApp
from quickstart_capture import Settings, capture


class QueueConsole:
    """Keep driver output off Tk's worker-unsafe widget interface."""
    def __init__(self, events):
        self.events = events

    def write(self, text):
        self.events.put(("log", text))

    def flush(self):
        pass


class QuickstartApp(MeasurementApp):
    def __init__(self, root):
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.result = None
        super().__init__(root, title="PIEC — Your first measurement", geometry="1450x900")
        # Preserve the familiar PIEC layout, but make worker logging thread-safe.
        sys.stdout = sys.stderr = QueueConsole(self.events)
        self.root.minsize(1150, 800)
        for widget in self.static_frame.winfo_children():
            widget.destroy()
        self.static_frame.configure(text="1. CHOOSE INSTRUMENTS")
        self.dynamic_frame.configure(text="2. CHOOSE A SIGNAL")
        self.plot_config_frame.configure(text="GETTING STARTED")
        self.controls = []

        self.mode = self._field(self.static_frame, 0, "Mode", "Virtual", ("Virtual", "Physical"))
        self.awg_address = self._field(self.static_frame, 1, "AWG VISA address", "")
        self.scope_address = self._field(self.static_frame, 2, "Scope VISA address", "")
        self.mode.bind("<<ComboboxSelected>>", self._mode_changed)
        self.mode_hint = ttk.Label(self.static_frame, wraplength=440, justify="left")
        self.mode_hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=8)

        self.waveform = self._field(self.dynamic_frame, 0, "Waveform", "Sine", ("Sine", "Square", "Ramp"))
        self.frequency = self._field(self.dynamic_frame, 1, "Frequency (Hz)", "1000")
        self.amplitude = self._field(self.dynamic_frame, 2, "Amplitude (Vpp)", "2")
        ttk.Label(self.dynamic_frame, text="2 Vpp spans −1 V to +1 V. Offset is zero.\nQuick-start range: 1–100,000 Hz; up to 2 Vpp.",
                  wraplength=440).grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(self.plot_config_frame, wraplength=440, justify="left", text=(
            "Start in Virtual mode and click Capture.\n"
            "Then select Square and capture again, followed by Ramp.\n\n"
            "The top plot previews the virtual AWG signal. The lower plot shows "
            "the ferroelectric sample response. On hardware, the plot shows "
            "the direct scope capture.\n\n"
            "Export CSV saves the last successful scope capture."
        )).pack(anchor="w")
        self.export_button = ttk.Button(self.plot_config_frame, text="Export CSV…", command=self.export_csv, state="disabled")
        self.export_button.pack(anchor="w", pady=10)
        self.run_button.configure(text="3. CAPTURE WAVEFORM")
        self._mode_changed()
        self.ax.set(title="Choose a signal and click Capture", xlabel="Time (ms)", ylabel="Voltage (V)")
        self.canvas.draw_idle()
        print("Welcome! Start with a virtual sine wave. Ctrl+Enter also captures.")
        self.poll_id = self.root.after(100, self._poll)

    def _field(self, parent, row, label, default, choices=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        widget = ttk.Combobox(parent, values=choices, state="readonly", width=23) if choices else ttk.Entry(parent, width=25)
        widget.grid(row=row, column=1, padx=5, pady=5, sticky="ew")
        if choices:
            widget.set(default)
        else:
            widget.insert(0, default)
        self.controls.append((widget, "readonly" if choices else "normal"))
        return widget

    def _mode_changed(self, event=None):
        physical = self.mode.get() == "Physical"
        for widget in (self.awg_address, self.scope_address):
            widget.configure(state="normal" if physical and not self.busy else "disabled")
        self.mode_hint.configure(text=(
            "Keysight 81150A + DSOX3024A. Connect AWG CH1 → scope CH1. "
            "Set the AWG to continuous output (burst off), Vpp units. "
            "The GUI configures 50 Ω and a CH1 rising-edge trigger; no trigger cable needed."
            if physical else "No hardware or VISA connection needed. Uses the existing virtual sample."
        ))

    def load_settings(self):
        # Always start in Virtual mode rather than restore a previous bench setup.
        pass

    def run_measurement(self):
        if self.busy or self.closing:
            return
        try:
            settings = Settings(
                mode=self.mode.get(), waveform={"Sine": "SIN", "Square": "SQU", "Ramp": "RAMP"}[self.waveform.get()],
                frequency=float(self.frequency.get()), amplitude_vpp=float(self.amplitude.get()),
                awg_address=self.awg_address.get(), scope_address=self.scope_address.get(),
            )
            settings.validate()
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Check the settings", str(exc), parent=self.root)
            return
        self.busy = True
        for widget, _ in self.controls:
            widget.configure(state="disabled")
        self.run_button.configure(state="disabled", text="Capturing…")
        self.export_button.configure(state="disabled")
        print(f"{settings.mode}: {settings.waveform}, {settings.frequency:g} Hz, {settings.amplitude_vpp:g} Vpp")
        threading.Thread(target=self._capture, args=(settings,), daemon=False).start()

    def _capture(self, settings):
        try:
            self.events.put(("result", capture(settings)))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.console.write(value)
                continue
            self.busy = False
            if kind == "result":
                self.result = value
                self._plot_capture()
                print(f"Captured {len(value.data)} samples. AWG output off. Export CSV when ready.")
            else:
                print(f"Capture failed: {value}\nIf this is a VISA timeout, check wiring and trigger settings. "
                      "If communication was lost, verify the AWG output is off at the instrument.")
                if not self.closing:
                    messagebox.showerror("Capture failed", value, parent=self.root)
            for widget, state in self.controls:
                widget.configure(state=state)
            self._mode_changed()
            self.run_button.configure(state="normal", text="3. CAPTURE WAVEFORM")
            self.export_button.configure(state="normal" if self.result is not None else "disabled")
        if self.closing and not self.busy:
            self._destroy()
            return
        self.poll_id = self.root.after(100, self._poll)

    def _plot_capture(self):
        result = self.result
        self.fig.clear()
        axes = self.fig.subplots(2 if result.applied is not None else 1, 1, squeeze=False).ravel()
        if result.applied is not None:
            axes[0].plot(result.applied.Time * 1000, result.applied.Voltage)
            axes[0].set(title="Applied waveform", xlabel="Time (ms)", ylabel="Voltage (V)")
        axes[-1].plot(result.data.Time * 1000, result.data.Voltage)
        axes[-1].set(title="Virtual sample response" if result.applied is not None else "Physical scope capture",
                     xlabel="Time (ms)", ylabel="Voltage (V)")
        for ax in axes:
            ax.grid(True, alpha=0.3)
        self.fig.suptitle(f"{result.settings.mode} · {result.settings.waveform} · {result.settings.frequency:g} Hz · {result.settings.amplitude_vpp:g} Vpp", fontsize=12)
        self.fig.tight_layout()
        self.toolbar.update()
        self.canvas.draw_idle()

    def export_csv(self):
        if self.result is None or self.busy:
            return
        settings = self.result.settings
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".csv", filetypes=[("CSV data", "*.csv")],
            initialfile=f"{settings.mode.lower()}_{settings.waveform.lower()}_{settings.frequency:g}Hz.csv",
        )
        if path:
            try:
                self.result.data.to_csv(path, index=False)
                print(f"Saved {path}")
            except OSError as exc:
                messagebox.showerror("Could not save CSV", str(exc), parent=self.root)

    def on_closing(self):
        if self.busy:
            self.closing = True
            self.run_button.configure(text="Closing after capture cleanup…")
            print("Waiting for capture and output-off cleanup before closing.")
        else:
            self._destroy()

    def _destroy(self):
        self.root.after_cancel(self.poll_id)
        self.root.after_cancel(self._load_settings_id)
        sys.stdout, sys.stderr = self.original_stdout, self.original_stderr
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    QuickstartApp(root)
    root.mainloop()
