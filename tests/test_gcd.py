"""GCD battery physics, virtual SMU behavior, and saved measurement pipeline."""

from pathlib import Path
import threading

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.gcd import GCD
from piec.simulation.battery import Battery
from piec.simulation.fe_material import Resistor
from piec.simulation.sample import Sample
from tests.support.gcd import Clock, scripted_smu


@pytest.fixture(autouse=True)
def no_physical_connections(monkeypatch):
    from piec.drivers import instrument

    def forbidden(*args, **kwargs):
        pytest.fail('GCD tests must never open physical hardware')

    monkeypatch.setattr(instrument, 'PiecManager', forbidden)


@pytest.fixture
def smu(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, '_shared_fe_sample', None)
    monkeypatch.setattr(VirtualInstrument, '_shared_mag_sample', None)
    instrument = Keithley2400('VIRTUAL')
    instrument.sample = Battery()
    return instrument


def test_battery_coulomb_counting_and_instantaneous_response():
    battery = Battery(parameter_dict={'capacity_ah': 1.0, 'initial_soc': 0.25})
    assert isinstance(battery, Sample)
    assert battery.name == 'virtual_battery'
    battery.advance_time(0.5, 1800)
    assert battery.soc == pytest.approx(0.5)
    voltage, coordinate = battery.current_response(0.1, 10)
    assert voltage == pytest.approx(3.7)  # 3.6 V OCV + I R
    assert coordinate == 10
    assert battery.voltage_response(voltage, coordinate)[0] == pytest.approx(0.1)
    battery.advance_time(-0.5, 1800)
    assert battery.soc == pytest.approx(0.25)
    battery.advance_time(-1.0, 3600)
    assert battery.soc == 0
    battery.advance_time(2.0, 3600)
    assert battery.soc == 1


@pytest.mark.parametrize('parameters', [
    {'capacity_ah': 0}, {'resistance': -1}, {'initial_soc': 1.1},
    {'voltage_empty': 5}, {'voltage_full': np.nan},
])
def test_battery_rejects_invalid_parameters(parameters):
    with pytest.raises(ValueError):
        Battery(**parameters)


def test_virtual_time_advances_only_with_output_on_and_reads_do_not_advance(smu):
    smu.configure_current_source(current=0.01, voltage_compliance=5)
    initial_soc = smu.sample.soc
    smu.advance_time(10)
    assert smu.sample.soc == initial_soc
    assert smu.get_current() == 0
    smu.output(on=True)
    smu.advance_time(36)
    assert smu.sample.soc == pytest.approx(initial_soc + 0.1)
    voltage = smu.get_voltage()
    for _ in range(3):
        assert smu.get_voltage() == voltage
        assert smu.get_current() == 0.01
    assert smu.sample.soc == pytest.approx(initial_soc + 0.1)
    smu.set_source_current(current=-0.01)
    smu.advance_time(36)
    assert smu.sample.soc == pytest.approx(initial_soc)


def test_compliance_reports_limited_current(smu):
    smu.configure_current_source(current=0.1, voltage_compliance=3.25)
    smu.output(on=True)
    assert smu.get_voltage() == pytest.approx(3.25)
    assert smu.get_current() == pytest.approx(0.01)  # OCV is 3.24 V


def test_resistor_response_preserved_and_dynamic_stepping_rejected(smu):
    smu.sample = Resistor(100)
    smu.configure_current_source(current=0.01, voltage_compliance=5)
    smu.output(on=True)
    assert smu.get_voltage() == pytest.approx(1)
    assert smu.get_current() == pytest.approx(0.01)
    with pytest.raises(TypeError, match='advance_time'):
        smu.advance_time(1)


