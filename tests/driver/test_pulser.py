"""
Consolidated Pulser Category Tests.

Covers:
- Base class, channel and parameter attributes, autodetect ID
- Automatic discovery of all Pulser drivers
- VirtualPulser state transitions, channel settings, and trigger modes
- BNC765 SCPI command generation and query parameter updates
"""

from unittest.mock import Mock
import pytest
from piec.drivers.pulser.pulser import Pulser
from piec.drivers.pulser.bnc765 import BNC765
from piec.drivers.pulser.virtual_pulser import VirtualPulser
from tests.support.driver_contracts import DriverCase, physical, virtual, case_for, assert_driver_contract
from tests.support.discovery import discover_driver_classes, discover_instrument_categories
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver

def pulser_outputs(instrument):
    instrument.output(1, True)
    if isinstance(instrument, VirtualPulser):
        enabled = instrument.state['output_on'][1]
        instrument.output(1, False)
        return enabled, instrument.state['output_on'][1]
    instrument.output(1, False)
    return tuple(instrument.instrument.writes)

# Independent device responses and expectations; discovery supplies the test inventory.
CASES = [
        DriverCase(BNC765, physical(BNC765), pulser_outputs, ('OUTPut1:STATe ON', 'OUTPut1:STATe OFF')),
        DriverCase(VirtualPulser, virtual(VirtualPulser), pulser_outputs, (True, False)),
    ]



ALL_PULSER_DRIVERS = discover_driver_classes()["pulser"]


# ============================================================================
# 1. Base Class & Driver Inventory Conformance
# ============================================================================

class TestPulserDiscovery:
    """Verify that all advertised and discovered pulser drivers conform to standards."""

    def test_discovery_and_registration(self):
        assert_all_drivers_registered('pulser', [case.cls for case in CASES])

    @pytest.mark.parametrize("driver_cls", ALL_PULSER_DRIVERS)
    def test_inherits_from_pulser(self, driver_cls):
        assert issubclass(driver_cls, Pulser)

    @pytest.mark.parametrize("driver_cls", ALL_PULSER_DRIVERS)
    def test_declares_channel_attribute(self, driver_cls):
        assert hasattr(driver_cls, "channel")
        assert len(driver_cls.channel) >= 1

    def test_bnc765_declares_autodetect_id(self):
        assert hasattr(BNC765, "AUTODETECT_ID")
        assert BNC765.AUTODETECT_ID == "BNC765"


# ============================================================================
# 2. VirtualPulser Contract Tests
# ============================================================================

class TestVirtualPulserContract:
    """Verify VirtualPulser parameter configuration and output toggling."""

    @pytest.fixture
    def v_pulser(self):
        return VirtualPulser()

    def test_initial_state(self, v_pulser):
        assert 1 in v_pulser.channel
        assert v_pulser.state["output_on"][1] is False
        assert v_pulser.state["trigger_source"] == "INT"
        assert v_pulser.state["trigger_mode"] == "CONT"

    def test_timing_configuration(self, v_pulser):
        v_pulser.set_period(1, 2e-3)
        assert v_pulser.state["period"][1] == 2e-3

        v_pulser.set_frequency(1, 1000.0)
        assert v_pulser.state["period"][1] == pytest.approx(1e-3)

        v_pulser.set_width(1, 5e-5)
        assert v_pulser.state["width"][1] == 5e-5

        v_pulser.set_delay(1, 1e-6)
        assert v_pulser.state["delay"][1] == 1e-6

        v_pulser.set_rise_time(1, 2e-9)
        assert v_pulser.state["rise_time"][1] == 2e-9

        v_pulser.set_fall_time(1, 3e-9)
        assert v_pulser.state["fall_time"][1] == 3e-9

    def test_voltage_levels_and_output(self, v_pulser):
        v_pulser.set_high_level(1, 2.5)
        assert v_pulser.state["high_level"][1] == 2.5

        v_pulser.set_low_level(1, -1.0)
        assert v_pulser.state["low_level"][1] == -1.0

        v_pulser.set_offset(1, 0.75)
        assert v_pulser.state["offset"][1] == 0.75

        v_pulser.output(1, True)
        assert v_pulser.state["output_on"][1] is True

        v_pulser.output(1, False)
        assert v_pulser.state["output_on"][1] is False

    def test_triggering_and_burst(self, v_pulser):
        v_pulser.set_trigger_source("EXT")
        assert v_pulser.state["trigger_source"].upper() == "EXT"

        v_pulser.set_trigger_mode("BURS")
        assert v_pulser.state["trigger_mode"].upper() == "BURS"

        v_pulser.set_burst_count(1, 50)
        assert v_pulser.state["burst_count"][1] == 50

        v_pulser.set_polarity(1, "INV")
        assert v_pulser.state["polarity"][1].upper() == "INV"


