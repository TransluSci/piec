"""Hardware-delay calibration using synthetic, trigger-relative scope captures."""

from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from piec.measurement.discrete_waveform import DiscreteWaveform, HysteresisLoop


def pulse_capture(delay, polarity=1, step=0.5e-9):
    times = np.arange(-1e-6, 1e-6, step)
    edge = 200e-9 + delay
    rise = np.clip((times - edge) / 4e-9 + 0.5, 0, 1)
    fall = np.clip((edge + 200e-9 - times) / 4e-9 + 0.5, 0, 1)
    voltage = 0.007 + polarity * 0.1 * np.minimum(rise, fall)
    return pd.DataFrame({'Time': times, 'Voltage': voltage})


@pytest.fixture
def measurement(monkeypatch):
    monkeypatch.setattr('piec.measurement.discrete_waveform.time.sleep', lambda _: None)
    awg = Mock(idn=Mock(return_value='AWG'))
    scope = Mock(idn=Mock(return_value='Scope'))
    return DiscreteWaveform(awg=awg, osc=scope, time_offset=42e-9)


@pytest.mark.parametrize('delay', [-100e-9, -10e-9, 0, 10.3e-9, 50.7e-9, 100e-9])
@pytest.mark.parametrize('polarity', [-1, 1])
def test_calibration_measures_signed_delay(measurement, delay, polarity):
    capture = pulse_capture(delay, polarity)
    # Include noise and an isolated spike before the real pulse.
    capture['Voltage'] += np.random.default_rng(12).normal(0, 0.0002, len(capture))
    capture.loc[1800, 'Voltage'] += 0.15
    measurement.osc.get_data.return_value = capture
    result = measurement.measure_time_offset()
    assert result == pytest.approx(delay, abs=0.1e-9)
    assert measurement.time_offset == result
    assert measurement.metadata['time_offset'].iloc[0] == result
    measurement.awg.output.assert_called_with(channel=1, on=False)
    measurement.osc.set_horizontal_position.assert_called_with(x_position=0.0)
    measurement.osc.set_acquisition_points.assert_called_with(acquisition_points=4000)


def test_calibration_preserves_experiment_data_and_frequency(measurement):
    loop = HysteresisLoop(awg=measurement.awg, osc=measurement.osc, frequency=10,
                          time_offset=1e-3)
    loop.data = pd.DataFrame({'saved': [1]})
    original_data = loop.data
    loop.osc.get_data.return_value = pulse_capture(30e-9)
    assert loop.measure_time_offset() == pytest.approx(30e-9, abs=1e-12)
    assert loop.length == 0.1
    assert loop.frequency == 10
    assert loop.data is original_data
    loop.osc.configure_horizontal.assert_called_with(tdiv=200e-9)


@pytest.mark.parametrize('bad_capture', ['flat', 'noise', 'coarse', 'nan', 'reversed', 'unpadded', 'partial', 'multiple'])
def test_invalid_capture_preserves_previous_offset(measurement, bad_capture):
    capture = pulse_capture(50e-9)
    if bad_capture == 'flat':
        capture['Voltage'] = 0.1
    elif bad_capture == 'noise':
        capture['Voltage'] = np.random.default_rng(2).normal(0, 0.001, len(capture))
    elif bad_capture == 'coarse':
        capture = pulse_capture(50e-9, step=10e-9)
    elif bad_capture == 'nan':
        capture.loc[20, 'Voltage'] = np.nan
    elif bad_capture == 'reversed':
        capture = capture.iloc[::-1]
    elif bad_capture == 'unpadded':
        capture = capture[capture['Time'] >= 0]
    elif bad_capture == 'partial':
        capture = pulse_capture(700e-9)
    elif bad_capture == 'multiple':
        capture['Voltage'] += pulse_capture(-500e-9)['Voltage'] - 0.007
    measurement.osc.get_data.return_value = capture
    with pytest.raises(ValueError):
        measurement.measure_time_offset()
    assert measurement.time_offset == 42e-9
    assert measurement.metadata['time_offset'].iloc[0] == 42e-9
    measurement.awg.output.assert_called_with(channel=1, on=False)


def test_output_disabled_when_acquisition_fails(measurement):
    measurement.osc.get_data.side_effect = TimeoutError('No trigger')
    with pytest.raises(TimeoutError):
        measurement.measure_time_offset()
    measurement.awg.output.assert_called_with(channel=1, on=False)
    assert measurement.time_offset == 42e-9