def test_gcd_full_pipeline(smu, tmp_path, monkeypatch):
    def unexpected_sleep(_):
        pytest.fail('Virtual cycling must not sleep')
    monkeypatch.setattr('piec.measurement.gcd.time.sleep', unexpected_sleep)
    experiment = GCD(smu, virtual_time=True, n_cycles=3, save_dir=tmp_path,
                     show_plots=False)
    data = experiment.run_experiment()
    assert experiment.completed_cycles == 3
    assert experiment.status == 'complete'
    assert not smu.state['output_on']
    assert np.all(np.diff(data['time (s)']) >= 0)
    for cycle in (1, 2, 3):
        charge = data[(data.cycle == cycle) & (data.phase == 'charge')]
        discharge = data[(data.cycle == cycle) & (data.phase == 'discharge')]
        assert len(charge) > 10 and len(discharge) > 10
        assert charge['current (A)'].eq(experiment.current).all()
        assert discharge['current (A)'].eq(-experiment.current).all()
        assert charge['voltage (V)'].iloc[-1] >= experiment.voltage_upper
        assert discharge['voltage (V)'].iloc[-1] <= experiment.voltage_lower
        slope = experiment.current / (smu.sample.capacity_ah * 3600) * 1.2
        np.testing.assert_allclose(np.diff(charge['voltage (V)']), slope, atol=1e-12)
        np.testing.assert_allclose(np.diff(discharge['voltage (V)']), -slope, atol=1e-12)
    metadata, restored = standard_csv_to_metadata_and_data(experiment.filename)
    pd.testing.assert_frame_equal(restored, data)
    assert metadata.loc[0, 'mtype'] == 'gcd'
    assert metadata.loc[0, 'sourcemeter'] == smu.idn()
    assert metadata.loc[0, 'completed_cycles'] == 3
    assert metadata.loc[0, 'status'] == 'complete'
    assert metadata.loc[0, 'voltage_lower'] == experiment.voltage_lower
    assert 'capacity_ah' in metadata.loc[0, 'simulation_sample']
    assert len(experiment.history) == 1
    assert Path(experiment.plot_filename).read_bytes().startswith(b'\x89PNG')
    previous = experiment.filename
    experiment.run_experiment()
    assert experiment.filename != previous
    assert len(experiment.history) == 2


def test_unreachable_cutoff_saves_partial_data_and_disables_output(smu, tmp_path):
    experiment = GCD(smu, virtual_time=True, voltage_upper=4.5,
                     sample_interval=7, max_half_cycle_time=10,
                     save_dir=tmp_path, show_plots=False)
    with pytest.raises(TimeoutError, match='Cycle 1 charge'):
        experiment.run_experiment()
    assert not smu.state['output_on']
    assert experiment.completed_cycles == 0
    assert list(experiment.data['time (s)']) == [0, 7, 10]
    metadata, restored = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, 'status'] == 'aborted'
    assert len(restored) == 3
    assert len(experiment.history) == 1


@pytest.mark.parametrize('error', [RuntimeError('read failed'), KeyboardInterrupt()])
def test_read_failure_and_interruption_disable_output_and_preserve_data(smu, tmp_path, monkeypatch, error):
    read = smu.get_voltage
    reads = 0

    def fail_after_initial_read():
        nonlocal reads
        reads += 1
        if reads > 1:
            raise error
        return read()

    monkeypatch.setattr(smu, 'get_voltage', fail_after_initial_read)
    experiment = GCD(smu, virtual_time=True, save_dir=tmp_path, show_plots=False)
    with pytest.raises(type(error)):
        experiment.run_experiment()
    assert not smu.state['output_on']
    assert experiment.status == 'aborted'
    assert len(experiment.data) == 1
    assert Path(experiment.filename).exists()


@pytest.mark.parametrize('parameters', [
    {'current': 0}, {'current': 2}, {'n_cycles': 0}, {'n_cycles': 1.5},
    {'n_cycles': True}, {'sample_interval': 0}, {'max_half_cycle_time': -1},
    {'voltage_lower': 4.2}, {'voltage_compliance': 4.1},
    {'voltage_upper': np.inf}, {'sense_mode': 'invalid'},
])
def test_invalid_gcd_configuration_rejected(smu, parameters):
    with pytest.raises((ValueError, TypeError)):
        GCD(smu, **parameters)
    assert not smu.state['output_on']


def test_default_ferroelectric_sample_cannot_do_dynamic_battery_cycling(smu):
    VirtualInstrument.set_virtual_sample(None)
    default_smu = Keithley2400('VIRTUAL')
    with pytest.raises(ValueError, match='dynamic virtual sample'):
        GCD(default_smu, virtual_time=True)


