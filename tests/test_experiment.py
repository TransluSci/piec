"""Regression coverage for shared experiment state and waveform metadata."""

from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.discrete_waveform import (
    DiscreteWaveform,
    HysteresisLoop,
    ThreePulsePund,
)
from piec.measurement.experiment import Experiment


def test_experiment_metadata_and_history_are_independent():
    experiment = Experiment()
    other = Experiment()
    assert experiment.save_dir == r'\\scratch'
    experiment.setting = 1.0
    experiment._private = 'excluded'
    experiment.callback = lambda: None
    experiment.data = pd.DataFrame({'value': [1, 2]})
    experiment._update_metadata()
    experiment._update_history()

    experiment.metadata.loc[0, 'setting'] = 2.0
    assert experiment.history[0].loc[0, 'setting'] == 1.0
    assert other.history == []
    assert 'setting' not in other.metadata
    assert not {'_private', 'callback', 'data', 'metadata', 'history'} & set(experiment.metadata)


def test_discrete_waveform_preserves_metadata_schema(monkeypatch, tmp_path):
    monkeypatch.setattr('piec.measurement.experiment.time.time', lambda: 123.0)
    awg = Mock(idn=Mock(return_value='AWG'))
    osc = Mock(idn=Mock(return_value='OSC'))
    waveform = DiscreteWaveform(awg, osc, v_div=0.2, voltage_channel='2', save_dir=str(tmp_path))

    expected = pd.DataFrame({
        'v_div': [0.2],
        'voltage_channel': ['2'],
        'save_dir': [str(tmp_path)],
        'mtype': [None],
        'awg': ['AWG'],
        'osc': ['OSC'],
        'length': [None],
        'timestamp': [123.0],
        'processed': [False],
    })
    pd.testing.assert_frame_equal(waveform.metadata, expected)
    assert waveform.data is None
    assert waveform.filename is None
    assert waveform.history == []
    awg.idn.assert_called_once_with()
    osc.idn.assert_called_once_with()


@pytest.mark.parametrize('measurement_class, parameters, field, initial, updated', [
    (HysteresisLoop, {'amplitude': 2.5}, 'amplitude', 2.5, 3.0),
    (ThreePulsePund, {'reset_amp': 2.5}, 'reset_amp', 2.5, 3.0),
])
def test_waveform_subclasses_refresh_save_and_snapshot_metadata(
    tmp_path, measurement_class, parameters, field, initial, updated,
):
    waveform = measurement_class(
        awg=Mock(idn=Mock(return_value='AWG')),
        osc=Mock(idn=Mock(return_value='OSC')),
        save_dir=str(tmp_path),
        **parameters,
    )
    assert waveform.metadata.loc[0, field] == initial
    assert waveform.metadata.loc[0, 'length'] == waveform.length
    waveform._update_history()
    setattr(waveform, field, updated)
    destination = tmp_path / 'updated'
    waveform.save_dir = str(destination)
    waveform.data = pd.DataFrame({'time (s)': [0.0, 1.0], 'voltage (V)': [0.0, 0.5]})
    waveform.save_waveform()
    waveform._update_history()

    assert Path(waveform.filename).parent == destination
    metadata, data = standard_csv_to_metadata_and_data(waveform.filename)
    assert metadata.loc[0, field] == updated
    assert metadata.loc[0, 'mtype'] == waveform.mtype
    assert metadata.loc[0, 'awg'] == 'AWG'
    assert metadata.loc[0, 'osc'] == 'OSC'
    assert metadata.loc[0, 'save_dir'] == str(destination)
    assert len(data) == 2
    assert waveform.history[0].loc[0, field] == initial
    assert waveform.history[1].loc[0, field] == updated
    assert waveform.history[0].loc[0, 'save_dir'] == str(tmp_path)
    assert not {'data', 'metadata', 'history'} & set(metadata)
