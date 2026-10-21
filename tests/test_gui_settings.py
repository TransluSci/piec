"""Exercise settings persistence with real Tk widgets and reopened windows."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

tk = pytest.importorskip('tkinter')


MEASUREMENTS = Path(__file__).resolve().parents[1] / 'Measurements'
GUI_CASES = [
    ('Ferroelectric Testing/FE_testing_GUI.py', 'FEMeasurementApp', {
        'address:awg': 'GPIB0::10::INSTR',
        'address:oscilloscope': 'GPIB0::11::INSTR',
        'vdiv_entry': '0.25', 'area_entry': '2.5e-8', 'timeshift_entry': '57',
        'auto_timeshift_entry': True, 'saveplots_entry': True,
        'x_axis': 'time (s)', 'y_axis': 'polarization (uC/cm^2)',
    }, {'frequency': '1234', 'amplitude': '2.75', 'offset': '-0.3', 'n_cycles': '7'}),
    ('AMR/amr_GUI.py', 'AMRApp', {
        'address:dmm': 'GPIB0::12::INSTR',
        'address:dc_calibrator': 'GPIB0::13::INSTR',
        'address:stepper_motor': 'ASRL4::INSTR',
        'address:lockin': 'GPIB0::14::INSTR',
        'initialize_lockin_var': False, 'x_axis': 'field', 'y_axis': 'Y',
    }, {'field': '250', 'angle_step': '17', 'total_angle': '180',
        'amplitude': '0.2', 'frequency': '37', 'measure_time': '2.5',
        'sensitivity': '100uv/pa'}),
    ('DCIV/IV_sweep_GUI.py', 'IVSweepApp', {
        'address:sourcemeter': 'GPIB0::15::INSTR', 'sense_mode_entry': '4W',
        'x_axis': 'current (A)', 'y_axis': 'voltage (V)',
    }, {'v_start': '-2', 'v_stop': '3', 'num_steps': '13',
        'current_compliance': '0.007', 'dwell_time': '0.35'}),
    ('Quickstart/quick_start_local_GUI.py', 'QuickstartApp', {
        'address:awg': 'GPIB0::16::INSTR',
        'address:oscilloscope': 'GPIB0::17::INSTR', 'auto_save_entry': False,
    }, {'waveform': 'RAMP', 'frequency': '4321', 'amplitude': '3.25', 'offset': '-0.2'}),
]
PUND_VALUES = {
    'reset_amp': '3.5', 'reset_width': '2e-6', 'reset_delay': '3e-6',
    'p_u_amp': '2.5', 'p_u_width': '4e-6', 'p_u_delay': '5e-6', 'offset': '0.7',
}


def get_input(app, name):
    if name.startswith('address:'):
        return app.instrument_address_entries[name.split(':', 1)[1]]
    return getattr(app, name)


def set_input(widget, value):
    if isinstance(widget, tk.Variable) or widget.winfo_class() == 'TCombobox':
        widget.set(value)
    else:
        widget.delete(0, tk.END)
        widget.insert(0, value)


@pytest.fixture
def open_gui(monkeypatch, tmp_path):
    try:
        probe = tk.Tk()
        probe.withdraw()
    except tk.TclError:
        pytest.skip('A desktop display is required for the real-widget GUI tests')

    from piec.measurement.gui_utils import MeasurementApp, messagebox
    import matplotlib.pyplot as plt

    # Discovery must not contact lab hardware during a settings test. Addresses
    # deliberately remain absent from the list, as when hardware is disconnected.
    monkeypatch.setattr(MeasurementApp, 'get_visa_resources', lambda self: [])
    monkeypatch.setattr(MeasurementApp, 'get_settings_file_path',
                        lambda self: str(tmp_path / f'{type(self).__name__}.json'))
    prompts = []
    monkeypatch.setattr(messagebox, 'askyesno', lambda *a, **k: prompts.append(a) or True)
    failures = []
    monkeypatch.setattr(messagebox, 'showerror', lambda *a, **k: failures.append(a))
    stdout, stderr = sys.stdout, sys.stderr
    windows = []
    modules = {}
    first_root = probe

    def create(case=GUI_CASES[0]):
        nonlocal first_root
        if isinstance(case, type):
            gui_class = case
        else:
            relative, name, _, _ = case
            gui_class = None
        if gui_class is None and name not in modules:
            # Two existing launchers apply Windows DPI awareness at import time.
            if sys.platform != 'win32' and name in ('AMRApp', 'IVSweepApp'):
                import ctypes
                from types import SimpleNamespace
                monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
                    shcore=SimpleNamespace(SetProcessDpiAwareness=lambda _: None)), raising=False)
            spec = importlib.util.spec_from_file_location(name, MEASUREMENTS / relative)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules[name] = module
        if gui_class is None:
            gui_class = getattr(modules[name], name)
        root = first_root if first_root is not None else tk.Tk()
        first_root = None
        root.deiconify()
        root.report_callback_exception = lambda *error: failures.append(error)
        app = gui_class(root)
        windows.append(app)
        # Let the inherited startup timer load settings, as it does in a real run.
        root.after(300, root.quit)
        root.mainloop()
        return app

    create.prompts = prompts
    create.failures = failures
    yield create
    if first_root is not None:
        first_root.destroy()
    for app in windows:
        try:
            if app.root.winfo_exists():
                app.root.after_cancel(app._load_settings_id)
                app.root.destroy()
        except tk.TclError:
            pass
        app.close_instruments()
        plt.close(app.fig)
    sys.stdout, sys.stderr = stdout, stderr


@pytest.mark.parametrize('case', GUI_CASES, ids=[case[1] for case in GUI_CASES])
def test_every_input_survives_close_and_reopen(open_gui, tmp_path, case):
    app = open_gui(case)
    assert app.save_dir_entry.get() == 'scratch'
    expected = dict(case[2], save_dir_entry=str(tmp_path / 'custom data directory'))
    for name, value in expected.items():
        assert get_input(app, name).get() != value
        set_input(get_input(app, name), value)
    is_fe = case[1] == 'FEMeasurementApp'
    if is_fe:
        app.select_measurement('HysteresisLoop')
    for name, value in case[3].items():
        assert app.dynamic_inputs[name].get() != value
        set_input(app.dynamic_inputs[name], value)
    if is_fe:
        app.select_measurement('ThreePulsePund')
        for name, value in PUND_VALUES.items():
            set_input(app.dynamic_inputs[name], value)
        app.select_measurement('HysteresisLoop')
        assert {name: widget.get() for name, widget in app.dynamic_inputs.items()} == case[3]
        app.select_measurement('ThreePulsePund')

    # Invoke the installed window-manager close handler, including its prompt.
    app.root.tk.call(app.root.protocol('WM_DELETE_WINDOW'))
    assert len(open_gui.prompts) == 1
    saved = json.loads((tmp_path / f'{case[1]}.json').read_text())
    assert saved['static']['Save Directory'] == expected['save_dir_entry']
    app = open_gui(case)
    for name, value in expected.items():
        assert get_input(app, name).get() == value, name
    if is_fe:
        assert app.measurement_type.get() == 'ThreePulsePund'
        assert {name: widget.get() for name, widget in app.dynamic_inputs.items()} == PUND_VALUES
        app.select_measurement('HysteresisLoop')
    assert {name: widget.get() for name, widget in app.dynamic_inputs.items()} == case[3]

    # Save again while the other FE panel is visible, retaining its cached peer.
    app.on_closing()
    app = open_gui(case)
    if is_fe:
        assert app.measurement_type.get() == 'HysteresisLoop'
        app.select_measurement('ThreePulsePund')
        assert {name: widget.get() for name, widget in app.dynamic_inputs.items()} == PUND_VALUES
    assert not open_gui.failures


def test_old_flat_dynamic_settings_are_restored(open_gui, tmp_path):
    (tmp_path / 'FEMeasurementApp.json').write_text(json.dumps({
        'static': {'Measurement Type': 'ThreePulsePund', 'AWG Address': 'GPIB0::9::INSTR'},
        'dynamic': {'Reset Amplitude (V)': '8.25'},
    }))
    app = open_gui()
    assert app.measurement_type.get() == 'ThreePulsePund'
    assert app.instrument_address_entries['awg'].get() == 'GPIB0::9::INSTR'
    assert app.dynamic_inputs['reset_amp'].get() == '8.25'
    assert not open_gui.failures


def test_declining_save_keeps_previous_settings(open_gui, monkeypatch, tmp_path):
    from piec.measurement.gui_utils import messagebox

    app = open_gui()
    app.save_settings()
    previous = (tmp_path / 'FEMeasurementApp.json').read_bytes()
    set_input(app.save_dir_entry, 'not saved')
    monkeypatch.setattr(messagebox, 'askyesno', lambda *a, **k: False)
    app.on_closing()
    assert (tmp_path / 'FEMeasurementApp.json').read_bytes() == previous


def test_save_failure_keeps_window_open(open_gui, monkeypatch, tmp_path):
    app = open_gui()
    monkeypatch.setattr(app, 'get_settings_file_path', lambda: str(tmp_path / 'missing' / 'settings.json'))
    app.on_closing()
    assert app.root.winfo_exists()
    assert len(open_gui.failures) == 1


def test_malformed_settings_leave_defaults(open_gui, tmp_path):
    (tmp_path / 'FEMeasurementApp.json').write_text('{bad json')
    app = open_gui()
    assert app.save_dir_entry.get() == 'scratch'
    assert not open_gui.failures


@pytest.mark.parametrize('case', GUI_CASES, ids=[case[1] for case in GUI_CASES])
def test_declared_instruments_connect_in_virtual_mode(open_gui, monkeypatch, case):
    from piec.drivers.virtual_instrument import VirtualInstrument
    from piec.drivers import instrument as driver_module

    def forbid_hardware(*args, **kwargs):
        raise AssertionError('Virtual GUI connections must not contact hardware')

    monkeypatch.setattr(driver_module, 'PiecManager', forbid_hardware)
    app = open_gui(case)
    instruments = app.connect_instruments()
    expected = {name.split(':', 1)[1] for name in case[2] if name.startswith('address:')}
    assert set(instruments) == expected
    assert all(isinstance(instrument, VirtualInstrument) for instrument in instruments.values())
    assert all(instrument.idn() for instrument in instruments.values())
    assert not open_gui.failures


def test_refresh_preserves_selected_addresses(open_gui, monkeypatch):
    app = open_gui()
    app.instrument_address_entries['awg'].set('GPIB0::42::INSTR')
    monkeypatch.setattr(app, 'get_visa_resources', lambda: ['GPIB0::9::INSTR'])
    app.refresh_instruments()
    awg = app.instrument_address_entries['awg']
    assert awg.get() == 'GPIB0::42::INSTR'
    assert set(awg['values']) == {'VIRTUAL', 'GPIB0::9::INSTR', 'GPIB0::42::INSTR'}
    assert app.instrument_address_entries['oscilloscope'].get() == 'VIRTUAL'


def test_autodetect_updates_matches_and_closes_probe_sessions(open_gui, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from piec.measurement import gui_utils

    app = open_gui()
    probe = SimpleNamespace(instrument=SimpleNamespace(resource_name='GPIB0::23::INSTR'), close=Mock())
    detector = Mock(side_effect=[probe, RuntimeError('not connected')])
    monkeypatch.setattr(gui_utils, 'autodetect', detector)
    monkeypatch.setattr(app, '_manual_driver', lambda name: None)
    app.instrument_address_entries['oscilloscope'].set('GPIB0::24::INSTR')
    app.autodetect_instruments()
    assert app.instrument_address_entries['awg'].get() == 'GPIB0::23::INSTR'
    assert app.instrument_address_entries['oscilloscope'].get() == 'GPIB0::24::INSTR'
    probe.close.assert_called_once_with()
    assert [call.kwargs['address'] for call in detector.call_args_list] == ['awg', 'oscilloscope']
    assert all(call.kwargs['required_type'] is app._instrument_types[call.kwargs['address']]
               for call in detector.call_args_list)


def test_failed_connection_closes_preceding_instruments(open_gui, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from piec.drivers.awg.awg import Awg
    from piec.measurement import gui_utils

    class FakeAwg(Awg):
        def __init__(self):
            self.instrument = SimpleNamespace(close=Mock())

    app = open_gui()
    app.instrument_address_entries['awg'].set('GPIB0::23::INSTR')
    app.instrument_address_entries['oscilloscope'].set('GPIB0::24::INSTR')
    awg = FakeAwg()
    detector = Mock(side_effect=[awg, None])
    monkeypatch.setattr(gui_utils, 'autodetect', detector)
    monkeypatch.setattr(app, '_manual_driver', lambda name: None)
    with pytest.raises(ConnectionError, match='oscilloscope'):
        app.connect_instruments(virtual_options={'awg': {'simulation_points': 10}})
    awg.instrument.close.assert_called_once_with()
    assert app.instruments == {}
    # Simulation-only options must never reach a physical resource constructor.
    assert 'simulation_points' not in detector.call_args_list[0].kwargs


def test_manual_only_stepper_keeps_explicit_address_support(open_gui, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from piec.drivers.stepper_motor.arduino_stepper import Geos_Stepper
    from piec.measurement import gui_utils

    app = open_gui(GUI_CASES[1])
    assert app._manual_driver('stepper_motor') is Geos_Stepper
    close = Mock()
    def fake_init(self, address, **options):
        self.instrument = SimpleNamespace(resource_name=address, close=close)
    monkeypatch.setattr(Geos_Stepper, '__init__', fake_init)
    detector = Mock(return_value=None)
    monkeypatch.setattr(gui_utils, 'autodetect', detector)
    app.instrument_address_entries['stepper_motor'].set('ASRL4::INSTR')
    stepper = app.connect_instrument('stepper_motor')
    assert stepper.instrument.resource_name == 'ASRL4::INSTR'
    detector.assert_not_called()
    gui_utils._safe_close(stepper)
    close.assert_called_once_with()
    app.autodetect_instruments()
    assert 'stepper_motor' not in [call.kwargs['address'] for call in detector.call_args_list]
    assert app.instrument_address_entries['stepper_motor'].get() == 'ASRL4::INSTR'


def test_quickstart_capture_uses_shared_virtual_connections(open_gui, tmp_path):
    import pandas as pd

    app = open_gui(GUI_CASES[3])
    set_input(app.save_dir_entry, str(tmp_path / 'capture'))
    app.run_measurement()
    files = list((tmp_path / 'capture').glob('*.csv'))
    assert len(files) == 1
    data = pd.read_csv(files[0])
    assert {'Time', 'Voltage'} <= set(data)
    assert not data.empty
    assert app.instruments == {}
    assert not open_gui.failures


def test_new_gui_only_needs_a_list_of_instrument_types(open_gui):
    from piec.measurement.gui_utils import MeasurementApp
    from piec.drivers.virtual_instrument import VirtualInstrument

    class NewApp(MeasurementApp):
        _instruments = ('pulser', 'rf_source')

    app = open_gui(NewApp)
    assert set(app.instrument_address_entries) == {'pulser', 'rf_source'}
    assert all(entry.get() == 'VIRTUAL' for entry in app.instrument_address_entries.values())
    instruments = app.connect_instruments()
    assert all(isinstance(instrument, VirtualInstrument) for instrument in instruments.values())
    assert set(instruments) == {'pulser', 'rf_source'}


def test_shutdown_resets_experiment_before_closing_connections(open_gui):
    from types import SimpleNamespace

    app = open_gui()
    events = []
    app.experiment = SimpleNamespace(safe_close=lambda: events.append('reset'))
    app.instruments['awg'] = SimpleNamespace(close=lambda: events.append('disconnect'))
    app.on_closing()
    assert events == ['reset', 'disconnect']
    assert app.instruments == {}
