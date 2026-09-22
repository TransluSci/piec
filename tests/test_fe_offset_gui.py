"""Calibration button behavior without opening windows or connecting hardware."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def gui(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'Measurements/Ferroelectric Testing/FE_testing_GUI.py'
    spec = importlib.util.spec_from_file_location('fe_offset_gui', path)
    module = importlib.util.module_from_spec(spec)
    # gui_utils selects TkAgg on import; keep the headless backend during tests.
    with patch('matplotlib.use'):
        spec.loader.exec_module(module)
    app = module.FEMeasurementApp.__new__(module.FEMeasurementApp)
    app.root = Mock()
    app.measure_offset_button = Mock()
    app.run_button = Mock()
    app.timeshift_entry = Mock(get=Mock(return_value='100'))
    app.awg_address_entry = Mock(get=Mock(return_value='AWG'))
    app.osc_address_entry = Mock(get=Mock(return_value='Scope'))
    app._get_instruments = Mock(return_value=(Mock(), Mock()))
    monkeypatch.setattr(module.messagebox, 'askokcancel', Mock(return_value=True))
    monkeypatch.setattr(module.messagebox, 'showerror', Mock())
    calibration = Mock()
    calibration.measure_time_offset.return_value = -35.25e-9
    monkeypatch.setattr(module, 'DiscreteWaveform', Mock(return_value=calibration))
    return app, module, calibration


def test_cancel_leaves_instruments_and_offset_untouched(gui):
    app, module, calibration = gui
    module.messagebox.askokcancel.return_value = False
    app.measure_time_offset()
    app._get_instruments.assert_not_called()
    calibration.measure_time_offset.assert_not_called()
    app.timeshift_entry.delete.assert_not_called()


def test_confirmation_precedes_hardware_access_and_updates_nanoseconds(gui):
    app, module, calibration = gui
    calls = Mock()
    calls.attach_mock(module.messagebox.askokcancel, 'confirm')
    calls.attach_mock(app._get_instruments, 'connect')
    calls.attach_mock(calibration.measure_time_offset, 'calibrate')
    app.measure_time_offset()
    assert [call[0] for call in calls.mock_calls] == ['confirm', 'connect', 'calibrate']
    assert 'probes are shorted' in module.messagebox.askokcancel.call_args.args[1]
    app.timeshift_entry.insert.assert_called_once_with(0, '-35.25')
    app.measure_offset_button.configure.assert_called_with(state='normal')
    app.run_button.configure.assert_called_with(state='normal')


def test_failed_calibration_preserves_entry_and_restores_controls(gui):
    app, module, calibration = gui
    calibration.measure_time_offset.side_effect = ValueError('No pulse')
    app.measure_time_offset()
    app.timeshift_entry.delete.assert_not_called()
    module.messagebox.showerror.assert_called_once()
    app.measure_offset_button.configure.assert_called_with(state='normal')
    app.run_button.configure.assert_called_with(state='normal')


def test_virtual_instrument_does_not_claim_a_hardware_calibration(gui):
    app, module, calibration = gui
    app.osc_address_entry.get.return_value = 'VIRTUAL'
    app.measure_time_offset()
    app._get_instruments.assert_not_called()
    app.timeshift_entry.delete.assert_not_called()
    module.messagebox.showerror.assert_called_once()