def test_pause_stop_and_live_snapshots(smu, tmp_path, monkeypatch):
    """Stop from a paused worker, preserving data without advancing the battery."""
    experiment = GCD(smu, virtual_time=True, save_dir=tmp_path,
                     show_plots=False, save_plots=False)
    paused = threading.Event()
    release = threading.Event()
    errors = []

    def pause_wait(_):
        assert not smu.state['output_on']
        paused.set()
        assert release.wait(5), 'Test did not release paused worker'

    advance = smu.advance_time

    def pause_after_step(seconds):
        advance(seconds)
        experiment.pause_requested = True

    monkeypatch.setattr(smu, 'advance_time', pause_after_step)
    monkeypatch.setattr('piec.measurement.gcd.time.sleep', pause_wait)

    def run():
        try:
            experiment.run_experiment()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert paused.wait(5), 'Worker did not acknowledge pause'
        snapshot = experiment.get_data_snapshot()
        assert len(snapshot) == 1
        snapshot.iloc[0, 1] = -999
        assert experiment.get_data_snapshot().iloc[0, 1] > 0
        soc = smu.sample.soc
        experiment.abort_requested = True
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert not errors
    assert smu.sample.soc == soc
    assert not smu.state['output_on']
    assert experiment.status == 'aborted'
    metadata, saved = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, 'status'] == 'aborted'
    assert len(saved) == 1


def test_pause_resume_completes_without_counting_pause_as_simulated_time(smu, tmp_path, monkeypatch):
    experiment = GCD(smu, virtual_time=True, n_cycles=1, save_dir=tmp_path,
                     show_plots=False, save_plots=False)
    experiment.pause_requested = True
    start_soc = smu.sample.soc
    pauses = []

    def resume(_):
        pauses.append(smu.sample.soc)
        assert not smu.state['output_on']
        experiment.pause_requested = False

    monkeypatch.setattr('piec.measurement.gcd.time.sleep', resume)
    # Worker mode must never create matplotlib figures, even with TkAgg loaded.
    monkeypatch.setattr('piec.measurement.gcd.plt.subplots',
                        lambda: pytest.fail('Disabled plotting must not create a figure'))
    experiment.run_experiment()
    assert pauses == [start_soc]
    assert experiment.status == 'complete'
    assert experiment.completed_cycles == 1
    assert experiment.data['time (s)'].iloc[0] == 0
    assert not smu.state['output_on']


def test_same_gcd_instance_restarts_after_stop(smu, tmp_path, monkeypatch):
    experiment = GCD(smu, virtual_time=True, n_cycles=1, save_dir=tmp_path,
                     show_plots=False, save_plots=False)
    advance = smu.advance_time

    def stop_after_step(seconds):
        advance(seconds)
        experiment.abort_requested = True
        experiment.pause_requested = True

    monkeypatch.setattr(smu, 'advance_time', stop_after_step)
    experiment.run_experiment()
    assert experiment.status == 'aborted'
    old_filename = experiment.filename
    old_history = experiment.history[0].copy()
    monkeypatch.setattr(smu, 'advance_time', advance)
    experiment.run_experiment()
    assert experiment.status == 'complete'
    assert experiment.completed_cycles == 1
    assert not experiment.abort_requested and not experiment.pause_requested
    assert experiment.filename != old_filename
    assert experiment.data['time (s)'].iloc[0] == 0
    assert len(experiment.history) == 2
    pd.testing.assert_frame_equal(experiment.history[0], old_history)
    assert smu.state['off_mode'] == 'HIMP'
    assert smu.state['source_current'] == 0


def test_same_protocol_in_physical_and_virtual_modes(smu, tmp_path, monkeypatch):
    """Compare the real driver's SCPI path with accelerated virtual acquisition."""
    physical = scripted_smu()
    clock = Clock()
    clock.on_sleep = physical.instrument.advance
    monkeypatch.setattr('piec.measurement.gcd.time.monotonic', clock.monotonic)
    monkeypatch.setattr('piec.measurement.gcd.time.sleep', clock.sleep)
    experiment = GCD(physical, n_cycles=2, sample_interval=0.1, save_dir=tmp_path,
                     show_plots=False, save_plots=False)
    physical_data = experiment.run_experiment()
    assert not isinstance(physical, VirtualInstrument)
    assert clock.sleeps and max(clock.sleeps) <= 0.05
    assert 'simulation_sample' not in experiment.metadata
    smu.sample = Battery(capacity_ah=0.00001)
    virtual_experiment = GCD(smu, virtual_time=True, n_cycles=2,
                             sample_interval=0.1, save_dir=tmp_path,
                             show_plots=False, save_plots=False)
    virtual_data = virtual_experiment.run_experiment()
    pd.testing.assert_frame_equal(physical_data, virtual_data, atol=1e-10, rtol=1e-10)
    writes = physical.instrument.writes
    assert writes[:2] == [':OUTP:SMOD HIMP', ':OUTP OFF']
    assert writes[-3:] == [':OUTP:SMOD HIMP', ':OUTP OFF', ':SOUR:CURR:LEV 0.0']
    assert ':SOUR:CURR:LEV 0.01' in writes
    assert ':SOUR:CURR:LEV -0.01' in writes
    physical.instrument.writes.clear()
    experiment.safe_close()
    assert physical.instrument.writes == [':OUTP:SMOD HIMP', ':OUTP OFF', ':SOUR:CURR:LEV 0.0']


