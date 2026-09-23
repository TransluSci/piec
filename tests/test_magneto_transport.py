"""Exercise magneto-transport metadata and the virtual AMR pipeline."""

import ast
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.amr import AMR, MagnetoTransport
from piec.simulation.magnetic_material import MagneticSample


@pytest.fixture
def instruments(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, '_shared_fe_sample', None)
    monkeypatch.setattr(VirtualInstrument, '_shared_mag_sample', MagneticSample())
    monkeypatch.setattr(np.random, 'normal', lambda *args: 0.0)
    monkeypatch.setattr('piec.measurement.magneto_transport.plt.show', lambda: None)
    elapsed = [0.0]

    def sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(
        'piec.measurement.magneto_transport.time',
        SimpleNamespace(time=lambda: elapsed[0], sleep=sleep),
    )
    return dict(dmm=VirtualDMM(), calibrator=VirtualCalibrator(),
                arduino=VirtualStepper(), lockin=VirtualLockin())


def test_magneto_transport_initializes_shared_metadata(instruments, tmp_path):
    experiment = MagnetoTransport(**instruments, field=100, save_dir=str(tmp_path), live_plot=False)
    assert experiment.history == []
    assert experiment.metadata.loc[0, 'field'] == 100
    assert experiment.metadata.loc[0, 'plot_config'] == {'x': 'angle', 'y': 'X'}
    for name, instrument in instruments.items():
        assert experiment.metadata.loc[0, name] == instrument.idn()


@pytest.mark.parametrize('live_plot', [False, True])
def test_amr_virtual_pipeline_refreshes_metadata_and_history(instruments, tmp_path, live_plot):
    experiment = AMR(
        **instruments, field=100, angle_step=90, total_angle=180,
        measure_time=0.15, frequency=17, save_dir=str(tmp_path),
        live_plot=live_plot, plot_config={'x': 'angle', 'y': 'Y'},
    )
    assert experiment.history == []
    assert experiment.metadata.loc[0, 'frequency'] == 17
    assert experiment.metadata.loc[0, 'angle_step'] == 90
    experiment.frequency = 23
    experiment.run_experiment(configure_lockin=live_plot)

    metadata, data = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, 'mtype'] == 'amr'
    assert metadata.loc[0, 'frequency'] == 23
    assert metadata.loc[0, 'field'] == 100
    assert metadata.loc[0, 'save_dir'] == str(tmp_path)
    assert ast.literal_eval(metadata.loc[0, 'plot_config']) == {'x': 'angle', 'y': 'Y'}
    for name, instrument in instruments.items():
        assert metadata.loc[0, name] == instrument.idn()
    assert not {'self', '__class__', 'data', 'metadata', 'history', '_fig', '_ax'} & set(metadata)
    assert data['angle'].tolist() == [0, 90, 180]
    assert data['field'].tolist() == [100, 100, 100]
    np.testing.assert_allclose(data['Y'], data['X'] / 10)
    assert np.isfinite(data.to_numpy()).all()
    assert instruments['calibrator'].mag_sample.current_field == 0
    assert len(experiment.history) == 1
    pd.testing.assert_frame_equal(experiment.history[0], experiment.metadata)

    experiment.frequency = 31
    experiment._update_metadata()
    assert experiment.history[0].loc[0, 'frequency'] == 23
    assert experiment.metadata.loc[0, 'frequency'] == 31
