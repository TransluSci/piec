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
        'awg_address_entry': 'GPIB0::10::INSTR',
        'osc_address_entry': 'GPIB0::11::INSTR',
        'vdiv_entry': '0.25', 'area_entry': '2.5e-8', 'timeshift_entry': '57',
        'auto_timeshift_entry': True, 'saveplots_entry': True,
        'x_axis': 'time (s)', 'y_axis': 'polarization (uC/cm^2)',
    }, {'frequency': '1234', 'amplitude': '2.75', 'offset': '-0.3', 'n_cycles': '7'}),
    ('AMR/amr_GUI.py', 'AMRApp', {
        'dmm_address_entry': 'GPIB0::12::INSTR',
        'calibrator_address_entry': 'GPIB0::13::INSTR',
        'stepper_address_entry': 'ASRL4::INSTR',
        'lockin_address_entry': 'GPIB0::14::INSTR',
        'initialize_lockin_var': False, 'x_axis': 'field', 'y_axis': 'Y',
    }, {'field': '250', 'angle_step': '17', 'total_angle': '180',
        'amplitude': '0.2', 'frequency': '37', 'measure_time': '2.5',
        'sensitivity': '100uv/pa'}),
    ('DCIV/IV_sweep_GUI.py', 'IVSweepApp', {
        'sm_address_entry': 'GPIB0::15::INSTR', 'sense_mode_entry': '4W',
        'x_axis': 'current (A)', 'y_axis': 'voltage (V)',
    }, {'v_start': '-2', 'v_stop': '3', 'num_steps': '13',
        'current_compliance': '0.007', 'dwell_time': '0.35'}),
    ('Quickstart/quick_start_local_GUI.py', 'QuickstartApp', {
        'awg_address_entry': 'GPIB0::16::INSTR',
        'osc_address_entry': 'GPIB0::17::INSTR', 'auto_save_entry': False,
    }, {'waveform': 'RAMP', 'frequency': '4321', 'amplitude': '3.25', 'offset': '-0.2'}),
]
PUND_VALUES = {
    'reset_amp': '3.5', 'reset_width': '2e-6', 'reset_delay': '3e-6',
    'p_u_amp': '2.5', 'p_u_width': '4e-6', 'p_u_delay': '5e-6', 'offset': '0.7',
}


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
        probe.destroy()
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

    def create(case=GUI_CASES[0]):
        relative, name, _, _ = case
        if name not in modules:
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
        root = tk.Tk()
        root.report_callback_exception = lambda *error: failures.append(error)
        app = getattr(modules[name], name)(root)
        windows.append(app)
        # Let the inherited startup timer load settings, as it does in a real run.
        root.after(300, root.quit)
        root.mainloop()
        return app

    create.prompts = prompts
    create.failures = failures
    yield create
    for app in windows:
        try:
            if app.root.winfo_exists():
                app.root.after_cancel(app._load_settings_id)
                app.root.destroy()
        except tk.TclError:
            pass
        plt.close(app.fig)
    sys.stdout, sys.stderr = stdout, stderr


@pytest.mark.parametrize('case', GUI_CASES, ids=[case[1] for case in GUI_CASES])
def test_every_input_survives_close_and_reopen(open_gui, tmp_path, case):
    app = open_gui(case)
    assert app.save_dir_entry.get() == 'scratch'
    expected = dict(case[2], save_dir_entry=str(tmp_path / 'custom data directory'))
    for name, value in expected.items():
        assert getattr(app, name).get() != value
        set_input(getattr(app, name), value)
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
        assert getattr(app, name).get() == value, name
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
    assert app.awg_address_entry.get() == 'GPIB0::9::INSTR'
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
