"""Contract tests for model-style virtual driver construction.

These tests intentionally describe the behavior implemented by the virtual
dispatch work: constructing a physical model with ``address="VIRTUAL"``
returns the matching category virtual driver, profiled with the model's
capability attributes.
"""

import warnings

import pytest
import numpy as np

from piec.drivers.awg.agilent_33220a import Agilent33220A
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.sdg2000 import SDG2000X
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.daq.usb231 import USB231
from piec.drivers.daq.virtual_daq import VirtualDaq
from piec.drivers.dc_calibrator.edc522 import EDC522
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.instrument import Instrument
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.oscilloscope.lecroy_sda6020 import LeCroySDA6020
from piec.drivers.oscilloscope.tektronix_tds2000 import TektronixTDS2000
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.virtual_dispatch import (
    VirtualDriverDispatchError,
    VirtualDriverNotFoundError,
)
from piec.drivers.virtual_instrument import VirtualInstrument


def test_model_virtual_address_returns_virtual_awg_instance():
    awg = Keysight81150a("VIRTUAL")

    assert isinstance(awg, VirtualAwg)
    assert not isinstance(awg, Keysight81150a)


@pytest.mark.parametrize(
    ("model_class", "virtual_class"),
    [
        (Keysight81150a, VirtualAwg),
        (KeysightDSOX3024a, VirtualScope),
        (USB231, VirtualDaq),
        (EDC522, VirtualCalibrator),
    ],
)
def test_model_virtual_dispatch_across_representative_categories(
    model_class,
    virtual_class,
):
    instrument = model_class("VIRTUAL")

    assert isinstance(instrument, virtual_class)
    assert instrument.emulated_driver_class is model_class


@pytest.mark.parametrize(
    "address",
    ["VIRTUAL_AWG", "VIRTUAL_SCOPE", "VIRTUAL_NOT_A_REAL_CATEGORY"],
)
def test_model_constructor_rejects_category_virtual_addresses(address):
    with pytest.raises(VirtualDriverDispatchError, match="only address='VIRTUAL'"):
        Keysight81150a(address)


@pytest.mark.parametrize(
    "attribute",
    [
        "channel",
        "waveform",
        "frequency",
        "amplitude",
        "offset",
        "load_impedance",
        "source_impedance",
        "arb_data_range",
    ],
)
def test_model_virtual_class_preserves_model_capability_attributes(attribute):
    awg = Keysight81150a("VIRTUAL")

    assert isinstance(awg, VirtualAwg)
    assert getattr(type(awg), attribute) == getattr(Keysight81150a, attribute)


def test_model_virtual_driver_validates_capabilities_by_default():
    awg = Keysight81150a("VIRTUAL")

    assert awg.check_params is True
    assert awg.amplitude == (0, 5)
    with pytest.raises(ValueError, match="amplitude.*out of acceptable Range"):
        awg.set_amplitude(1, 15)

    assert awg.state["amplitude"][1] == 1.0
    assert awg._current_amplitude is None


def test_model_virtual_driver_validates_initial_hib_frequency_limits():
    awg = Keysight81150a("VIRTUAL")

    awg.set_waveform(1, "SIN")
    awg.set_frequency(1, 240e6)

    with pytest.raises(ValueError, match="frequency.*out of range"):
        awg.set_frequency(1, 240e6 + 1)

    assert awg.state["frequency"][1] == 240e6


def test_model_virtual_driver_can_explicitly_disable_validation():
    awg = Keysight81150a("VIRTUAL", check_params=False)

    awg.set_amplitude(1, 15)

    assert awg.check_params is False
    assert awg.state["amplitude"][1] == 15


def test_model_specific_optional_commands_are_not_added_to_virtual_class():
    awg = Keysight81150a("VIRTUAL")

    assert not hasattr(type(awg), "configure_output_amplifier")


def test_model_capabilities_are_applied_before_virtual_state_initialization():
    # Agilent33220A is single-channel while generic VirtualAwg is dual-channel.
    awg = Agilent33220A("VIRTUAL")

    assert awg.channel == [1]
    assert list(awg.state["output"]) == [1]
    assert list(awg.state["waveform"]) == [1]


def test_model_virtual_dispatch_skips_physical_model_constructor(monkeypatch):
    def physical_constructor_side_effect(*args, **kwargs):
        raise AssertionError("physical model constructor behavior was invoked")

    monkeypatch.setattr(
        Keysight81150a,
        "__init__",
        physical_constructor_side_effect,
    )

    awg = Keysight81150a("VIRTUAL")

    assert isinstance(awg, VirtualAwg)


