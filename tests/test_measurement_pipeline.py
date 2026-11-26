"""Integration tests covering full virtual-driver measurement CSV pipelines."""

import ast
import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.amr import AMR
from piec.measurement.discrete_waveform import HysteresisLoop, ThreePulsePund


def test_hysteresis_full_pipeline(tmp_path, monkeypatch):
    """Verify HysteresisLoop initialization, virtual capture, analysis, and CSV output."""
    monkeypatch.setattr(VirtualInstrument, "sample", None)
    loop = HysteresisLoop(
        awg=VirtualAwg(),
        osc=VirtualScope(),
        frequency=1000.0,
        amplitude=1.0,
        n_cycles=2,
        area=1.0e-5,
        show_plots=False,
        save_plots=False,
        save_dir=str(tmp_path),
    )

    assert loop.mtype == "hysteresis"
    assert loop.data is None
    assert loop.filename is None
    assert loop.history == []
    assert isinstance(loop.metadata, pd.DataFrame)
    assert float(loop.metadata["frequency"].iloc[0]) == pytest.approx(1000.0)
    assert float(loop.metadata["amplitude"].iloc[0]) == pytest.approx(1.0)

    loop.run_experiment()

    assert loop.filename is not None and os.path.isfile(loop.filename)
    assert os.path.getsize(loop.filename) > 0
    metadata, data = standard_csv_to_metadata_and_data(loop.filename)
    assert {"frequency", "amplitude", "area", "n_cycles", "time_offset"} <= set(metadata.columns)
    assert float(metadata["frequency"].iloc[0]) == pytest.approx(1000.0)
    assert float(metadata["amplitude"].iloc[0]) == pytest.approx(1.0)
    assert bool(metadata["processed"].iloc[0]) is True

    assert {"time (s)", "voltage (V)", "current (A)", "polarization (uC/cm^2)", "applied voltage (V)"} <= set(data.columns)
    assert len(data) > 0
    assert pd.api.types.is_numeric_dtype(data["time (s)"])
    assert pd.api.types.is_numeric_dtype(data["voltage (V)"])
    assert len(loop.history) == 1
    assert isinstance(loop.history[0], pd.DataFrame)


def test_pund_full_pipeline_preserves_metadata(tmp_path, monkeypatch):
    """Verify ThreePulsePund virtual capture, analysis, and metadata round-trip."""
    monkeypatch.setattr(VirtualInstrument, "sample", None)
    experiment = ThreePulsePund(
        awg=VirtualAwg(),
        osc=VirtualScope(),
        reset_amp=2.0,
        p_u_amp=1.5,
        show_plots=False,
        save_plots=False,
        save_dir=str(tmp_path),
    )
    experiment.run_experiment()

    metadata, data = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, "mtype"] == "3pulsepund"
    assert metadata.loc[0, "reset_amp"] == 2.0
    assert metadata.loc[0, "p_u_amp"] == 1.5
    assert metadata.loc[0, "length"] == pytest.approx(experiment.length)
    assert metadata.loc[0, "awg"] == experiment.awg.idn()
    assert metadata.loc[0, "osc"] == experiment.osc.idn()
    assert bool(metadata.loc[0, "processed"]) is True
    assert not data.empty
    assert {"current (A)", "polarization (uC/cm^2)", "applied voltage (V)"} <= set(data)
    assert len(experiment.history) == 1
    assert experiment.history[0].loc[0, "reset_amp"] == 2.0


def test_amr_virtual_pipeline(tmp_path, monkeypatch):
    """Verify virtual AMR sweep, CSV round-trip, and metadata/history snapshots."""
    monkeypatch.setattr(VirtualInstrument, "sample", None)
    monkeypatch.setattr(np.random, "normal", lambda *args: 0.0)
    elapsed = [0.0]

    def sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(
        "piec.measurement.magneto_transport.time",
        SimpleNamespace(time=lambda: elapsed[0], sleep=sleep),
    )
    instruments = dict(
        dmm=VirtualDMM(),
        calibrator=VirtualCalibrator(),
        arduino=VirtualStepper(),
        lockin=VirtualLockin(),
    )

    experiment = AMR(
        **instruments,
        field=100,
        angle_step=90,
        total_angle=180,
        measure_time=0.15,
        frequency=17,
        save_dir=str(tmp_path),
        live_plot=False,
        plot_config={"x": "angle", "y": "Y"},
    )
    assert experiment.history == []
    assert experiment.metadata.loc[0, "frequency"] == 17
    assert experiment.metadata.loc[0, "angle_step"] == 90

    experiment.frequency = 23
    experiment.run_experiment(configure_lockin=False)

    metadata, data = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, "mtype"] == "amr"
    assert metadata.loc[0, "frequency"] == 23
    assert metadata.loc[0, "field"] == 100
    assert metadata.loc[0, "save_dir"] == str(tmp_path)
    assert ast.literal_eval(metadata.loc[0, "plot_config"]) == {"x": "angle", "y": "Y"}
    for name, instrument in instruments.items():
        assert metadata.loc[0, name] == instrument.idn()
    assert not {"self", "__class__", "data", "metadata", "history", "_fig", "_ax"} & set(metadata)

    assert data["angle"].tolist() == [0, 90, 180]
    assert data["field"].tolist() == [100, 100, 100]
    np.testing.assert_allclose(data["Y"], data["X"] / 10)
    assert np.isfinite(data.to_numpy()).all()
    assert instruments["dmm"].get_voltage() == 0
    assert len(experiment.history) == 1
    pd.testing.assert_frame_equal(experiment.history[0], experiment.metadata)

    experiment.frequency = 31
    experiment._update_metadata()
    assert experiment.history[0].loc[0, "frequency"] == 23
    assert experiment.metadata.loc[0, "frequency"] == 31
