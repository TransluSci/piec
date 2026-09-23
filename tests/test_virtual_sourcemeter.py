import inspect
from pathlib import Path

import pytest

from piec.drivers.scpi import Scpi
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.iv_sweep import IVSweep
from piec.simulation.fe_material import Resistor


@pytest.fixture
def resistive_sourcemeter():
    original_sample = VirtualInstrument._shared_fe_sample
    sourcemeter = VirtualSourcemeter()
    sourcemeter.virtual_sample = Resistor(resistance=2000.0)
    try:
        yield sourcemeter
    finally:
        VirtualInstrument.set_virtual_sample(original_sample)


def test_virtual_sourcemeter_is_generic_not_scpi():
    assert not issubclass(VirtualSourcemeter, Scpi)


def test_virtual_sourcemeter_uses_external_resistive_sample(resistive_sourcemeter):
    resistive_sourcemeter.configure_voltage_source(
        voltage=1.0,
        current_compliance=0.1,
    )

    assert resistive_sourcemeter.get_voltage() == pytest.approx(1.0)
    assert resistive_sourcemeter.get_current() == pytest.approx(0.0005)
    assert resistive_sourcemeter.get_resistance() == pytest.approx(2000.0)
    assert resistive_sourcemeter.quick_read() == pytest.approx(2000.0)


def test_virtual_sourcemeter_respects_current_compliance(resistive_sourcemeter):
    resistive_sourcemeter.configure_voltage_source(
        voltage=10.0,
        current_compliance=0.001,
    )

    assert resistive_sourcemeter.get_current() == pytest.approx(0.001)


def test_virtual_sourcemeter_uses_sample_for_current_source(resistive_sourcemeter):
    resistive_sourcemeter.configure_current_source(
        current=0.002,
        voltage_compliance=10.0,
    )

    assert resistive_sourcemeter.get_current() == pytest.approx(0.002)
    assert resistive_sourcemeter.get_voltage() == pytest.approx(4.0)


def test_iv_sweep_uses_channel_aware_driver_interface(
    resistive_sourcemeter,
    tmp_path,
):
    experiment = IVSweep(
        sourcemeter=resistive_sourcemeter,
        v_start=0.0,
        v_stop=1.0,
        num_steps=3,
        current_compliance=0.1,
        dwell_time=0.0,
        sense_mode="2W",
        save_dir=str(tmp_path),
    )

    experiment.run_experiment()

    assert experiment.data["voltage (V)"].tolist() == pytest.approx(
        [0.0, 0.5, 1.0]
    )
    assert experiment.data["current (A)"].tolist() == pytest.approx(
        [0.0, 0.00025, 0.0005]
    )
    assert experiment.filename is not None
    assert Path(experiment.filename).exists()
    assert resistive_sourcemeter.state["output_on"] is False

    metadata, saved_data = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, 'mtype'] == 'iv_sweep'
    assert metadata.loc[0, 'sourcemeter'] == resistive_sourcemeter.idn()
    assert metadata.loc[0, 'num_steps'] == 3
    assert metadata.loc[0, 'save_dir'] == str(tmp_path)
    assert len(saved_data) == 3
    assert len(experiment.history) == 1
    assert not {'data', 'metadata', 'history'} & set(metadata)

    experiment.v_stop = 2.0
    experiment.run_experiment()
    metadata, saved_data = standard_csv_to_metadata_and_data(experiment.filename)
    assert metadata.loc[0, 'v_stop'] == 2.0
    assert saved_data['voltage (V)'].tolist() == pytest.approx([0, 1, 2])
    assert len(experiment.history) == 2
    assert experiment.history[0].loc[0, 'v_stop'] == 1.0
    assert experiment.history[1].loc[0, 'v_stop'] == 2.0


@pytest.mark.parametrize(
    "method_name",
    [
        "output",
        "set_source_function",
        "set_sense_function",
        "set_sense_mode",
        "set_source_voltage",
        "set_source_current",
        "set_voltage_compliance",
        "set_current_compliance",
        "configure_voltage_source",
        "configure_current_source",
        "quick_read",
        "get_voltage",
        "get_current",
    ],
)
def test_virtual_sourcemeter_matches_parent_signatures(method_name):
    assert inspect.signature(getattr(VirtualSourcemeter, method_name)) == inspect.signature(
        getattr(Sourcemeter, method_name)
    )