def test_model_virtual_instance_uses_virtual_stateful_methods():
    awg = Keysight81150a("VIRTUAL")

    awg.set_frequency(channel=1, frequency=1234.0)

    assert awg.state["frequency"][1] == 1234.0


def test_model_virtual_dispatch_records_source_driver():
    awg = Keysight81150a("VIRTUAL")

    assert awg.is_profiled_virtual_driver is True
    assert awg.emulated_driver_class is Keysight81150a
    assert awg.virtual_driver_class is VirtualAwg


def test_direct_virtual_driver_is_not_marked_as_model_profiled():
    awg = VirtualAwg()

    assert awg.is_profiled_virtual_driver is False


def test_missing_category_virtual_driver_raises_contextual_error():
    class UnsupportedModel(Instrument):
        __module__ = "piec.drivers.unsupported.example"

    with pytest.raises(VirtualDriverNotFoundError) as exc_info:
        UnsupportedModel("VIRTUAL")

    error = exc_info.value
    assert error.model_class is UnsupportedModel
    assert error.category == "unsupported"
    assert "UnsupportedModel" in str(error)
    assert "unsupported" in str(error)


def test_awg_simulation_size_is_independent_of_model_arb_limit():
    awg = SDG2000X("VIRTUAL")

    assert awg.arb_data_range == SDG2000X.arb_data_range
    assert awg.arb_data_range[1] > awg.simulation_points
    assert len(awg.get_waveform(1)) == awg.simulation_points


def test_scope_simulation_size_is_independent_of_model_acquisition_limit():
    scope = LeCroySDA6020("VIRTUAL")

    assert scope.acquisition_points == LeCroySDA6020.acquisition_points
    assert scope.acquisition_points[1] > scope.simulation_points
    assert len(scope.quick_read()) == scope.simulation_points


def test_simulation_points_can_be_configured_without_changing_capabilities():
    awg = VirtualAwg(simulation_points=128)
    scope = VirtualScope(simulation_points=128)

    assert awg.simulation_points == 128
    assert len(awg.get_waveform(1)) == 128
    assert scope.simulation_points == 128
    assert len(scope.quick_read()) == 128


def test_scope_requested_points_are_bounded_by_simulation_capacity():
    scope = VirtualScope(simulation_points=128)

    scope.configure_acquisition(acquisition_points=64)
    assert len(scope.quick_read()) == 64

    scope.configure_acquisition(acquisition_points=1000000)
    assert len(scope.quick_read()) == 128


def test_scope_requested_points_do_not_warn_when_simulation_is_bounded():
    scope = VirtualScope(simulation_points=128)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scope.set_acquisition_points(
            VirtualInstrument.SIMULATION_POINTS_WARNING_THRESHOLD + 1
        )

    assert caught == []


def test_virtual_instruments_use_shared_simulation_default():
    assert VirtualInstrument.DEFAULT_SIMULATION_POINTS == 10000
    assert VirtualAwg().simulation_points == VirtualInstrument.DEFAULT_SIMULATION_POINTS
    assert VirtualScope().simulation_points == VirtualInstrument.DEFAULT_SIMULATION_POINTS


def test_simulation_points_are_initialized_for_all_virtual_instruments():
    daq = VirtualDaq(simulation_points=128)

    assert daq.simulation_points == 128


def test_virtual_daq_warns_for_large_explicit_scans(monkeypatch):
    monkeypatch.setattr(
        VirtualInstrument,
        "SIMULATION_POINTS_WARNING_THRESHOLD",
        10,
    )
    daq = VirtualDaq()

    with pytest.warns(RuntimeWarning, match="virtual DAQ scan"):
        data = daq.read_AI_scan(channel=0, points=11, rate=1000)

    assert len(data) == 11


def test_profiled_virtual_keeps_model_limit_separate_from_simulation_default():
    scope = TektronixTDS2000("VIRTUAL")

    assert scope.acquisition_points == TektronixTDS2000.acquisition_points
    assert scope.simulation_points == VirtualInstrument.DEFAULT_SIMULATION_POINTS


def test_large_virtual_input_warns_without_being_rejected():
    awg = VirtualAwg()
    data = np.zeros(VirtualInstrument.SIMULATION_POINTS_WARNING_THRESHOLD + 1)

    with pytest.warns(RuntimeWarning, match="exceeding the recommended"):
        awg.create_arb_waveform(channel=1, name="large", data=data)

    assert len(awg.state["arb_waveform"][1]) == len(data)
