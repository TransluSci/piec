"""Generic PIEC MOKE GUI. Run python Measurements/MOKE/moke_GUI.py."""
from functools import partial
import json
import math
from pathlib import Path
import queue
import threading
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import pandas as pd

from piec.measurement.gui_utils import MeasurementApp
from piec.measurement.moke import MOKE
from piec.analysis.moke import analyze_moke_dataframe, plot_moke_loop
from piec.drivers.field_controller.virtual_field_controller import VirtualFieldController
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.daq.daq import Daq
from piec.drivers.autodetect import autodetect, _open_mcc_driver, _safe_close, _resolve_type_string
from piec.drivers.emulators.daq_to_field_controller import DaqFieldController
from piec.drivers.emulators.daq_to_dmm import DaqAsDMM
from piec.drivers.emulators.daq_to_gaussmeter import DaqAsGaussmeter
from piec.drivers.emulators.source_as_field_controller import SourceAsFieldController
from piec.simulation.magnetic_material import ArctanMOKE

DAQ_ADDRESS = 'DAQ emulator'
SOURCE_ADDRESS = 'Source emulator'
DEFAULT_DAQ_AI_MODE = 'DIFF'
DAQ_AI_MODES = ('DIFF', 'SE')
DAQ_AI_CHOICES = {
    'DIFF': ('Unassigned', *(f'AI{i} (AIN{2*i} − AIN{2*i+1})' for i in range(4))),
    'SE': ('Unassigned', *(f'AIN{i} (AGND ref.)' for i in range(8))),
}
DEFAULT_DAQ_PATHS = {
    'longitudinal': {'output': 0, 'field_input': 0, 'signal_input': 2},
    'polar': {'output': 1, 'field_input': 1, 'signal_input': 3},
}
DEFAULT_SOURCE = dict(category='sourcemeter', address='VIRTUAL', mode='current', channel=1,
                      gain=100.0, offset=0.0, minimum=-1.0, maximum=1.0, compliance=10.0)
GEOMETRIES = ('longitudinal', 'polar', 'transverse')
DAQ_CHANNELS = {'field_controller': 'output', 'dmm': 'signal_input', 'gaussmeter': 'field_input'}


class _QueuedConsole:
    def __init__(self, events):
        self.events = events

    def write(self, text):
        self.events.put(('log', text))

    def flush(self):
        pass


