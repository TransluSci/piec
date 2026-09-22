"""Regression coverage for capture placement and calibrated analysis timing."""

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from piec.analysis.hysteresis import process_raw_hyst
from piec.analysis.pund import process_raw_3pp
from piec.analysis.utilities import (
    metadata_and_data_to_csv,
    standard_csv_to_metadata_and_data,
)
from piec.measurement.discrete_waveform import (
    DiscreteWaveform,
    HysteresisLoop,
    ThreePulsePund,
)


def instruments():
    return Mock(idn=Mock(return_value='AWG')), Mock(idn=Mock(return_value='Scope'))


@pytest.mark.parametrize('frequency', [100, 1000, 1e6])
@pytest.mark.parametrize('time_offset', [0.0, 100e-9])
def test_capture_starts_at_response_with_only_trailing_padding(frequency, time_offset):
    awg, scope = instruments()
    measurement = HysteresisLoop(awg=awg, osc=scope, frequency=frequency,
                                 time_offset=time_offset)
    measurement.configure_oscilloscope()
    settings = scope.configure_horizontal.call_args.kwargs

    # A ten-division scope locates the trigger relative to the screen center.
    duration = 10 * settings['tdiv']
    start = -settings['x_position'] - duration / 2
    assert settings['x_position'] < 0
    assert start == pytest.approx(time_offset, abs=1e-15)
    assert start + duration - (time_offset + 1 / frequency) == pytest.approx(
        0.25 / frequency
    )


def test_pund_capture_recomputes_position_when_duration_changes():
    awg, scope = instruments()
    measurement = ThreePulsePund(awg=awg, osc=scope, time_offset=100e-9)
    for length in [6e-3, 12e-3]:
        measurement.length = length
        measurement.configure_oscilloscope()
        settings = scope.configure_horizontal.call_args.kwargs
        start = -settings['x_position'] - 5 * settings['tdiv']
        assert start == pytest.approx(100e-9, abs=1e-15)
        assert 10 * settings['tdiv'] == pytest.approx(1.25 * length)


@pytest.mark.parametrize('time_offset', [0.0, 100e-9])
def test_base_class_uses_time_offset_to_start_capture(time_offset):
    awg, scope = instruments()
    measurement = DiscreteWaveform(awg=awg, osc=scope, time_offset=time_offset)
    measurement.length = 1e-3
    measurement.configure_oscilloscope()
    settings = scope.configure_horizontal.call_args.kwargs
    assert -settings['x_position'] - 5 * settings['tdiv'] == pytest.approx(time_offset)


@pytest.mark.parametrize('time_offset,expected_wait', [
    (-2.0, 0.0),
    (-1.25, 0.0),
    (-0.1, 1.38),
    (0.0, 1.5),
    (0.1, 1.62),
])
def test_capture_wait_includes_delay_and_trailing_padding(monkeypatch, time_offset,
                                                       expected_wait):
    awg, scope = instruments()
    measurement = HysteresisLoop(awg=awg, osc=scope, frequency=1, time_offset=time_offset)
    measurement.configure_oscilloscope()
    sleep = Mock()
    monkeypatch.setattr('piec.measurement.discrete_waveform.time.sleep', sleep)
    scope.get_data.return_value = pd.DataFrame({'Time': [time_offset], 'Voltage': [0.0]})
    measurement.apply_and_capture_waveform()
    assert sleep.call_args.args[0] == pytest.approx(expected_wait)


@pytest.mark.parametrize('measurement_class,process', [
    (HysteresisLoop, process_raw_hyst),
    (ThreePulsePund, process_raw_3pp),
])
@pytest.mark.parametrize('auto_timeshift', [False, True])
def test_analysis_starts_applied_waveform_at_zero(tmp_path, measurement_class, process,
                                                auto_timeshift):
    awg, scope = instruments()
    calibration = 100e-6
    measurement = measurement_class(awg=awg, osc=scope, time_offset=calibration)
    measurement.configure_oscilloscope()
    measurement._update_metadata()
    times = np.linspace(0, 1.25 * measurement.length, 2001)
    data = pd.DataFrame({'time (s)': times + calibration,
                         'voltage (V)': -np.exp(-times / 100e-6)})
    path = str(tmp_path / 'capture.csv')
    metadata_and_data_to_csv(measurement.metadata, data, path)

    process(path, auto_timeshift=auto_timeshift)
    metadata, result = standard_csv_to_metadata_and_data(path)
    applied = result['applied voltage (V)'].to_numpy()
    first_nonzero = np.flatnonzero(applied)[0]
    assert first_nonzero <= 1  # A triangle starts at zero; a pulse does not.
    assert result['time (s)'].iloc[0] == 0
    assert metadata['time_offset'].iloc[0] == pytest.approx(calibration)
    assert applied[-1] == 0  # The capture retains a tail after the waveform.
