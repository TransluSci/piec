"""Contract tests for model-style virtual driver construction.

These tests intentionally describe the behavior implemented by the virtual
dispatch work: constructing a physical model with ``address="VIRTUAL"``
returns the matching category virtual driver, profiled with the model's
capability attributes.
"""

import pytest

from piec.drivers.awg.agilent_33220a import Agilent33220A
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.virtual_awg import VirtualAwg


def test_model_virtual_address_returns_virtual_awg_instance():
    awg = Keysight81150a("VIRTUAL")

    assert isinstance(awg, VirtualAwg)
    assert not isinstance(awg, Keysight81150a)


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
        "configure_output_amplifier",
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

    assert awg.emulated_driver_class is Keysight81150a
    assert awg.virtual_driver_class is VirtualAwg