class MOKEApp(MeasurementApp):
    """Required field source and optical DMM, with optional field measurement.

    Standard address discovery comes from MeasurementApp. DAQ channel adapters
    are selected explicitly and borrow one connection owned by this GUI.
    """
    _instruments = ('field_controller', 'dmm', 'gaussmeter')

    def __init__(self, root, paths=None):
        self._worker = None
        self._events = queue.Queue()
        self._updates = queue.Queue(maxsize=1)
        self._closing = False
        self._last_update = None
        self._owned_daq = None
        self._owned_source = None
        self._source_output = None
        self._setup_window = None
        paths = DEFAULT_DAQ_PATHS if paths is None else paths
        self.connection_setup = {'board': '0', 'ai_mode': DEFAULT_DAQ_AI_MODE,
                                 'ao_sample_rate': 1000.0,
                                 'profiles': {}, 'source': dict(DEFAULT_SOURCE)}
        for geometry in GEOMETRIES:
            profile = dict(output=None, field_input=None, signal_input=None,
                           command_gain=1000.0, command_offset=0.0,
                           monitor_gain=1000.0, monitor_offset=0.0)
            profile.update(paths.get(geometry, {}))
            self.connection_setup['profiles'][geometry] = profile
        super().__init__(root, title='PIEC - MOKE', geometry='1500x900')
        sys.stdout = sys.stderr = _QueuedConsole(self._events)
        self.save_dir_entry.insert(0, 'scratch')
        for widget in self.instrument_address_entries.values():
            widget['values'] = list(widget['values']) + [DAQ_ADDRESS]
        selector = self.instrument_address_entries['field_controller']
        selector['values'] = list(selector['values']) + [SOURCE_ADDRESS]
        self.use_gaussmeter = tk.BooleanVar(root, value=False)
        self.gaussmeter_toggle = ttk.Checkbutton(
            self.static_frame, text='Use gaussmeter', variable=self.use_gaussmeter,
            command=self._update_gaussmeter)
        self.gaussmeter_toggle.grid(row=2, column=0, columnspan=2, sticky='w', pady=5)
        self.setup_button = ttk.Button(self.static_frame, text='CONNECTION SETUP...',
                                        command=self.open_connection_setup)
        self.setup_button.grid(row=3, column=0, columnspan=3, sticky='ew', pady=5)
        self.inputs = {}
        self._input(self.static_frame, 'Geometry', 'longitudinal', GEOMETRIES, row=4)
        self._input(self.static_frame, 'Mode', 'stepped', ('stepped', 'continuous'), row=5)
        self.geometry_note = ttk.Label(self.static_frame, wraplength=470, foreground='#B9C6D1')
        self.geometry_note.grid(row=6, column=0, columnspan=3, sticky='w', pady=(4, 0))
        plot_axes = ('field (Oe)', 'time (s)', 'requested field (Oe)', 'signal (V)')
        self._input(self.plot_config_frame, 'Display', 'Cycle average',
                    ('Cycle average', 'Most recent cycle', 'Live signal'), row=0)
        self._input(self.plot_config_frame, 'X-axis', 'field (Oe)', plot_axes, row=1)
        self._input(self.plot_config_frame, 'Y-axis', 'signal (V)', plot_axes, row=2)
        self.inputs['Geometry'].bind('<<ComboboxSelected>>', lambda event: self._update_geometries())
        for selector in self.instrument_address_entries.values():
            selector.bind('<<ComboboxSelected>>', lambda event: self._update_geometries(), add='+')
        self.inputs['Mode'].bind('<<ComboboxSelected>>', self.update_dynamic_inputs)
        self.inputs['Display'].bind('<<ComboboxSelected>>', self._on_display_change)
        self.inputs['X-axis'].bind('<<ComboboxSelected>>', lambda event: self._draw())
        self.inputs['Y-axis'].bind('<<ComboboxSelected>>', lambda event: self._draw())
        self.saveplots_entry = tk.BooleanVar(value=False)
        self.save_plots_checkbox = ttk.Checkbutton(
            self.plot_config_frame,
            text='Save Plots?',
            variable=self.saveplots_entry,
            onvalue=True,
            offvalue=False,
        )
        self.save_plots_checkbox.grid(row=3, column=0, sticky='w', pady=4)
        self.save_kerr_entry = tk.BooleanVar(value=False)
        self.save_kerr_checkbox = ttk.Checkbutton(
            self.plot_config_frame,
            text='Save Kerr plot?',
            variable=self.save_kerr_entry,
            onvalue=True,
            offvalue=False,
        )
        self.save_kerr_checkbox.grid(row=3, column=1, sticky='w', pady=4)
        self.status_label = ttk.Label(self.plot_config_frame, text='Ready', wraplength=470)
        self.status_label.grid(row=4, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.right_panel.rowconfigure(2, weight=0)
        self.right_panel.rowconfigure(3, weight=1)
        self.log_frame.grid(row=3, column=0, sticky='nsew', pady=(6, 0))
        self.log_text.configure(height=6)
        self.analysis_frame = ttk.LabelFrame(
            self.right_panel, text='LOOP ANALYSIS', style='Card.TLabelframe', padding=(10, 6)
        )
        self.analysis_frame.grid(row=2, column=0, sticky='ew', pady=(0, 6))
        for col in (1, 3, 5):
            self.analysis_frame.columnconfigure(col, weight=1)
        self._analysis_vars = {}
        readout_defs = [
            (0, 0, 'hc', 'Hc:'),
            (0, 2, 'loop_center', 'Loop center:'),
            (0, 4, 'squareness', 'Mr / Ms:'),
            (1, 0, 'crossings', 'H+ / H-:'),
            (1, 2, 'amplitude', 'MOKE amp:'),
            (1, 4, 'source', 'Field source:'),
        ]
        for r, c, key, label_text in readout_defs:
            ttk.Label(self.analysis_frame, text=label_text).grid(row=r, column=c, sticky='w', padx=(0, 6), pady=3)
            var = tk.StringVar(value='—')
            box = tk.Label(
                self.analysis_frame,
                textvariable=var,
                bg='#1B2026',
                fg='#F3F6FA',
                relief='sunken',
                bd=1,
                font=('Consolas', 10, 'bold'),
                anchor='center',
                padx=8,
                pady=3,
                width=18,
            )
            box.grid(row=r, column=c + 1, sticky='ew', padx=(0, 14 if c < 4 else 0), pady=3)
            self._analysis_vars[key] = var
        self.analysis_note_var = tk.StringVar(value='Waiting for completed loop')
        ttk.Label(
            self.analysis_frame,
            textvariable=self.analysis_note_var,
            foreground='#B9C6D1',
        ).grid(row=2, column=0, columnspan=6, sticky='w', pady=(4, 0))
        self.control_frame = ttk.Frame(self.right_panel)
        self.control_frame.grid(row=1, column=0, pady=10)
        self.pause_button = ttk.Button(self.control_frame, text='PAUSE', command=self.toggle_pause)
        self.pause_button.pack(side='left', padx=5)
        self.stop_button = ttk.Button(self.control_frame, text='STOP', command=self.stop_measurement)
        self.stop_button.pack(side='left', padx=5)
        self.control_frame.grid_remove()
        self.paused = False
        self._update_gaussmeter()
        self._poll_id = self.root.after(100, self._poll)

    def _input(self, parent, label, value, options=None, row=0):
        ttk.Label(parent, text=label + ':').grid(row=row, column=0, sticky='w')
        widget = (ttk.Combobox(parent, values=options, state='readonly', width=24)
                  if options is not None else ttk.Entry(parent, width=26))
        widget.grid(row=row, column=1, sticky='ew', pady=2)
        if options is not None:
            widget.set(value)
        else:
            widget.insert(0, value)
        self.inputs[label] = widget

    def update_dynamic_inputs(self, event=None):
        if not hasattr(self, 'inputs') or 'Mode' not in self.inputs:
            return
        self._cache_dynamic_inputs()
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()
        for key in list(self.inputs):
            if key not in ('Geometry', 'Mode', 'Display', 'X-axis', 'Y-axis'):
                self.inputs.pop(key, None)
        mode = self.inputs['Mode'].get()
        self.dynamic_frame.configure(text='CONTINUOUS INPUTS' if mode == 'continuous' else 'STEPPED INPUTS')
        if mode == 'continuous':
            fields = [
                ('Field amplitude (Oe)', '1000'),
                ('Cycle period (s)', '0.2'),
                ('Cycles to average', '10'),
                ('Discard initial cycles', '1'),
                ('Points per cycle / average', '200'),
                ('Input sample rate (Hz)', '10000'),
                ('Initial endpoint hold (s)', '0'),
            ]
        else:
            fields = [
                ('Field amplitude (Oe)', '1000'),
                ('Cycles to average', '10'),
                ('Discard initial cycles', '1'),
                ('Points per cycle / average', '200'),
                ('Point dwell (s)', '0.001'),
                ('Initial endpoint hold (s)', '0'),
            ]
            if self.use_gaussmeter.get():
                fields.extend([
                    ('Field tolerance (Oe, optional)', ''),
                    ('Settling timeout (s)', '10'),
                ])
        for row, (label, default) in enumerate(fields):
            self._input(self.dynamic_frame, label, default, row=row)
        self._apply_saved_dynamic()
        if self._worker is not None:
            for key, widget in self.inputs.items():
                if key not in ('Display', 'X-axis', 'Y-axis'):
                    widget.state(['disabled'])

    def _update_gaussmeter(self):
        enabled = self.use_gaussmeter.get() and self._worker is None
        self.instrument_address_entries['gaussmeter'].state(['!disabled' if enabled else 'disabled'])
        if hasattr(self, 'inputs'):
            self.update_dynamic_inputs()
            self._update_geometries()

    def _missing_daq_channels(self, geometry):
        profile = self.connection_setup['profiles'][geometry]
        return [DAQ_CHANNELS[role] for role in self._active_roles()
                if self.instrument_address_entries[role].get() == DAQ_ADDRESS
                and profile.get(DAQ_CHANNELS[role]) in (None, '')]

    def _update_geometries(self):
        if self._worker is not None:
            return
        selector = self.inputs['Geometry']
        available = tuple(g for g in GEOMETRIES if not self._missing_daq_channels(g))
        selector['values'] = available
        selector.state(['!disabled' if available else 'disabled'])
        self.run_button.state(['!disabled' if selector.get() in available else 'disabled'])
        missing = ', '.join(g.title() for g in GEOMETRIES if g not in available)
        if missing:
            self.geometry_note.configure(
                text=f'Unavailable with current DAQ wiring: {missing}. Edit under Connection Setup > DAQ channels.')
            self.geometry_note.grid()
        else:
            self.geometry_note.grid_remove()

    def _active_roles(self):
        return ('field_controller', 'dmm') + (('gaussmeter',) if self.use_gaussmeter.get() else ())

    def autodetect_instruments(self):
        if self._worker is not None:
            return
        original = self.instrument_address_entries
        try:
            self.instrument_address_entries = {name: original[name] for name in self._active_roles()
                                              if original[name].get() not in (DAQ_ADDRESS, SOURCE_ADDRESS)}
            super().autodetect_instruments()
        finally:
            self.instrument_address_entries = original
        if any(original[name].get() == DAQ_ADDRESS for name in self._active_roles()):
            self._discover_daq()
        if original['field_controller'].get() == SOURCE_ADDRESS:
            self._discover_source()
        self._update_geometries()

    def _discover_daq(self, target=None):
        device = None
        try:
            board = int(target.get() if target is not None else self.connection_setup['board'])
            device = _open_mcc_driver(Daq, board)
            print(f'Detected shared DAQ: {device.idn()} (board {device.board_num})')
        except Exception as error:
            messagebox.showerror('DAQ discovery', str(error), parent=self.root)
        finally:
            _safe_close(device)

    def open_connection_setup(self):
        if self._worker is not None:
            return
        if self._setup_window is not None and self._setup_window.winfo_exists():
            self._setup_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._setup_window = window
        window.title('MOKE Connection Setup')
        window.transient(self.root)
        window.grab_set()
        self.style.configure('MOKE.TNotebook', background='#181818', borderwidth=0)
        self.style.configure('MOKE.TNotebook.Tab', background='#333F49', foreground='#F3F6FA',
                             padding=(14, 9), font=('Helvetica', 12, 'bold'))
        self.style.map('MOKE.TNotebook.Tab',
                       background=[('selected', '#285477'), ('active', '#405668')],
                       foreground=[('selected', '#FFFFFF'), ('active', '#FFFFFF')])
        notebook = ttk.Notebook(window, style='MOKE.TNotebook')
        notebook.pack(fill='both', expand=True)
        frame = ttk.Frame(notebook, style='Card.TFrame', padding=15)
        notebook.add(frame, text='Connections')
        daq_frame = ttk.Frame(notebook, style='Card.TFrame', padding=15)
        notebook.add(daq_frame, text='DAQ channels')
        source_frame = ttk.Frame(notebook, style='Card.TFrame', padding=15)
        notebook.add(source_frame, text='Source settings')
        source_widgets = {}
        definitions = [
            ('category', 'PIEC source category', ('sourcemeter', 'dc_calibrator')),
            ('address', 'Source address', ('VIRTUAL', *self.get_visa_resources())),
            ('mode', 'Output mode', ('current', 'voltage')),
            ('channel', 'Sourcemeter channel', None),
            ('gain', 'Calibration (Oe/A or Oe/V)', None), ('offset', 'Field offset (Oe)', None),
            ('minimum', 'Minimum source output (A or V)', None),
            ('maximum', 'Maximum source output (A or V)', None),
            ('compliance', 'SMU compliance (V in current mode; A in voltage mode)', None)]
        source_settings = {**DEFAULT_SOURCE, **self.connection_setup.get('source', {})}
        for row, (key, label, options) in enumerate(definitions):
            ttk.Label(source_frame, text=label).grid(row=row, column=0, sticky='w', pady=3)
            widget = (ttk.Combobox(source_frame, values=options, state='normal' if key == 'address' else 'readonly')
                      if options else ttk.Entry(source_frame))
            if options:
                widget.set(str(source_settings[key]))
            else:
                widget.insert(0, str(source_settings[key]))
            widget.grid(row=row, column=1, sticky='ew', pady=3)
            source_widgets[key] = widget
        ttk.Button(source_frame, text='DISCOVER SOURCE',
                   command=lambda: self._discover_source(source_widgets)).grid(row=9, column=1, pady=8)
        ttk.Label(source_frame, text='Used when Field controller is set to Current or voltage source.').grid(
            row=10, column=0, columnspan=2, sticky='w', pady=8)
        connection_choices = {'Instrument address': None, 'Shared DAQ channel': DAQ_ADDRESS,
                              'Current or voltage source': SOURCE_ADDRESS}
        role_labels = {'field_controller': 'Field controller', 'dmm': 'Optical signal (DMM)',
                       'gaussmeter': 'Field monitor (optional)'}
        backends = {}
        for row, name in enumerate(self._instruments):
            ttk.Label(frame, text=role_labels[name]).grid(row=row, column=0, sticky='w', padx=(0, 14))
            options = tuple(connection_choices) if name == 'field_controller' else tuple(connection_choices)[:2]
            widget = ttk.Combobox(frame, values=options, width=26, state='readonly')
            selected = self.instrument_address_entries[name].get()
            widget.set(next((label for label in options if connection_choices[label] == selected),
                            'Instrument address'))
            widget.grid(row=row, column=1, sticky='ew', pady=5)
            backends[name] = widget
        ttk.Label(frame, text='Instrument address uses the address selected on the main window, including VIRTUAL.\n'
                  'Shared DAQ channel uses the wiring for the selected geometry under DAQ channels.\n'
                  'Current or voltage source uses the instrument and calibration under Source settings.').grid(
                      row=3, column=0, columnspan=2, sticky='w', pady=(14, 0))
        ttk.Label(daq_frame, text='Shared DAQ: MCC board number (e.g. USB-1208HS, USB-231)').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(12, 3))
        board = ttk.Entry(daq_frame)
        board.insert(0, self.connection_setup['board'])
        board.grid(row=1, column=0, sticky='ew')
        ttk.Button(daq_frame, text='DISCOVER DAQ', command=lambda: self._discover_daq(board)).grid(row=1, column=1)
        ttk.Label(daq_frame, text='Analog input mode').grid(row=2, column=0, sticky='w', pady=(8, 0))
        ai_mode = ttk.Combobox(daq_frame, values=DAQ_AI_MODES, state='readonly', width=10)
        ai_mode.set(self.connection_setup['ai_mode'])
        ai_mode.grid(row=2, column=1, sticky='w', pady=(8, 0))
        ttk.Label(daq_frame, text='AO sample rate (Hz)').grid(row=3, column=0, sticky='w', pady=(6, 0))
        ao_rate = ttk.Entry(daq_frame, width=12)
        ao_rate.insert(0, str(self.connection_setup.get('ao_sample_rate', 1000.0)))
        ao_rate.grid(row=3, column=1, sticky='w', pady=(6, 0))
        ttk.Label(daq_frame, text='Select the photodiode and field monitor inputs for each geometry.').grid(
            row=4, column=0, columnspan=2, sticky='w', pady=(12, 3))
        table = ttk.Frame(daq_frame, style='Card.TFrame')
        table.grid(row=5, column=0, columnspan=3, sticky='ew')
        keys = ('output', 'signal_input', 'field_input', 'command_gain', 'command_offset',
                'monitor_gain', 'monitor_offset')
        input_keys = ('signal_input', 'field_input')
        labels = ('Geometry', 'Magnet\nAO', 'Photodiode\nAI', 'Field monitor\nAI', 'Command\nOe/V', 'Command\noffset Oe',
                  'Monitor\nOe/V', 'Monitor\noffset Oe')
        for col, label in enumerate(labels):
            ttk.Label(table, text=label).grid(row=0, column=col, padx=3)
        entries = {}
        input_choices = DAQ_AI_CHOICES[ai_mode.get()]
        for row, geometry in enumerate(GEOMETRIES, 1):
            ttk.Label(table, text=geometry.title()).grid(row=row, column=0, sticky='w')
            entries[geometry] = {}
            for col, key in enumerate(keys, 1):
                value = self.connection_setup['profiles'][geometry][key]
                if key in input_keys:
                    widget = ttk.Combobox(table, values=input_choices, state='readonly', width=21)
                    selection = value + 1 if value is not None else 0
                    widget.current(selection if 0 <= selection < len(input_choices) else 0)
                else:
                    widget = ttk.Entry(table, width=11)
                    widget.insert(0, '' if value is None else str(value))
                widget.grid(row=row, column=col, padx=3, pady=3)
                entries[geometry][key] = widget

        def update_ai_choices(event):
            choices = DAQ_AI_CHOICES[ai_mode.get()]
            for widgets in entries.values():
                for key in input_keys:
                    widget = widgets[key]
                    selection = widget.current()
                    widget.configure(values=choices)
                    widget.current(selection if 0 <= selection < len(choices) else 0)

        ai_mode.bind('<<ComboboxSelected>>', update_ai_choices)
        ttk.Label(daq_frame, text='A geometry becomes available once all channels needed by the selected DAQ roles are assigned.').grid(row=6, column=0, columnspan=3, pady=10)
        def apply():
            try:
                board_number = int(board.get())
                if board_number < 0:
                    raise ValueError('MCC board number must be nonnegative')
                ao_sample_rate = float(ao_rate.get())
                if not math.isfinite(ao_sample_rate) or ao_sample_rate <= 0:
                    raise ValueError('DAQ AO sample rate must be positive and finite')
                profiles = {}
                for geometry, widgets in entries.items():
                    profile = {}
                    for key, widget in widgets.items():
                        if key in input_keys:
                            selection = widget.current()
                            profile[key] = selection - 1 if selection > 0 else None
                        else:
                            text = widget.get().strip()
                            profile[key] = (int(text) if text else None) if key == 'output' else float(text)
                    if profile['output'] is not None and profile['output'] < 0:
                        raise ValueError('Output channel numbers must be nonnegative')
                    if (not all(math.isfinite(profile[key]) for key in keys[3:])
                            or profile['command_gain'] == 0 or profile['monitor_gain'] == 0):
                        raise ValueError('DAQ calibrations require finite offsets and nonzero gains')
                    profiles[geometry] = profile
                source = {key: widget.get().strip() for key, widget in source_widgets.items()}
                source['channel'] = int(source['channel'])
                for key in ('gain', 'offset', 'minimum', 'maximum', 'compliance'):
                    source[key] = float(source[key])
                if not source['minimum'] < source['maximum'] or source['channel'] < 1:
                    raise ValueError('Require increasing source limits and a positive channel')
                if (not all(math.isfinite(source[k]) for k in ('gain', 'offset', 'minimum', 'maximum', 'compliance'))
                        or source['gain'] == 0):
                    raise ValueError('Require finite source settings and nonzero calibration gain')
                if source['category'] == 'sourcemeter' and source['compliance'] <= 0:
                    raise ValueError('Sourcemeter compliance must be positive')
                for name, widget in backends.items():
                    selector = self.instrument_address_entries[name]
                    backend = connection_choices[widget.get()]
                    if backend is not None:
                        selector.set(backend)
                    elif selector.get() in (DAQ_ADDRESS, SOURCE_ADDRESS):
                        selector.set('VIRTUAL')
                self.connection_setup = {'board': str(board_number), 'ai_mode': ai_mode.get(),
                                         'ao_sample_rate': ao_sample_rate,
                                         'profiles': profiles, 'source': source}
            except Exception as error:
                messagebox.showerror('Invalid connection setup', str(error), parent=window)
                return
            self._update_geometries()
            window.destroy()
        actions = ttk.Frame(window, padding=10)
        actions.pack(fill='x')
        ttk.Button(actions, text='APPLY', command=apply).pack(side='right', padx=5)
        ttk.Button(actions, text='CANCEL', command=window.destroy).pack(side='right', padx=5)

    def _discover_source(self, widgets=None):
        settings = self.connection_setup.get('source', DEFAULT_SOURCE)
        category = widgets['category'].get() if widgets else settings['category']
        device = None
        try:
            device = autodetect(address=category, required_type=_resolve_type_string(category))
            if device is None:
                raise ConnectionError('No matching source detected')
            address = device.instrument.resource_name
            if widgets:
                widgets['address'].set(address)
            else:
                self.connection_setup.setdefault('source', dict(DEFAULT_SOURCE))['address'] = address
            print(f'Detected source: {device.idn()} at {address}')
        except Exception as error:
            messagebox.showerror('Source discovery', str(error), parent=self.root)
        finally:
            _safe_close(device)

    def save_settings(self):
        if not super().save_settings():
            return False
        try:
            path = Path(self.get_settings_file_path())
            settings = json.loads(path.read_text(encoding='utf-8'))
            settings['moke_connection'] = self.connection_setup
            path.write_text(json.dumps(settings, indent=4), encoding='utf-8')
            return True
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror('Save settings', str(error), parent=self.root)
            return False

    def load_settings(self):
        try:
            path = self.get_settings_file_path()
            if path and Path(path).exists():
                settings = json.loads(Path(path).read_text(encoding='utf-8'))
                setup = settings.get('moke_connection')
                if setup is not None:
                    if not isinstance(setup, dict) or not all(
                            isinstance(setup.get('profiles', {}).get(g), dict) for g in GEOMETRIES):
                        raise ValueError('Invalid saved MOKE connection setup')
                    setup.setdefault('source', dict(DEFAULT_SOURCE))
                    setup.setdefault('ao_sample_rate', 1000.0)
                    if setup.setdefault('ai_mode', DEFAULT_DAQ_AI_MODE) not in DAQ_AI_MODES:
                        raise ValueError('Invalid saved DAQ analog input mode')
                    self.connection_setup = setup
        except (OSError, ValueError, TypeError) as error:
            print(f'Could not load MOKE connection setup: {error}')
        super().load_settings()
        if self.inputs.get('Display') is not None and self.inputs['Display'].get() == 'Latest cycle':
            self.inputs['Display'].set('Most recent cycle')
        self._update_gaussmeter()

    def close_instruments(self):
        try:
            super().close_instruments()
        finally:
            try:
                if self._owned_source is not None:
                    source, self._owned_source = self._owned_source, None
                    output, self._source_output = self._source_output, None
                    try:
                        if output is not None:
                            output(on=False)
                    finally:
                        source.close()
            finally:
                if self._owned_daq is not None:
                    device, self._owned_daq = self._owned_daq, None
                    device.close()

    def _connect_roles(self, roles, profile):
        """Use the base class for direct connections; adapt one shared DAQ."""
        self.close_instruments()
        try:
            if any(self.instrument_address_entries[name].get() == DAQ_ADDRESS for name in roles):
                self._owned_daq = _open_mcc_driver(Daq, int(self.connection_setup['board']))
                self._owned_daq.set_input_mode(self.connection_setup['ai_mode'])
            for name in roles:
                if name == 'field_controller' and self.instrument_address_entries[name].get() == SOURCE_ADDRESS:
                    settings = self.connection_setup['source']
                    address = settings['address']
                    if address.upper() == 'VIRTUAL':
                        address = 'VIRTUAL_' + settings['category']
                    self._owned_source = autodetect(address=address,
                                                     required_type=_resolve_type_string(settings['category']))
                    if self._owned_source is None:
                        raise ConnectionError('Could not connect to the selected source')
                    source = self._owned_source
                    channel, mode = settings['channel'], settings['mode']
                    if settings['category'] == 'sourcemeter':
                        if channel not in source.channel:
                            raise ValueError('Unavailable source channel')
                        if not math.isfinite(settings['compliance']) or settings['compliance'] <= 0:
                            raise ValueError('Sourcemeter compliance must be positive and finite')
                        if mode == 'current':
                            def setter(value):
                                source.set_source_current(channel=channel, current=value)
                        else:
                            def setter(value):
                                source.set_source_voltage(channel=channel, voltage=value)
                    else:
                        setter = partial(source.set_output, mode=mode)
                    self.instruments[name] = SourceAsFieldController(
                        source, setter, settings['gain'], (settings['minimum'], settings['maximum']),
                        offset=settings['offset'])
                elif self.instrument_address_entries[name].get() != DAQ_ADDRESS:
                    self.instruments[name] = super().connect_instrument(name)
                elif name == 'field_controller':
                    self.instruments[name] = DaqFieldController(
                        self._owned_daq, profile['output'], profile['command_gain'], profile['command_offset'],
                        ao_sample_rate=float(self.connection_setup.get('ao_sample_rate', 1000.0)))
                elif name == 'dmm':
                    self.instruments[name] = DaqAsDMM(self._owned_daq, profile['signal_input'])
                else:
                    self.instruments[name] = DaqAsGaussmeter(
                        self._owned_daq, profile['field_input'], profile['monitor_gain'], profile['monitor_offset'])
            return self.instruments
        except Exception:
            self.close_instruments()
            raise

    def _configure_acquisition(self, instruments):
        field, dmm = instruments['field_controller'], instruments['dmm']
        if isinstance(field, VirtualFieldController):
            sample = ArctanMOKE()
            field.mag_sample = sample
            if isinstance(dmm, VirtualDMM):
                dmm.set_voltage_reader(sample.get_moke_voltage)

    def run_measurement(self):
        if self._worker is not None:
            return
        try:
            values = {key: widget.get() for key, widget in self.inputs.items()}
            amplitude = float(values['Field amplitude (Oe)'])
            if amplitude <= 0:
                raise ValueError('Field amplitude must be positive')
            roles = self._active_roles()
            profile = self.connection_setup['profiles'][values['Geometry']]
            if self._missing_daq_channels(values['Geometry']):
                self._update_geometries()
                self.status_label.configure(text='Assign the missing channels in Connection Setup.')
                return
            if (self.instrument_address_entries['dmm'].get() == DAQ_ADDRESS
                    and 'gaussmeter' in roles
                    and self.instrument_address_entries['gaussmeter'].get() == DAQ_ADDRESS
                    and profile['signal_input'] == profile['field_input']):
                raise ValueError('Optical signal and field monitor require different inputs')
            mode = values['Mode']
            settings = dict(geometry=values['Geometry'], field_min=-amplitude, field_max=amplitude,
                            cycle_period=float(values.get('Cycle period (s)', 0.2)),
                            cycles=int(values['Cycles to average']),
                            discard_cycles=int(values['Discard initial cycles']),
                            points_per_cycle=int(values['Points per cycle / average']),
                            sample_rate=float(values.get('Input sample rate (Hz)', 10000)),
                            mode=mode,
                            dwell_time=float(values.get('Point dwell (s)', 0.001)),
                            initial_hold=float(values['Initial endpoint hold (s)']),
                            field_tolerance=(float(values['Field tolerance (Oe, optional)'])
                                             if self.use_gaussmeter.get() and mode == 'stepped'
                                             and values.get('Field tolerance (Oe, optional)', '').strip() else None),
                            settle_timeout=float(values.get('Settling timeout (s)', 10)),
                            save_dir=self.save_dir_entry.get(), on_update=self._queue_update)
            instruments = self._connect_roles(roles, profile)
            self._configure_acquisition(instruments)
            self.experiment = MOKE(instruments['field_controller'], instruments['dmm'],
                                   gaussmeter=instruments.get('gaussmeter'),
                                   **settings)
            if self._owned_daq is not None:
                self.experiment.daq_profile = dict(profile, ai_mode=self.connection_setup['ai_mode'])
            if self._owned_source is not None:
                self.experiment.source_settings = dict(self.connection_setup['source'])
        except Exception as error:
            self.close_instruments()
            self.experiment = None
            messagebox.showerror('MOKE configuration', str(error), parent=self.root)
            return
        self._last_update = None
        self._reset_analysis_readout('Waiting for completed loop')
        self.paused = False
        self.pause_button.configure(text='PAUSE')
        self.pause_button.state(['!disabled'])
        self.stop_button.state(['!disabled'])
        self.run_button.grid_remove()
        self.control_frame.grid()
        self._set_editing(False)
        self.status_label.configure(text='Running')
        self._worker = threading.Thread(target=self._acquire, daemon=False)
        self._worker.start()

    def _set_editing(self, enabled):
        state = ['!disabled' if enabled else 'disabled']
        for key, widget in self.inputs.items():
            if key not in ('Display', 'X-axis', 'Y-axis'):
                widget.state(state)
        for widget in self.instrument_address_entries.values():
            widget.state(state)
        self.setup_button.state(state)
        self.gaussmeter_toggle.state(state)
        if enabled:
            self._update_gaussmeter()

    def toggle_pause(self):
        if self._worker is None or self.experiment is None:
            return
        self.paused = not self.paused
        if self.paused:
            self.experiment.request_pause()
            self.status_label.configure(text='Pause requested; waiting for acquisition boundary')
        else:
            self.experiment.request_resume()
            self.status_label.configure(text='Running')
        self.pause_button.configure(text='RESUME' if self.paused else 'PAUSE')

    def _configure_source(self):
        source = self._owned_source
        settings = self.connection_setup['source']
        channel, mode = settings['channel'], settings['mode']
        if settings['category'] == 'sourcemeter':
            self._source_output = partial(source.output, channel=channel)
            self._source_output(on=False)
            if mode == 'current':
                source.configure_current_source(channel=channel, current=0.0,
                                                voltage_compliance=settings['compliance'])
            else:
                source.configure_voltage_source(channel=channel, voltage=0.0,
                                                current_compliance=settings['compliance'])
        else:
            self._source_output = source.output
            self._source_output(on=False)
        self.experiment.field_controller.set_field(0.0)
        self._source_output(on=True)

    def _acquire(self):
        try:
            if self._owned_source is not None:
                self._configure_source()
            self.experiment.run_experiment()
            self._events.put(('done', f'{self.experiment.status}: {self.experiment.filename or "no data"}'))
        except Exception as error:
            self._events.put(('error', str(error)))
        finally:
            try:
                self.close_instruments()
            except Exception as error:
                self._events.put(('error', f'Connection close failed: {error}'))
            self._events.put(('finished', None))

    def _queue_update(self, update):
        try:
            self._updates.get_nowait()
        except queue.Empty:
            pass
        self._updates.put_nowait(update)

    def stop_measurement(self):
        if self._worker is not None:
            if self.experiment is not None:
                self.experiment.request_stop()
            self.status_label.configure(text='Stopping; saving acquired data and zeroing field…')

    def _poll(self):
        try:
            self._last_update = self._updates.get_nowait()
            self._draw()
            if self._last_update.get('status') == 'paused' and self.paused:
                self.status_label.configure(text='Paused')
        except queue.Empty:
            pass
        while True:
            try:
                kind, message = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.console.write(message)
            elif kind == 'finished':
                self._worker = None
                self.control_frame.grid_remove()
                self.run_button.grid()
                self.run_button.state(['!disabled'])
                self._set_editing(True)
                # Experiment output is already zeroed and the owned DAQ closed.
                # Base on_closing must not attempt another I/O on that device.
                self.experiment = None
                if self._closing:
                    self._finish_close()
                    return
            else:
                if kind == 'done' and self.experiment and self.experiment.filename:
                    try:
                        self._last_update = self._updates.get_nowait()
                        self._draw()
                    except queue.Empty:
                        pass
                    if self.saveplots_entry.get():
                        plot_path = Path(self.experiment.filename).with_suffix('.png')
                        self.fig.savefig(plot_path, dpi=300, bbox_inches='tight')
                        self.console.write(f'Saved plot: {plot_path}\n')
                    if self.save_kerr_entry.get():
                        loop_df = None
                        if self._last_update:
                            if (self._last_update.get('cycles', 0) >= 1
                                    and not self._last_update.get('average', pd.DataFrame()).empty):
                                loop_df = self._last_update['average']
                            elif self._last_update.get('has_completed_latest', False):
                                loop_df = self._last_update.get('latest')
                        if loop_df is not None and not loop_df.empty:
                            geom = self.inputs['Geometry'].get()
                            colors = {'polar': '#1f4e78', 'longitudinal': '#b83b3b', 'transverse': '#2e7d5b'}
                            kerr_path = str(Path(self.experiment.filename).with_suffix('')) + '_kerr.png'
                            analysis = analyze_moke_dataframe(loop_df, field_source=self.experiment.field_source)
                            plot_moke_loop(
                                loop_df['field (Oe)'].to_numpy(),
                                loop_df['signal (V)'].to_numpy(),
                                analysis=analysis,
                                title=f'{geom.capitalize()} MOKE',
                                color=colors.get(geom, '#1f4e78'),
                                save_path=kerr_path,
                                show=False,
                            )
                            self.console.write(f'Saved Kerr plot: {kerr_path}\n')
                        else:
                            self.console.write('Skipped Kerr plot: no completed loop acquired\n')
                short_status = (
                    f'{self.experiment.status}: {Path(self.experiment.filename).name}'
                    if kind == 'done' and self.experiment and self.experiment.filename
                    else message
                )
                self.status_label.configure(text=short_status)
                self.console.write(message + '\n')
                if kind == 'error':
                    messagebox.showerror('MOKE acquisition failed', message, parent=self.root)
        self._poll_id = self.root.after(60, self._poll)

    def _on_display_change(self, event=None):
        choice = self.inputs['Display'].get()
        x_widget = self.inputs.get('X-axis')
        if x_widget is not None:
            if choice == 'Live signal' and x_widget.get() == 'field (Oe)':
                x_widget.set('time (s)')
            elif choice != 'Live signal' and x_widget.get() == 'time (s)':
                x_widget.set('field (Oe)')
        self._draw()

    def _draw(self):
        if self._last_update is None:
            return
        choice = self.inputs['Display'].get()
        key = {
            'Cycle average': 'average',
            'Most recent cycle': 'latest',
            'Latest cycle': 'latest',
            'Live signal': 'live',
        }.get(choice, 'average')
        frame = self._last_update.get(key, pd.DataFrame())
        x_col = self.inputs['X-axis'].get()
        y_col = self.inputs['Y-axis'].get()
        mode_sig = (choice, x_col, y_col)
        title_text = f"{choice}: {y_col} vs {x_col} ({self._last_update['cycles']} averaged cycles)"
        if getattr(self, '_plot_sig', None) != mode_sig or not hasattr(self, '_trace_line'):
            self.ax.clear()
            self.ax.grid(True, linestyle='--', alpha=0.3)
            self.ax.set_xlabel(x_col)
            self.ax.set_ylabel(y_col)
            self._title_artist = self.ax.set_title(title_text)
            (self._trace_line,) = self.ax.plot([], [], color='#4DA6FF', linewidth=1.8)
            self._plot_sig = mode_sig
            self.fig.set_tight_layout(True)
        else:
            self._title_artist.set_text(title_text)
        if not frame.empty and x_col in frame.columns and y_col in frame.columns:
            x = frame[x_col].to_numpy()
            y = frame[y_col].to_numpy()
            # Close the loop visually when plotting a single/averaged cycle against field
            if key != 'live' and 'field' in x_col and len(x) > 2:
                x = np.append(x, x[0])
                y = np.append(y, y[0])
            self._trace_line.set_data(x, y)
            self.ax.relim()
            self.ax.autoscale_view()
        else:
            self._trace_line.set_data([], [])
        self.canvas.draw()
        self.fig.set_tight_layout(False)
        self._update_analysis_readout(choice)

    def _reset_analysis_readout(self, note):
        for var in self._analysis_vars.values():
            var.set('—')
        self.analysis_note_var.set(note)

    def _update_analysis_readout(self, choice):
        if self._last_update is None:
            return
        if choice == 'Cycle average':
            if self._last_update.get('cycles', 0) < 1:
                self._reset_analysis_readout('Cycle average: waiting for first included cycle')
                return
            frame = self._last_update.get('average', pd.DataFrame())
            scope = f"Cycle average ({self._last_update['cycles']} cycles)"
        elif choice in ('Most recent cycle', 'Latest cycle'):
            if not self._last_update.get('has_completed_latest', False):
                self._reset_analysis_readout('Latest loop: waiting for completed loop')
                return
            frame = self._last_update.get('latest', pd.DataFrame())
            scope = 'Latest completed loop'
        else:
            return

        if frame is None or frame.empty:
            self._reset_analysis_readout(f'{scope}: no data')
            return

        result = analyze_moke_dataframe(frame, field_source=self._last_update.get('field_source'))
        reasons = result['reasons']
        self._analysis_vars['hc'].set(f"{result['hc_oe']:.2f} Oe" if result['hc_oe'] is not None else 'N/A')
        self._analysis_vars['loop_center'].set(
            f"{result['loop_center_oe']:.2f} Oe" if result['loop_center_oe'] is not None else 'N/A'
        )
        self._analysis_vars['squareness'].set(
            f"{result['squareness']:.3f}" if result['squareness'] is not None else 'N/A'
        )
        if result['h_increasing_oe'] is not None and result['h_decreasing_oe'] is not None:
            self._analysis_vars['crossings'].set(
                f"{result['h_increasing_oe']:.1f} / {result['h_decreasing_oe']:.1f} Oe"
            )
        else:
            self._analysis_vars['crossings'].set('N/A')
        self._analysis_vars['amplitude'].set(
            f"{result['amplitude_v'] * 1e3:.2f} mV" if result['amplitude_v'] is not None else 'N/A'
        )
        self._analysis_vars['source'].set('Commanded' if result['uses_commanded_field'] else 'Measured')

        unique_reasons = list(dict.fromkeys(reasons.values()))
        if unique_reasons:
            self.analysis_note_var.set(f"{scope} — {unique_reasons[0]}")
        else:
            self.analysis_note_var.set(scope)

    def on_closing(self):
        if self._worker is not None:
            self._closing = True
            self.stop_measurement()
            return
        if hasattr(self, '_poll_id'):
            self.root.after_cancel(self._poll_id)
        self._finish_close()

    def _finish_close(self):
        self._closing = False
        super().on_closing()
        # The base class leaves the window open when saving settings fails.
        # Resume polling so a later acquisition still receives updates.
        try:
            if self.root.winfo_exists():
                self._poll_id = self.root.after(100, self._poll)
        except tk.TclError:
            pass  # The root was successfully destroyed.


def main():
    root = tk.Tk()
    MOKEApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
