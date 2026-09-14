"""
Tests for RF source instrument category.

Covers driver discovery/registration, capability declarations,
and VirtualRFSource operational contracts.
"""

import pytest
import warnings
from piec.drivers.rf_source.rf_source import RFSource
from piec.drivers.rf_source.virtual_rf_source import VirtualRFSource
from tests.support.driver_contracts import DriverCase, physical, virtual, case_for, assert_driver_contract
from tests.support.discovery import discover_driver_classes, discover_instrument_categories
from tests.support.discovery import assert_all_drivers_registered

def rf_frequency(instrument):
    instrument.set_frequency(2.4e9)
    return instrument.state['frequency']

# Independent device responses and expectations; discovery supplies the test inventory.
CASES = [DriverCase(VirtualRFSource, virtual(VirtualRFSource), rf_frequency, 2.4e9)]



# ============================================================================
# 1. Registration and Discovery Tests
# ============================================================================

class TestRFSourceDiscovery:
    """Verify RF source driver discovery, registration, and capabilities."""

    def test_discovery_and_registration(self):
        assert_all_drivers_registered('rf_source', [case.cls for case in CASES])

    def test_virtual_rf_source_inheritance(self):
        assert issubclass(VirtualRFSource, RFSource)

    def test_declares_capabilities(self):
        assert hasattr(VirtualRFSource, "channel")
        assert hasattr(VirtualRFSource, "frequency")
        assert hasattr(VirtualRFSource, "power")
        assert hasattr(VirtualRFSource, "modulation")
        assert isinstance(VirtualRFSource.channel, list)
        assert isinstance(VirtualRFSource.frequency, tuple)
        assert isinstance(VirtualRFSource.power, tuple)
        assert isinstance(VirtualRFSource.modulation, list)

    def test_legacy_import_deprecation(self):
        with pytest.deprecated_call(match="RF_source is deprecated"):
            import piec.drivers.rf_source.rf_source as mod
            _ = mod.RF_source


# ============================================================================
# 2. VirtualRFSource Contract Tests
# ============================================================================

class TestVirtualRFSourceContract:
    """Verify VirtualRFSource state tracking and behavior."""

    @pytest.fixture
    def rf(self):
        return VirtualRFSource()

    def test_initial_state(self, rf):
        assert rf.state["frequency"] == 1e9
        assert rf.state["power"] == -20.0
        assert rf.state["output_on"][1] is False
        assert rf.state["modulation_type"] == "AM"
        assert rf.state["modulation_enabled"] is False
        assert rf.state["reference_source"] == "INT"
        assert rf.state["sweep_mode"] == "LIN"

    def test_core_rf_output(self, rf):
        rf.set_frequency(2.4e9)
        assert rf.state["frequency"] == 2.4e9

        rf.set_power(10.0)
        assert rf.state["power"] == 10.0

        rf.output(1, True)
        assert rf.state["output_on"][1] is True

        rf.output(1, False)
        assert rf.state["output_on"][1] is False

    def test_modulation_controls(self, rf):
        rf.set_modulation("fm")
        assert rf.state["modulation_type"] == "FM"

        rf.enable_modulation(True)
        assert rf.state["modulation_enabled"] is True

        # AM parameters
        rf.set_am_depth(80.0)
        assert rf.state["am_depth"] == 80.0
        rf.set_am_frequency(5000.0)
        assert rf.state["am_frequency"] == 5000.0

        # FM parameters
        rf.set_fm_deviation(25000.0)
        assert rf.state["fm_deviation"] == 25000.0
        rf.set_fm_frequency(2000.0)
        assert rf.state["fm_frequency"] == 2000.0

        # PM / Pulse parameters
        rf.set_pulse_width(2e-6)
        assert rf.state["pulse_width"] == 2e-6
        rf.set_pulse_period(20e-6)
        assert rf.state["pulse_period"] == 20e-6

    def test_reference_source(self, rf):
        rf.set_reference_source("ext")
        assert rf.state["reference_source"] == "EXT"

    def test_frequency_sweep(self, rf):
        rf.set_sweep_start_frequency(100e6)
        assert rf.state["sweep_start_freq"] == 100e6

        rf.set_sweep_stop_frequency(2e9)
        assert rf.state["sweep_stop_freq"] == 2e9

        rf.set_sweep_points(501)
        assert rf.state["sweep_points"] == 501

        rf.set_sweep_mode("log")
        assert rf.state["sweep_mode"] == "LOG"

        rf.output_sweep(True)
        assert rf.state["sweep_output_on"] is True

    def test_scpi_commands_and_reset(self, rf):
        assert "Virtual_RF_Source" in rf.idn()
        assert rf.error() == "No errors."
        assert rf.self_test() == "0"
        assert rf.operation_complete() == "1"

        # Modify state, then reset
        rf.set_frequency(5e9)
        rf.output(1, True)
        rf.reset()
        assert rf.state["frequency"] == 1e9
        assert rf.state["output_on"][1] is False

        # initialize()
        rf.set_frequency(3e9)
        rf.initialize()
        assert rf.state["frequency"] == 1e9


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["rf_source"], ids=lambda cls: cls.__name__)
def test_driver_contract(driver_cls):
    assert_driver_contract(driver_cls, discover_instrument_categories()["rf_source"])


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["rf_source"], ids=lambda cls: cls.__name__)
def test_driver_behavior(driver_cls, monkeypatch):
    case_for(driver_cls, CASES).check(monkeypatch, discover_instrument_categories()["rf_source"])
