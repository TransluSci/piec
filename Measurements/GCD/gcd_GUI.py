"""PIEC GCD measurement GUI for physical and virtual sourcemeters."""

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.gcd import GCD
from piec.measurement.gui_utils import MeasurementApp
from piec.simulation.battery import Battery


DEFAULTS = {
    'save_dir': 'scratch', 'current': 0.01, 'voltage_lower': 3.1,
    'voltage_upper': 4.1, 'n_cycles': 3, 'sample_interval': 1.0,
    'max_half_cycle_time': 1000.0, 'voltage_compliance': 5.0,
    'capacity_ah': 0.001, 'initial_soc': 0.2,
}


class GCDApp(MeasurementApp):
    """Use the shared PIEC layout, settings, console, and plot toolbar."""

    _instruments = ('sourcemeter',)

    def __init__(self, root):
        self.is_measuring = False
        self.measurement_thread = None
        self._measurement_error = None
        self._original_sample = None
        self._battery = None
        self._closing_requested = False
        self._poll_id = None
        super().__init__(root, title='GCD Measurement GUI', geometry='1600x1000')
        self.save_dir_entry.insert(0, DEFAULTS['save_dir'])
        self.setup_dynamic_inputs()
        self.status_var = tk.StringVar(master=root, value='Ready')
        ttk.Label(self.plot_config_frame, textvariable=self.status_var).grid(
            row=2, column=0, columnspan=2, sticky='w', pady=5)
        self.control_frame = ttk.Frame(self.right_panel)
        self.control_frame.grid(row=1, column=0, pady=10)
        self.pause_button = ttk.Button(self.control_frame, text='PAUSE', command=self.toggle_pause)
        self.pause_button.pack(side='left', padx=5)
        self.stop_button = ttk.Button(self.control_frame, text='STOP', command=self.stop_measurement)
        self.stop_button.pack(side='left', padx=5)
        self.control_frame.grid_remove()
        print('Welcome to the GCD Measurement GUI! Ctrl+Enter runs the selected sourcemeter.')

    def setup_instrument_inputs(self):
        """Keep shared discovery and allow manually entered physical addresses."""
        super().setup_instrument_inputs()
        self.instrument_address_entries['sourcemeter'].configure(state='normal')

    def setup_dynamic_inputs(self):
        self.dynamic_frame.configure(text='GCD MEASUREMENT INPUTS')
        self.dynamic_inputs = {}
        labels = {
            'current': 'Current magnitude (A)', 'voltage_lower': 'Discharge cutoff (V)',
            'voltage_upper': 'Charge cutoff (V)', 'n_cycles': 'Number of cycles',
            'sample_interval': 'Sample interval (s)',
            'max_half_cycle_time': 'Half-cycle timeout (s)',
            'voltage_compliance': 'Voltage compliance (V)',
            'capacity_ah': 'Virtual battery capacity (Ah)', 'initial_soc': 'Virtual initial SOC (0–1)',
        }
        for row, (name, label) in enumerate(labels.items()):
            ttk.Label(self.dynamic_frame, text=f'{label}:').grid(row=row, column=0, sticky='w')
            entry = ttk.Entry(self.dynamic_frame, width=18)
            entry.grid(row=row, column=1, padx=5, pady=3)
            entry.insert(0, DEFAULTS[name])
            self.dynamic_inputs[name] = entry
        row = len(labels)
        ttk.Label(self.dynamic_frame, text='Sense mode:').grid(row=row, column=0, sticky='w')
        self.sense_mode = ttk.Combobox(self.dynamic_frame, values=['2W', '4W'], state='readonly', width=15)
        self.sense_mode.set('2W')
        self.sense_mode.grid(row=row, column=1, padx=5, pady=3)
        self.animate_var = tk.BooleanVar(master=self.root, value=True)
        self.saveplots_var = tk.BooleanVar(master=self.root, value=True)
        ttk.Checkbutton(self.dynamic_frame, text='Animate virtual run', variable=self.animate_var).grid(
            row=row + 1, column=0, columnspan=2, sticky='w', pady=3)
        ttk.Checkbutton(self.dynamic_frame, text='Save voltage plot', variable=self.saveplots_var).grid(
            row=row + 2, column=0, columnspan=2, sticky='w', pady=3)
        columns = ['time (s)', 'voltage (V)', 'current (A)', 'cycle']
        for row, (name, default) in enumerate((('x_axis', 'time (s)'), ('y_axis', 'voltage (V)'))):
            ttk.Label(self.plot_config_frame, text=f'{name[0].upper()}-axis:').grid(row=row, column=0, sticky='w')
            selector = ttk.Combobox(self.plot_config_frame, values=columns, state='readonly')
            selector.set(default)
            selector.grid(row=row, column=1, padx=5, pady=3)
            selector.bind('<<ComboboxSelected>>', self.plot_data)
            setattr(self, name, selector)
        self._apply_saved_dynamic()

    def run_measurement(self):
        if self.is_measuring:
            return
        try:
            values = {name: (int(widget.get()) if name == 'n_cycles' else float(widget.get()))
                      for name, widget in self.dynamic_inputs.items()
                      if name not in ('capacity_ah', 'initial_soc')}
            self.experiment = None
            instruments = self.connect_instruments()
            smu = instruments['sourcemeter']
            virtual = isinstance(smu, VirtualInstrument)
            if virtual:
                battery = Battery(capacity_ah=float(self.dynamic_inputs['capacity_ah'].get()),
                                  initial_soc=float(self.dynamic_inputs['initial_soc'].get()))
                self._original_sample = smu.sample
                self._battery = battery
                smu.sample = battery
            experiment = GCD(
                smu, **values, sense_mode=self.sense_mode.get(), virtual_time=virtual,
                simulation_delay=0.005 if virtual and self.animate_var.get() else 0.0,
                save_dir=self.save_dir_entry.get(), show_plots=False, save_plots=False)
        except Exception as error:
            self._restore_sample()
            self.close_instruments()
            messagebox.showerror('GCD setup', str(error), parent=self.root)
            return
        self.experiment = experiment
        self._save_plot = self.saveplots_var.get()
        self._measurement_error = None
        self.is_measuring = True
        self.paused = False
        self.run_button.grid_remove()
        self.control_frame.grid()
        self.pause_button.configure(text='PAUSE', state='normal')
        self.stop_button.configure(state='normal')
        self.status_var.set('Running GCD')
        print('Running GCD with ' + ('a fresh virtual battery.' if virtual else 'the selected physical SMU.'))
        self.measurement_thread = threading.Thread(target=self._run_experiment, daemon=True)
        self.measurement_thread.start()
        self.update_plot_loop()

    def _run_experiment(self):
        # Tk widgets and matplotlib stay on the main thread.
        try:
            self.experiment.run_experiment()
        except BaseException as error:
            self._measurement_error = error

    def toggle_pause(self):
        if self.is_measuring:
            self.paused = not self.paused
            self.experiment.pause_requested = self.paused
            self.pause_button.configure(text='RESUME' if self.paused else 'PAUSE')
            self.status_var.set('Pausing — output will be isolated' if self.paused else 'Running GCD')

    def stop_measurement(self):
        if self.is_measuring:
            self.experiment.abort_requested = True
            self.stop_button.configure(state='disabled')
            self.pause_button.configure(state='disabled')
            self.status_var.set('Stopping and saving partial data...')

    def _restore_sample(self):
        if self._battery is not None:
            if VirtualInstrument._shared_fe_sample is self._battery:
                VirtualInstrument.set_virtual_sample(self._original_sample)
            self._battery = None
            self._original_sample = None

    def update_plot_loop(self):
        self._poll_id = None
        self.plot_data()
        if self.measurement_thread.is_alive():
            self._poll_id = self.root.after(100, self.update_plot_loop)
            return
        self.is_measuring = False
        self._restore_sample()
        self.control_frame.grid_remove()
        self.run_button.grid()
        if self.experiment.filename:
            try:
                # Save the canonical voltage/time PNG on the UI thread, independently
                # of the current GUI axis selections.
                self.experiment.save_plots = self._save_plot
                self.experiment.analyze()
                self.experiment.save_data()
                self.experiment.history[-1] = self.experiment.metadata.copy()
                print(f'Data: {self.experiment.filename}')
                if self.experiment.plot_filename:
                    print(f'Plot: {self.experiment.plot_filename}')
            except Exception as error:
                self._measurement_error = self._measurement_error or error
        self.status_var.set(f'{self.experiment.status.capitalize()} — '
                            f'{self.experiment.completed_cycles} complete cycles')
        self.plot_data()
        if self._measurement_error is not None:
            details = str(self._measurement_error)
            if self.experiment.cleanup_error:
                details += '\n\nShutdown could not be confirmed: ' + self.experiment.cleanup_error
            if self.experiment.save_error:
                details += '\n\nData could not be saved: ' + self.experiment.save_error
            print(f'Measurement failed: {details}')
            messagebox.showerror('GCD measurement', details, parent=self.root)
        else:
            print(f'Measurement {self.experiment.status}. Output off.')
        if self._closing_requested:
            self.on_closing()

    def plot_data(self, event=None):
        if self.experiment is None:
            return
        data = self.experiment.get_data_snapshot()
        if data.empty:
            return
        x, y = self.x_axis.get(), self.y_axis.get()
        if x not in data or y not in data:
            return
        self.ax.clear()
        self.ax.plot(data[x], data[y], color='tab:blue')
        self.ax.set(xlabel=x, ylabel=y, title='GCD Measurement Data')
        self.canvas.draw_idle()
        if self.is_measuring and not self.paused and not self.experiment.abort_requested:
            last = data.iloc[-1]
            self.status_var.set(f'Cycle {last["cycle"]}/{self.experiment.n_cycles}: '
                                f'{last["phase"]} — {last["voltage (V)"]:.3f} V')

    def on_closing(self):
        if self.is_measuring:
            self._closing_requested = True
            self.stop_measurement()
            return
        self._closing_requested = False
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self._restore_sample()
        super().on_closing()


if __name__ == '__main__':
    root = tk.Tk()
    app = GCDApp(root)
    root.mainloop()