# ============================================================================
# 3. BNC765 SCPI Protocol Tests
# ============================================================================

class TestBNC765Commands:
    """Verify BNC765 SCPI command generation."""

    @pytest.fixture
    def bnc(self):
        responses = {
            "SOURce1:VOLTage:LEVel?": "1.0",
            "SOURce1:VOLTage:OFFSet?": "0.0",
        }
        inst = create_test_driver(BNC765, responses=responses)
        return inst

    def test_timing_commands(self, bnc):
        bnc.set_period(1, 1e-3)
        assert "SOURce1:FREQuency 1000.0" in bnc.instrument.writes

        bnc.set_frequency(1, 5000.0)
        assert "SOURce1:FREQuency 5000.0" in bnc.instrument.writes

        bnc.set_width(1, 2e-6)
        assert "SOURce1:PULSe:WIDTh 2e-06" in bnc.instrument.writes

        bnc.set_delay(1, 5e-7)
        assert "SOURce1:PULSe:DELay 5e-07" in bnc.instrument.writes

        bnc.set_rise_time(1, 1e-9)
        assert "SOURce1:PULSe:TRANsition:LEADing 1e-09" in bnc.instrument.writes

        bnc.set_fall_time(1, 2e-9)
        assert "SOURce1:PULSe:TRANsition:TRAiling 2e-09" in bnc.instrument.writes

    def test_voltage_level_commands(self, bnc):
        bnc.set_high_level(1, 3.0)
        assert any("SOURce1:VOLTage:LEVel" in w for w in bnc.instrument.writes)
        assert any("SOURce1:VOLTage:OFFSet" in w for w in bnc.instrument.writes)

        bnc.set_offset(1, 0.25)
        assert "SOURce1:VOLTage:OFFSet 0.25" in bnc.instrument.writes

    def test_output_and_trigger_commands(self, bnc):
        bnc.output(1, True)
        assert "OUTPut1:STATe ON" in bnc.instrument.writes

        bnc.output(1, False)
        assert "OUTPut1:STATe OFF" in bnc.instrument.writes

        bnc.set_trigger_source("INT")
        assert "TRIGger:SOURce INTERNAL" in bnc.instrument.writes

        bnc.set_trigger_mode("BURS")
        assert "TRIGger:MODe BURST" in bnc.instrument.writes

        bnc.set_burst_count(1, 25)
        assert "SOURce1:BURSt:NCYCles 25" in bnc.instrument.writes

        bnc.set_polarity(1, "INV")
        assert "SOURce1:INVert ON" in bnc.instrument.writes


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["pulser"], ids=lambda cls: cls.__name__)
def test_driver_contract(driver_cls):
    assert_driver_contract(driver_cls, discover_instrument_categories()["pulser"])


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["pulser"], ids=lambda cls: cls.__name__)
def test_driver_behavior(driver_cls, monkeypatch):
    case_for(driver_cls, CASES).check(monkeypatch, discover_instrument_categories()["pulser"])