@pytest.mark.parametrize('failure', ['read', 'setup', 'timeout', 'stop'])
def test_physical_path_cleans_up_on_every_exit(tmp_path, monkeypatch, failure):
    smu = scripted_smu()
    transport = smu.instrument
    clock = Clock()
    clock.on_sleep = transport.advance
    monkeypatch.setattr('piec.measurement.gcd.time.monotonic', clock.monotonic)
    monkeypatch.setattr('piec.measurement.gcd.time.sleep', clock.sleep)
    experiment = GCD(smu, n_cycles=1, max_half_cycle_time=0.1,
                     save_dir=tmp_path, show_plots=False, save_plots=False)
    if failure == 'read':
        read = smu.get_voltage

        def fail_second_read():
            if transport.reads >= 2:
                raise OSError('scripted read failed')
            return read()

        monkeypatch.setattr(smu, 'get_voltage', fail_second_read)
        expected = OSError
    elif failure == 'setup':
        def fail_setup(**kwargs):
            raise OSError('scripted setup failed')
        monkeypatch.setattr(smu, 'set_sense_mode', fail_setup)
        expected = OSError
    elif failure == 'stop':
        def stop(seconds):
            transport.advance(seconds)
            experiment.abort_requested = True
        clock.on_sleep = stop
        expected = None
    else:
        expected = TimeoutError
    if expected:
        with pytest.raises(expected):
            experiment.run_experiment()
    else:
        experiment.run_experiment()
        assert len(clock.sleeps) == 1  # Stop does not wait out the whole interval.
    assert experiment.status == 'aborted'
    assert not transport.output_on
    assert transport.current == 0
    assert transport.off_mode == 'HIMP'
    assert transport.writes[-3:] == [':OUTP:SMOD HIMP', ':OUTP OFF', ':SOUR:CURR:LEV 0.0']
    if failure != 'setup':
        metadata, data = standard_csv_to_metadata_and_data(experiment.filename)
        assert metadata.loc[0, 'status'] == 'aborted'
        assert len(data) >= 1


def test_shutdown_failure_attempts_output_off_and_preserves_acquisition_error(tmp_path, monkeypatch):
    smu = scripted_smu()
    experiment = GCD(smu, save_dir=tmp_path, show_plots=False, save_plots=False)

    def fail_read():
        # Fail HIMP setup only during the subsequent cleanup.
        monkeypatch.setattr(smu, 'set_off_mode', lambda **kwargs: (_ for _ in ()).throw(OSError('HIMP failed')))
        raise OSError('primary read failed')

    monkeypatch.setattr(smu, 'get_voltage', fail_read)
    with pytest.raises(OSError, match='primary read failed'):
        experiment.run_experiment()
    assert 'HIMP failed' in experiment.cleanup_error
    assert not smu.instrument.output_on
    assert smu.instrument.current == 0
    assert Path(experiment.filename).exists()


def test_physical_driver_cannot_enable_accelerated_time():
    smu = scripted_smu()
    with pytest.raises(ValueError, match='virtual SMU'):
        GCD(smu, virtual_time=True)
    assert smu.instrument.writes == []


def test_high_impedance_support_is_required_before_operating(smu, monkeypatch):
    monkeypatch.setattr(type(smu), 'off_mode', ['NORM'])
    with pytest.raises(ValueError, match='HIMP'):
        GCD(smu)
    assert not smu.state['output_on']
