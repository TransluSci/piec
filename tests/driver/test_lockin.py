"""
Consolidated Lock-In Amplifier Category Tests.

Covers:
- Base class, channel and parameter attributes, autodetect ID
- Automatic discovery of all Lock-In drivers
- VirtualLockin state management, excitation current, reader injection, and data readout
- SRS830 SCPI command generation, mapping lookup, and SNAP parsing
"""

import math
from unittest.mock import Mock
import numpy as np
import pytest
from piec.drivers.lockin.lockin import Lockin
from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from tests.support.driver_contracts import DriverCase, physical, virtual, case_for, assert_driver_contract
from tests.support.discovery import discover_driver_classes, discover_instrument_categories
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver

# Independent device responses and expectations; discovery supplies the test inventory.
CASES = [
        DriverCase(SRS830, physical(SRS830, {'SNAP? 1,2': '1.25,.5'}), lambda inst: tuple(inst.quick_read()), (1.25, .5)),
        DriverCase(VirtualLockin, virtual(VirtualLockin, xy_reader=lambda: (1.25, .5)), lambda inst: tuple(inst.quick_read()), (1.25, .5)),
    ]



ALL_LOCKIN_DRIVERS = discover_driver_classes()["lockin"]


def setup_srs830(responses=None):
    inst = create_test_driver(SRS830, responses=responses)
    inst._ref_src_map = {s.lower(): i for i, s in enumerate(inst.reference_source, 0)}
    inst._ref_src_map_inv = {i: s for s, i in inst._ref_src_map.items()}
    inst._in_config_map = {s.lower(): i for i, s in enumerate(inst.input_configuration, 0)}
    inst._in_config_map_inv = {i: s for s, i in inst._in_config_map.items()}
    inst._in_couple_map = {s.lower(): i for i, s in enumerate(inst.input_coupling, 0)}
    inst._in_couple_map_inv = {i: s for s, i in inst._in_couple_map.items()}
    inst._notch_map = {s.lower(): i for i, s in enumerate(inst.notch_filter, 0)}
    inst._notch_map_inv = {i: s for s, i in inst._notch_map.items()}
    inst._slope_map = {val: i for i, val in enumerate(inst.filter_slope, 0)}
    inst._slope_map_inv = {i: val for val, i in inst._slope_map.items()}
    inst._tc_map = {val: i for i, val in enumerate(inst.time_constant, 0)}
    inst._tc_map_inv = {i: val for val, i in inst._tc_map.items()}
    inst._sens_v_map = {val: i for i, val in enumerate(inst._sensitivity_v, 0)}
    inst._sens_i_map = {val: i for i, val in enumerate(inst._sensitivity_i, 0)}
    inst._current_input_config = "A"
    return inst


# ============================================================================
# 1. Base Class & Driver Inventory Conformance
# ============================================================================

class TestLockinDiscovery:
    """Verify that all advertised and discovered lockin drivers conform to standards."""

    def test_discovery_and_registration(self):
        assert_all_drivers_registered('lockin', [case.cls for case in CASES])

    @pytest.mark.parametrize("driver_cls", ALL_LOCKIN_DRIVERS)
    def test_inherits_from_lockin(self, driver_cls):
        assert issubclass(driver_cls, Lockin)

    @pytest.mark.parametrize("driver_cls", ALL_LOCKIN_DRIVERS)
    def test_declares_channel_attribute(self, driver_cls):
        assert hasattr(driver_cls, "channel")
        assert list(driver_cls.channel) == [1]

    def test_srs830_declares_autodetect_id(self):
        assert hasattr(SRS830, "AUTODETECT_ID")
        assert SRS830.AUTODETECT_ID == "SR830"


# ============================================================================
# 2. VirtualLockin Contract Tests
# ============================================================================

class TestVirtualLockinContract:
    """Verify VirtualLockin configuration, hook injection, and data extraction."""

    @pytest.fixture
    def v_lockin(self):
        return VirtualLockin()

    def test_initial_state(self, v_lockin):
        assert v_lockin.declared_units == {"x": "V", "y": "V", "excitation_current": "A"}
        assert v_lockin.excitation_current == 1e-6
        assert v_lockin.state["reference_frequency"] == 1000.0

    def test_configuration_commands(self, v_lockin):
        v_lockin.set_amplitude(0.5)
        assert v_lockin.state["reference_voltage"] == 0.5

        v_lockin.set_frequency(5000.0)
        assert v_lockin.state["reference_frequency"] == 5000.0

        v_lockin.configure_reference(phase=90.0)
        assert v_lockin.state["phase"] == 90.0

        v_lockin.configure_gain_filters(sensitivity=0.1, time_constant=0.03)
        assert v_lockin.state["sensitivity"] == 0.1
        assert v_lockin.state["time_constant"] == 0.03

    def test_excitation_current_validation(self, v_lockin):
        v_lockin.excitation_current = 2e-6
        assert v_lockin.excitation_current == 2e-6

        with pytest.raises(ValueError, match="must be finite"):
            v_lockin.excitation_current = float("inf")

    def test_hook_injection_and_readouts(self, v_lockin):
        v_lockin.set_xy_reader(lambda: (0.003, 0.004))

        xy = v_lockin.quick_read()
        assert xy == (pytest.approx(0.003), pytest.approx(0.004))

        assert v_lockin.get_X() == pytest.approx(0.003)
        assert v_lockin.get_Y() == pytest.approx(0.004)

        data = v_lockin.read_data()
        assert data["X"] == pytest.approx(0.003)
        assert data["Y"] == pytest.approx(0.004)
        assert data["R"] == pytest.approx(0.005)
        assert "Theta" in data

    def test_hook_with_excitation_current_arg(self, v_lockin):
        v_lockin.excitation_current = 1e-3
        v_lockin.set_xy_reader(lambda excitation_current: (excitation_current * 10, excitation_current * 20))
        assert v_lockin.get_X() == pytest.approx(0.01)
        assert v_lockin.get_Y() == pytest.approx(0.02)


