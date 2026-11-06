"""Real-widget GCD tests; all physical-address connections use fake transports."""

import time
from pathlib import Path

import pytest

from tests.test_gui_settings import open_gui, set_input


GCD_CASE = ('GCD/gcd_GUI.py', 'GCDApp', {}, {})


def pump_until(app, condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    assert condition(), 'GUI did not reach the expected state'


def test_gcd_gui_runs_saves_and_stops_paused_worker(open_gui, tmp_path, monkeypatch):
    from piec.drivers import instrument as driver_module
    from piec.drivers.virtual_instrument import VirtualInstrument
    from piec.analysis.utilities import standard_csv_to_metadata_and_data

    def forbid_hardware(*args, **kwargs):
        pytest.fail('GCD demo must not discover or open hardware')

    monkeypatch.setattr(driver_module, 'PiecManager', forbid_hardware)
    app = open_gui(GCD_CASE)
    assert not open_gui.failures
    assert app.instrument_address_entries['sourcemeter'].get() == 'VIRTUAL'
    assert app.get_visa_resources() == []
    assert str(app.instrument_address_entries['sourcemeter'].cget('state')) == 'normal'
    app.refresh_instruments()

    set_input(app.save_dir_entry, str(tmp_path))
    set_input(app.dynamic_inputs['n_cycles'], '1')
    app.animate_var.set(False)
    app.run_button.invoke()
    pump_until(app, lambda: not app.is_measuring)
    assert app.experiment.status == 'complete'
    assert app.experiment.completed_cycles == 1
    assert not app.experiment.sourcemeter.state['output_on']
    assert Path(app.experiment.filename).exists()
    assert Path(app.experiment.plot_filename).exists()
    assert len(app.ax.lines) == 1
    original_sample = VirtualInstrument._shared_fe_sample

    # Exercise inherited settings with entries, checkboxes, and plot selectors.
    set_input(app.dynamic_inputs['initial_soc'], '0.35')
    app.sense_mode.set('4W')
    app.y_axis.set('current (A)')
    assert app.save_settings()
    app.dynamic_inputs['initial_soc'].delete(0, 'end')
    app.sense_mode.set('2W')
    app.y_axis.set('voltage (V)')
    app.load_settings()
    assert app.dynamic_inputs['initial_soc'].get() == '0.35'
    assert app.sense_mode.get() == '4W'
    assert app.y_axis.get() == 'current (A)'

    app.animate_var.set(True)
    app.run_measurement()
    app.toggle_pause()
    pump_until(app, lambda: not app.experiment.sourcemeter.state['output_on'])
    app.stop_measurement()
    pump_until(app, lambda: not app.is_measuring)
    assert app.experiment.status == 'aborted'
    assert VirtualInstrument._shared_fe_sample is original_sample
    assert not app.experiment.sourcemeter.state['output_on']
    metadata, data = standard_csv_to_metadata_and_data(app.experiment.filename)
    assert metadata.loc[0, 'status'] == 'aborted'
    assert len(data) < 100
    assert not open_gui.failures

    # Restart through the same GUI after Stop.
    stopped_filename = app.experiment.filename
    app.animate_var.set(False)
    app.run_measurement()
    pump_until(app, lambda: not app.is_measuring)
    assert app.experiment.status == 'complete'
    assert app.experiment.completed_cycles == 1
    assert app.experiment.filename != stopped_filename
    assert app.experiment.data['time (s)'].iloc[0] == 0

    # Closing during an active run must wait for its worker and data saving.
    app.animate_var.set(True)
    app.run_measurement()
    app.on_closing()
    assert app._closing_requested
    assert app.root.winfo_exists()
    pump_until(app, lambda: not app.is_measuring)
    assert not app.measurement_thread.is_alive()
    assert Path(app.experiment.filename).exists()
    assert app.instruments == {}
    assert VirtualInstrument._shared_fe_sample is original_sample
    assert not open_gui.failures


def test_gcd_gui_physical_selection_uses_standard_connector_and_protocol(open_gui, tmp_path, monkeypatch):
    from piec.drivers import instrument as driver_module
    from piec.drivers.virtual_instrument import VirtualInstrument
    from piec.measurement import gui_utils
    from tests.support.gcd import scripted_smu

    def forbid_hardware(*args, **kwargs):
        pytest.fail('Physical-address GUI test must use its scripted transport')

    monkeypatch.setattr(driver_module, 'PiecManager', forbid_hardware)
    app = open_gui(GCD_CASE)
    smu = scripted_smu(immediate_cutoffs=True)
    address = 'GPIB0::24::INSTR'
    smu.instrument.resource_name = address
    detected = []

    def detector(**kwargs):
        detected.append(kwargs)
        return smu

    monkeypatch.setattr(gui_utils, 'autodetect', detector)
    monkeypatch.setattr(app, '_manual_driver', lambda name: None)
    monkeypatch.setattr(app, 'get_visa_resources', lambda: [address])
    app.refresh_instruments()
    assert address in app.instrument_address_entries['sourcemeter']['values']
    app.autodetect_instruments()
    assert app.instrument_address_entries['sourcemeter'].get() == address
    detected.clear()
    original_sample = VirtualInstrument._shared_fe_sample
    set_input(app.save_dir_entry, str(tmp_path))
    set_input(app.dynamic_inputs['n_cycles'], '1')
    # Virtual-only settings must be ignored for a physical driver.
    set_input(app.dynamic_inputs['capacity_ah'], 'not applicable')
    set_input(app.dynamic_inputs['initial_soc'], 'not applicable')
    app.run_measurement()
    pump_until(app, lambda: not app.is_measuring)
    assert len(detected) == 1
    assert detected[0]['address'] == address
    assert app.experiment.sourcemeter is smu
    assert not app.experiment.virtual_time
    assert app.experiment.simulation_delay == 0
    assert app.experiment.status == 'complete'
    assert 'simulation_sample' not in app.experiment.metadata
    assert 'sample' not in smu.__dict__
    assert VirtualInstrument._shared_fe_sample is original_sample
    assert smu.instrument.off_mode == 'HIMP'
    assert not smu.instrument.output_on
    assert smu.instrument.current == 0
    app.on_closing()
    assert '*RST' not in smu.instrument.writes
    assert not open_gui.failures
