"""
Consolidated DC Calibrator Category Tests.

Covers:
- Base class, channel declaration, class attributes, autodetect ID
- Automatic discovery of all DC Calibrator drivers
- VirtualCalibrator state management, output hook injection, voltage/current sourcing
- EDC522 custom protocol command formatting, range selection, and crowbar
"""

import math
from unittest.mock import Mock
import pytest

from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.dc_calibrator.edc522 import EDC522
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator

from tests.support.driver_cases import DRIVER_CASES
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver


ALL_CALIBRATOR_DRIVERS = [case.cls for case in DRIVER_CASES['dc_calibrator']]


# ============================================================================
# 1. Base Class & Driver Inventory Conformance
# ============================================================================

class TestCalibratorDiscovery:
    """Verify that all advertised and discovered calibrator drivers conform to standards."""

    def test_discovery_and_registration(self):
        assert_all_drivers_registered("dc_calibrator", ALL_CALIBRATOR_DRIVERS)

    @pytest.mark.parametrize("driver_cls", ALL_CALIBRATOR_DRIVERS)
    def test_inherits_from_dc_calibrator(self, driver_cls):
        assert issubclass(driver_cls, DCCalibrator)

    @pytest.mark.parametrize("driver_cls", ALL_CALIBRATOR_DRIVERS)
    def test_declares_channel_attribute(self, driver_cls):
        assert hasattr(driver_cls, "channel")
        assert list(driver_cls.channel) == [1]

    def test_edc522_declares_autodetect_id(self):
        assert hasattr(EDC522, "AUTODETECT_ID")
        assert isinstance(EDC522.AUTODETECT_ID, list)
        assert "522" in EDC522.AUTODETECT_ID


# ============================================================================
# 2. VirtualCalibrator Contract Tests
# ============================================================================

class TestVirtualCalibratorContract:
    """Verify VirtualCalibrator output controls, hook injection, and unit declarations."""

    @pytest.fixture
    def v_cal(self):
        return VirtualCalibrator()

    def test_initial_state(self, v_cal):
        assert v_cal.declared_units == {"voltage": "V", "current": "A"}
        assert v_cal.state["output_on"] is True
        assert v_cal.state["voltage"] == 0.0
        assert v_cal.state["current"] == 0.0

    def test_set_voltage_and_current(self, v_cal):
        v_cal.set_voltage(5.0)
        assert v_cal.state["voltage"] == 5.0
        assert v_cal.state["mode"] == "voltage"

        v_cal.set_current(0.02)
        assert v_cal.state["current"] == 0.02
        assert v_cal.state["mode"] == "current"

    def test_output_enable_disable(self, v_cal):
        v_cal.output(False)
        assert v_cal.state["output_on"] is False

        v_cal.output(True)
        assert v_cal.state["output_on"] is True

    def test_hook_injection(self, v_cal):
        events = []
        v_cal.set_output_hook(lambda val, mode=None: events.append((val, mode)))

        v_cal.set_voltage(2.5)
        assert len(events) == 1
        assert events[0][0] == 2.5

    def test_non_finite_rejection(self, v_cal):
        with pytest.raises(ValueError, match="finite"):
            v_cal.set_voltage(float("inf"))
        with pytest.raises(ValueError, match="finite"):
            v_cal.set_voltage(float("nan"))

    def test_reset_preserves_hook(self, v_cal):
        hook = lambda val: None
        v_cal.set_output_hook(hook)
        v_cal.set_voltage(10.0)
        v_cal.reset()

        assert v_cal.state["voltage"] == 0.0
        assert v_cal.output_hook is hook


# ============================================================================
# 3. EDC522 Protocol Tests
# ============================================================================

class TestEDC522Protocol:
    """Verify EDC522 command construction, range selection, error and idn behavior."""

    @pytest.fixture
    def edc(self):
        inst = create_test_driver(EDC522)
        return inst

    def test_voltage_output_formatting(self, edc):
        # 5V is on the 10V range ('1'), positive ('+')
        cmd = edc.set_voltage(5.0)
        assert len(cmd) == 8
        assert "1" in cmd  # Range 1
        assert "+" in cmd
        assert cmd in edc.instrument.writes

        # Negative voltage
        cmd_neg = edc.set_voltage(-5.0)
        assert "-" in cmd_neg

    def test_current_output_formatting(self, edc):
        # 50 mA on 100mA range ('5')
        cmd = edc.set_current(0.05)
        assert len(cmd) == 8
        assert "5" in cmd
        assert cmd in edc.instrument.writes

    def test_crowbar_command(self, edc):
        cmd = edc.output(False)
        assert cmd == "00000000"
        assert "00000000" in edc.instrument.writes

    def test_voltage_range_limits(self, edc):
        with pytest.raises(ValueError, match="out of the instrument's range"):
            edc.set_voltage(150.0)  # Exceeds standard 100V limit

    def test_idn_and_error(self, edc):
        edc.instrument.read = Mock(return_value="NOTHING WRONG\r\n")
        assert edc.idn() == "KROHN-HITE, 522, VER GEO"
        assert "?" in edc.instrument.writes


@pytest.mark.parametrize("case", DRIVER_CASES['dc_calibrator'], ids=lambda case: case.cls.__name__)
def test_registered_driver_behavior(case, monkeypatch):
    """Every runtime registration executes an observable category operation."""
    case.check(monkeypatch)