# ============================================================================
# 3. SRS830 SCPI Command & Query Tests
# ============================================================================

class TestSRS830Commands:
    """Verify SRS830 command formatting, mapping lookups, and parsing."""

    @pytest.fixture
    def srs(self):
        return setup_srs830(responses={"ISRC?": "0"})

    def test_reference_commands(self, srs):
        srs.set_amplitude(1.5)
        assert "SLVL 1.5" in srs.instrument.writes

        srs.set_reference_frequency(1234.0)
        assert "FREQ 1234.0" in srs.instrument.writes

        srs.set_reference_source("internal")
        assert "FMOD 0" in srs.instrument.writes

        srs.set_phase(45.0)
        assert "PHAS 45.0" in srs.instrument.writes

        srs.set_harmonic(2)
        assert "HARM 2" in srs.instrument.writes

    def test_input_and_filter_commands(self, srs):
        srs.set_input_configuration("A")
        assert "ISRC 0" in srs.instrument.writes

        srs.set_input_coupling("AC")
        assert "ICPL 0" in srs.instrument.writes

        srs.set_sensitivity(1.0)
        assert "SENS 26" in srs.instrument.writes

        srs.set_time_constant(0.1)
        assert "OFLT 8" in srs.instrument.writes

        srs.set_filter_slope(12)
        assert "OFSL 1" in srs.instrument.writes

        srs.set_notch_filter("Out")
        assert "ILIN 0" in srs.instrument.writes

    def test_auto_commands(self, srs):
        srs.auto_gain()
        assert "AGAN" in srs.instrument.writes

        srs.auto_phase()
        assert "APHS" in srs.instrument.writes

    def test_read_queries(self, srs):
        srs.instrument.responses.update({
            "SNAP? 1,2": "1.23, 4.56",
            "SNAP? 1,2,3,4": "1.0, 2.0, 2.236, 63.4",
            "OUTP? 1": "1.23",
            "OUTP? 2": "4.56",
            "OUTP? 3": "4.72",
            "OUTP? 4": "74.9",
        })

        x, y = srs.quick_read()
        assert x == pytest.approx(1.23)
        assert y == pytest.approx(4.56)

        data = srs.read_data()
        assert data["X"] == pytest.approx(1.0)
        assert data["Y"] == pytest.approx(2.0)
        assert data["R"] == pytest.approx(2.236)
        assert data["Theta"] == pytest.approx(63.4)

        assert srs.get_X() == pytest.approx(1.23)
        assert srs.get_Y() == pytest.approx(4.56)
        assert srs.get_R() == pytest.approx(4.72)
        assert srs.get_theta() == pytest.approx(74.9)


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["lockin"], ids=lambda cls: cls.__name__)
def test_driver_contract(driver_cls):
    assert_driver_contract(driver_cls, discover_instrument_categories()["lockin"])


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["lockin"], ids=lambda cls: cls.__name__)
def test_driver_behavior(driver_cls, monkeypatch):
    case_for(driver_cls, CASES).check(monkeypatch, discover_instrument_categories()["lockin"])


@pytest.mark.parametrize("missing_attr", ["sensitivity", "time_constant", "notch_filter", "filter_slope"])
def test_child_missing_required_capability_fails_contract(missing_attr):
    """Concrete lockin drivers must not set required parent capabilities to None."""
    class IncompleteLockin(Lockin):
        channel = [1]
        input_coupling = ["AC", "DC"]
        frequency = (0.001, 100000.0)
        phase = (-180.0, 180.0)
        sensitivity = (1e-9, 1.0)
        time_constant = [1e-3, 10e-3]
        notch_filter = ["Out", "Line"]
        filter_slope = [6, 12, 18, 24]

    setattr(IncompleteLockin, missing_attr, None)
    with pytest.raises(AssertionError, match=f"IncompleteLockin.{missing_attr} is required by the parent and cannot be None"):
        assert_driver_contract(IncompleteLockin, Lockin)
