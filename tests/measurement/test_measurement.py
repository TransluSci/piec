"""Public measurement contracts exercised through real virtual instruments."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from piec.measurement.contracts import RunState, SafetyStatus
from piec.measurement.persistence import read_measurement_csv
from tests.support.discovery import assert_all_measurements_registered
from tests.support.measurement_cases import MEASUREMENT_CASES


def assert_no_io(calls):
    assert not {key: spy.mock_calls for key, spy in calls.items() if spy.mock_calls}


def assert_data_matches(actual, expected):
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True),
                                  check_dtype=False, rtol=1e-10, atol=1e-15)


def test_all_measurements_registered():
    assert_all_measurements_registered({case.cls for case in MEASUREMENT_CASES})


@pytest.mark.parametrize('case', MEASUREMENT_CASES, ids=lambda case: case.name)
class TestCanonicalMeasurementContract:
    def test_constructor_and_invalid_options_have_zero_io(self, case, monkeypatch):
        _, calls, construct = case.build(monkeypatch)
        construct()
        assert_no_io(calls)
        _, calls, construct = case.build(monkeypatch, **case.invalid_options)
        with pytest.raises(ValueError):
            construct()
        assert_no_io(calls)

    def test_minimal_successful_run(self, case, monkeypatch):
        instruments, calls, construct = case.build(monkeypatch)
        meas = construct()
        data = meas.run_experiment(save=False)
        assert isinstance(data, pd.DataFrame)
        assert not data.empty
        assert set(data.columns) == set(case.units)
        assert all(pd.api.types.is_numeric_dtype(dtype) for dtype in data.dtypes)
        assert np.isfinite(data.to_numpy()).all()
        assert meas.column_units == case.units
        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        case.assert_safe(instruments, calls)

    def test_stop_before_execution_has_zero_io(self, case, monkeypatch):
        _, calls, construct = case.build(monkeypatch)
        meas = construct()
        token = meas._reserve()
        meas.request_stop()
        result = meas.run_experiment(token=token, save=False)
        assert result.empty
        assert meas.run_state == RunState.ABORTED
        assert meas.safety_status == SafetyStatus.NOT_NEEDED
        assert_no_io(calls)

    @pytest.mark.parametrize('interruption', ['stop', 'callback_error'])
    def test_interruption_preserves_acquired_data_and_safes(self, case, monkeypatch, tmp_path, interruption):
        instruments, calls, construct = case.build(monkeypatch)
        meas = construct()
        meas.output_dir = tmp_path
        captured = []
        fault = RuntimeError('injected acquisition callback fault')

        def interrupt(snapshot):
            # This callback runs after real instrument acquisition, including a
            # full frame for single-shot FE and a real row for scalar families.
            view = snapshot.get_view('raw')
            if view is None:
                view = snapshot.get_view('raw_window')
            assert view is not None and not view.empty
            captured.append(view.copy())
            if interruption == 'stop':
                meas.request_stop()
            else:
                raise fault

        if interruption == 'stop':
            result = meas.run_experiment(save=True, save_partial=True, on_update=interrupt)
            assert meas.run_state == RunState.ABORTED
            assert_data_matches(result, captured[0])
        else:
            with pytest.raises(RuntimeError) as error:
                meas.run_experiment(save=True, save_partial=True, on_update=interrupt)
            assert error.value is fault
            assert meas.run_state == RunState.FAILED
        assert len(captured) == 1
        assert_data_matches(meas.raw_data, captured[0])
        assert meas.filename is None
        assert meas.safety_status == SafetyStatus.SAFE
        case.assert_safe(instruments, calls)
        meta, saved, _ = read_measurement_csv(meas.partial_filename)
        assert_data_matches(saved, captured[0])
        assert meta['partial'] is True
        assert meta['outcome'] == meas.run_state.value

    def test_persistence_roundtrip(self, case, monkeypatch, tmp_path):
        instruments, calls, construct = case.build(monkeypatch)
        meas = construct()
        meas.output_dir = tmp_path
        data = meas.run_experiment(save=True)
        assert Path(meas.filename).is_file()
        meta, saved, units = read_measurement_csv(meas.filename)
        assert meta['measurement_schema'] == case.schema
        assert units == case.units
        assert_data_matches(saved, data)
        case.assert_safe(instruments, calls)

    def test_sensor_failure_retains_available_data_and_safes(self, case, monkeypatch):
        instruments, calls, construct = case.build(monkeypatch)
        meas = construct()
        sensor = calls[case.sensor]
        fault = OSError('sensor disconnected')
        captured = []

        def fail_next_read(snapshot):
            frame = snapshot.get_view('raw')
            if frame is None:
                frame = snapshot.get_view('raw_window')
            captured.append(frame.copy())
            sensor.side_effect = fault

        # Streaming measurements fail on the next physical read, after a real
        # row. Single-shot measurements have no partial frame before readout.
        if not case.has_multiple_reads:
            sensor.side_effect = fault
        with pytest.raises(OSError) as error:
            meas.run_experiment(save=False, on_update=fail_next_read)
        assert error.value is fault
        assert sensor.called
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.SAFE
        if case.has_multiple_reads:
            assert len(captured) == 1
            assert_data_matches(meas.raw_data, captured[0])
        else:
            assert meas.raw_data is None or meas.raw_data.empty
        case.assert_safe(instruments, calls)
