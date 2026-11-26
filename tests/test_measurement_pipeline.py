"""Dynamic contract tests for Experiment pipelines and HysteresisLoop reference."""

import importlib
import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import piec.measurement as measurement_pkg
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.drivers.autodetect import autodetect
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.virtual_dispatch import find_virtual_driver_class
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.discrete_waveform import HysteresisLoop
from piec.measurement.experiment import Experiment


_PARAM_ALIASES = {
    "osc": "oscilloscope",
    "arduino": "stepper_motor",
}


def discover_experiments():
    """Discover all concrete Experiment subclasses with a defined ``mtype``."""
    meas_dir = Path(measurement_pkg.__file__).resolve().parent
    experiments = []
    for path in sorted(meas_dir.glob("*.py")):
        if path.stem in {"__init__", "experiment", "gui_utils"} or path.stem.startswith("_"):
            continue
        module = importlib.import_module(f"piec.measurement.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__module__ == module.__name__
                and issubclass(obj, Experiment)
                and obj is not Experiment
                and obj.mtype is not None
            ):
                experiments.append(obj)
    return sorted(experiments, key=lambda cls: cls.__name__)


def _build_virtual_experiment(exp_cls, save_dir):
    """Instantiate an Experiment with matching VIRTUAL_* drivers and fast defaults."""
    defaults = {
        "save_dir": str(save_dir),
        "show_plots": False,
        "save_plots": False,
        "live_plot": False,
        "dwell_time": 0.0,
        "num_steps": 5,
        "points_per_cycle": 12,
        "angle_step": 90,
        "total_angle": 180,
        "measure_time": 0.05,
        "field": 100,
    }
    kwargs = {}
    for name, param in inspect.signature(exp_cls.__init__).parameters.items():
        if name == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        device_type = _PARAM_ALIASES.get(name, name)
        if find_virtual_driver_class(device_type) is not None:
            kwargs[name] = autodetect(f"VIRTUAL_{device_type}")
        elif name in defaults:
            kwargs[name] = defaults[name]
    return exp_cls(**kwargs)


@pytest.mark.parametrize("exp_cls", discover_experiments(), ids=lambda cls: cls.__name__)
def test_measurement_virtual_pipeline_contract(exp_cls, tmp_path, monkeypatch):
    """Verify every concrete Experiment runs virtually and produces valid PIEC CSV/DataFrames."""
    monkeypatch.setattr(VirtualInstrument, "sample", None)
    monkeypatch.setattr(np.random, "normal", lambda *args: 0.0)
    elapsed = [0.0]

    def _sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(
        "piec.measurement.magneto_transport.time",
        SimpleNamespace(time=lambda: elapsed[0], sleep=_sleep),
    )

    experiment = _build_virtual_experiment(exp_cls, tmp_path)
    experiment.run_experiment()

    assert isinstance(experiment.metadata, pd.DataFrame) and len(experiment.metadata) == 1
    assert isinstance(experiment.data, pd.DataFrame) and not experiment.data.empty
    assert experiment.filename is not None and os.path.isfile(experiment.filename)
    assert os.path.getsize(experiment.filename) > 0

    metadata, data = standard_csv_to_metadata_and_data(experiment.filename)
    assert isinstance(metadata, pd.DataFrame) and not metadata.empty
    assert isinstance(data, pd.DataFrame) and not data.empty
    assert metadata.loc[0, "mtype"] == exp_cls.mtype
    assert {"timestamp", "processed"} <= set(metadata.columns)
    for name in experiment._instruments:
        assert metadata.loc[0, name] == getattr(experiment, name).idn()

    numeric = data.select_dtypes(include=[np.number])
    assert not numeric.empty
    assert np.isfinite(numeric.to_numpy()).all()
    assert len(experiment.history) == 1
    assert isinstance(experiment.history[0], pd.DataFrame)


def test_hysteresis_full_pipeline(tmp_path, monkeypatch):
    """Legacy reference end-to-end check for HysteresisLoop formatting and analysis."""
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
