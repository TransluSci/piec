"""Preflight, readback, ownership, and calibration regressions for checkpoint 24a."""
import threading
from unittest.mock import Mock

import pytest

from piec.measurement import MagnetoTransport, MeasurementRunner
from piec.measurement.adapters.amr import AMRSetupProfile, FieldSource, FieldReader, TransportReadout, OrientationController
from piec.measurement.contracts import HardwareSafetyError, RunState, SafetyStatus
from tests.test_measurement_magneto_transport import create_mock_instruments


def measurement(**kwargs):
    instruments = create_mock_instruments()
    run = MagnetoTransport(dmm=instruments['dmm'], calibrator=instruments['calibrator'],
        stepper=instruments['arduino'], lockin=instruments['lockin'], field=100,
        shutdown_handler=kwargs.pop('shutdown_handler', Mock()), **kwargs)
    return run, instruments


def test_default_missing_shutdown_is_rejected_before_any_io():
    run, instruments = measurement(shutdown_handler=None)
    with pytest.raises(HardwareSafetyError):
        run.run_experiment(save=False)
    assert all(not instrument.mock_calls for instrument in instruments.values())


@pytest.mark.parametrize('options', [
    {'require_excitation_safing': False}, {'configure_lockin': 'False'},
    {'configure_lockin': 1}, {'readout_configuration': 'CONFIGURE'},
    {'configure_lockin': True, 'readout_configuration': 'preserve'},
])
def test_invalid_or_bypass_options_do_not_write(options):
    run, instruments = measurement()
    with pytest.raises(ValueError):
        run.run_experiment(options=options, save=False)
    assert all(not instrument.mock_calls for instrument in instruments.values())


@pytest.mark.parametrize('fault', ['query', 'nonfinite', 'mismatch'])
def test_field_reader_failure_stops_acquisition_and_still_safes(fault):
    run, instruments = measurement()
    instruments['dmm'].get_voltage.side_effect = None
    if fault == 'query':
        instruments['dmm'].get_voltage.side_effect = RuntimeError('read failed')
    else:
        instruments['dmm'].get_voltage.return_value = float('nan') if fault == 'nonfinite' else 100
    run.field_reader.mismatch_policy = 'raise'
    with pytest.raises((RuntimeError, ValueError)):
        run.run_experiment(save=False)
    assert run.run_state == RunState.FAILED
    assert run.safety_status == SafetyStatus.SAFE
    instruments['lockin'].get_X_Y.assert_not_called()
    instruments['calibrator'].output.assert_called_with(on=False)
    run.transport_readout.shutdown_handler.assert_called_once()


def test_invalid_field_preflight_happens_before_excitation_configuration():
    run, instruments = measurement(readout_configuration='configure')
    run.field_source.field_range = (-10, 10)
    with pytest.raises(ValueError):
        run.run_experiment(save=False)
    assert all(not instrument.mock_calls for instrument in instruments.values())


def test_profile_units_and_configure_policy_are_preserved_in_saved_readback(tmp_path):
    source, reader, lockin, motor = Mock(), Mock(), Mock(), Mock()
    reader.get_field.return_value = .1
    lockin.get_X_Y.return_value = (1e-5, 2e-5)
    profile = AMRSetupProfile(FieldSource(source, calibration='native', field_unit='T'),
        FieldReader(reader, calibration='native', field_unit='T'),
        TransportReadout(lockin, readout_configuration='configure', shutdown_handler=Mock()),
        OrientationController(motor))
    run = MagnetoTransport(profile=profile, field=.1, output_dir=tmp_path)
    frame = run.run_experiment(save=True)
    assert run.column_units['field'] == run.column_units['field_measured'] == 'T'
    assert frame.field_measured.iloc[0] == .1
    assert frame.field_time.iloc[0] >= 0
    assert frame.field_time.iloc[0] < 10
    lockin.configure_reference.assert_called_once()
    source.set_field.assert_any_call(.1)


def test_legacy_hardware_bypasses_are_absent_from_standardized_base():
    run, _ = measurement()
    for name in ('initialize', 'set_field', 'shut_off', 'configure_lockin',
                 'arduino', 'voltage_callibration', 'abort_requested', 'pause_requested', 'save_dir'):
        assert not hasattr(run, name), name


def test_pause_blocks_point_read_and_stop_wakes_paused_worker():
    run, instruments = measurement()
    reached = threading.Event()
    configure = run._configure_instruments
    def pause_after_config(request):
        configure(request)
        run.request_pause()
        reached.set()
    run._configure_instruments = pause_after_config
    runner = MeasurementRunner(run)
    runner.start(save=False)
    try:
        assert reached.wait(5)
        instruments['lockin'].get_X_Y.assert_not_called()
        runner.request_stop()
        assert runner.join(5)
        assert runner.run_state == RunState.ABORTED
        assert runner.safety_status == SafetyStatus.SAFE
    finally:
        runner.request_stop()
        runner.join(5)
