"""
Consolidated Sourcemeter Category Tests.

Covers physical drivers (Keithley 2400 via ScriptedTransport) and VirtualSourcemeter
across source/sense configuration, compliance limiting, reading, channel conventions,
and unconfirmed failure states.
"""

from __future__ import annotations

import inspect
import pytest

from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation.contracts import CapacitiveLoad, LoadResponse
from tests.support.driver_cases import DRIVER_CASES
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver

REGISTERED_SOURCEMETER_CLASSES = [case.cls for case in DRIVER_CASES['sourcemeter']]

LEVEL_2_SOURCEMETER_METHODS = [
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
    "get_resistance",
]


# ============================================================================
# 1. Discovery & Registration
# ============================================================================

def test_sourcemeter_driver_discovery():
    assert_all_drivers_registered("sourcemeter", REGISTERED_SOURCEMETER_CLASSES)


# ============================================================================
# 2. Surface & Channel Convention Contract
# ============================================================================

class TestSourcemeterSurfaceContract:
    @pytest.mark.parametrize("method_name", LEVEL_2_SOURCEMETER_METHODS)
    @pytest.mark.parametrize("cls", [Sourcemeter, VirtualSourcemeter, Keithley2400])
    def test_level_2_methods_exist_and_take_channel_1(self, cls, method_name):
        assert hasattr(cls, method_name)
        assert callable(getattr(cls, method_name))
        raw_func = getattr(cls, method_name)
        unwrapped = inspect.unwrap(raw_func)
        sig = inspect.signature(unwrapped)
        params = list(sig.parameters.values())
        assert len(params) >= 2
        assert params[0].name == "self"
        assert params[1].name == "channel"
        assert params[1].default == 1

    @pytest.mark.parametrize("cls", [VirtualSourcemeter, Keithley2400])
    @pytest.mark.parametrize("bad_channel", [0, 2, -1, 1.5, "1", None])
    def test_invalid_channel_rejected_before_mutation_or_io(self, cls, bad_channel):
        sm = create_test_driver(cls) if cls is Keithley2400 else cls()
        with pytest.raises((ValueError, TypeError)):
            sm.set_source_voltage(channel=bad_channel, voltage=1.0)
        if hasattr(sm, "instrument") and isinstance(sm.instrument, ScriptedTransport):
            assert sm.instrument.writes == []


# ============================================================================
# 3. Physical Driver: Keithley 2400 SCPI Commands & Parsing
# ============================================================================

class TestKeithley2400Commands:
    def test_output_commands(self):
        sm = create_test_driver(Keithley2400)
        sm.output(1, on=True)
        assert sm.instrument.writes[-1] == ":OUTP ON"
        sm.output(1, on=False)
        assert sm.instrument.writes[-1] == ":OUTP OFF"

    def test_source_and_sense_configuration(self):
        sm = create_test_driver(Keithley2400)
        sm.set_source_function(1, "VOLT")
        assert sm.instrument.writes[-1] == ":SOUR:FUNC VOLT"
        sm.set_source_function(1, "CURR")
        assert sm.instrument.writes[-1] == ":SOUR:FUNC CURR"

        sm.set_sense_function(1, "VOLT")
        assert sm.instrument.writes[-1] == ':SENS:FUNC "VOLTage"'
        sm.set_sense_function(1, "CURR")
        assert sm.instrument.writes[-1] == ':SENS:FUNC "CURRent"'
        sm.set_sense_function(1, "RES")
        assert sm.instrument.writes[-1] == ':SENS:FUNC "RESistance"'

        sm.set_sense_mode(1, "4W")
        assert sm.instrument.writes[-1] == ":SYST:RSEN ON"
        sm.set_sense_mode(1, "2W")
        assert sm.instrument.writes[-1] == ":SYST:RSEN OFF"

    def test_level_and_compliance_commands(self):
        sm = create_test_driver(Keithley2400)
        sm.set_source_voltage(1, 2.5)
        assert sm.instrument.writes[-1] == ":SOUR:VOLT:LEV 2.5"

        sm.set_source_current(1, 0.05)
        assert sm.instrument.writes[-1] == ":SOUR:CURR:LEV 0.05"

        sm.set_voltage_compliance(1, 10.0)
        assert sm.instrument.writes[-1] == ":SENS:VOLT:PROT 10.0"

        sm.set_current_compliance(1, 0.1)
        assert sm.instrument.writes[-1] == ":SENS:CURR:PROT 0.1"

    def test_read_parsing(self):
        # Keithley 2400 :READ? returns "voltage,current,resistance,timestamp,status"
        responses = {":READ?": "2.500000E+00,1.250000E-03,2.000000E+03,1.2345,0"}
        sm = create_test_driver(Keithley2400, responses=responses)
        assert sm.get_voltage() == pytest.approx(2.5)
        assert sm.get_current() == pytest.approx(0.00125)
        assert sm.get_resistance() == pytest.approx(2000.0)
        assert sm.quick_read() == pytest.approx(2.5)


# ============================================================================
# 4. VirtualSourcemeter Category Operations & Physics Decoupling
# ============================================================================

class TestVirtualSourcemeterCategory:
    def test_virtual_sourcemeter_source_and_sense_state(self):
        vsm = VirtualSourcemeter()
        vsm.set_source_function(1, "CURR")
        assert vsm.state["source_func"] == "CURR"
        vsm.set_source_voltage(1, 5.0)
        assert vsm.state["source_voltage"] == 5.0
        vsm.set_source_current(1, 0.02)
        assert vsm.state["source_current"] == 0.02
        vsm.set_voltage_compliance(1, 15.0)
        assert vsm.state["voltage_compliance"] == 15.0
        vsm.set_current_compliance(1, 0.05)
        assert vsm.state["current_compliance"] == 0.05

    def test_configured_vs_effective_output(self):
        vsm = VirtualSourcemeter()
        vsm.set_source_voltage(1, 5.0)
        # When output is disabled, effective values are 0.0
        assert vsm.effective_voltage == 0.0
        assert vsm.effective_current == 0.0
        vsm.output(1, on=True)
        assert vsm.effective_voltage == 5.0

    @pytest.mark.parametrize("read", [
        lambda s: s.get_voltage(),
        lambda s: s.get_current(),
        lambda s: s.get_resistance(),
        lambda s: s.quick_read(),
        lambda s: s.effective_voltage,
        lambda s: s.effective_current,
        lambda s: s.compliance_tripped,
        lambda s: s.query(":READ?"),
    ])
    def test_failed_shutdown_never_reads_as_confirmed_zero(self, read):
        error = ValueError("disconnected")
        def hook(output_on):
            if not output_on:
                raise error
            return 1.0, 0.001

        sm = VirtualSourcemeter(load_hook=hook)
        sm.output(on=True)
        with pytest.raises(ValueError) as caught:
            sm.output(on=False)
        assert caught.value is error
        with pytest.raises(RuntimeError, match="unconfirmed"):
            read(sm)

        sm.load_hook = lambda: (0.0, 0.0)
        sm.output(on=False)
        assert sm.effective_voltage == 0.0

    @pytest.mark.parametrize("response", [
        {"voltage": 2.0, "current": 1.0, "compliance_tripped": False},
        LoadResponse(voltage=2.0, current=1.0, compliance_tripped=True),
    ])
    def test_declared_compliance_flag_cannot_bypass_limit(self, response):
        sm = VirtualSourcemeter(load_hook=lambda: response)
        sm.configure_voltage_source(voltage=2.0, current_compliance=0.01)
        with pytest.raises(ValueError, match="exceeds compliance"):
            sm.output(on=True)

    def test_capacitor_uses_setup_clock_and_repeat_reads_share_sample(self):
        load = CapacitiveLoad(capacitance=1.0, leakage_resistance=1e9, start_time=10.0)
        sm = VirtualSourcemeter(load_hook=load)
        sm.configure_current_source(current=0.1, voltage_compliance=10.0)
        load.timebase.advance(1.0)
        sm.output(on=True)
        assert sm.get_voltage() == pytest.approx(0.1)
        assert sm.get_current() == pytest.approx(0.1)
        assert float(sm.query(":READ?").split(",")[0]) == pytest.approx(0.1)
        load.timebase.advance(1.0)
        assert sm.get_voltage() == pytest.approx(0.2)
        sm.reset()
        assert load.timebase.current_time == 12.0

    def test_scpi_numeric_output_and_callback_failure(self):
        def hook(stimulus):
            if stimulus == 2.0:
                raise ValueError("callback error")
            return stimulus, 0.001

        sm = VirtualSourcemeter(load_hook=hook)
        sm.write(":OUTP 1")
        assert sm.query(":OUTP?") == "1"
        with pytest.raises(ValueError, match="callback error"):
            sm.write(":SOUR:VOLT:LEV 2")
        assert sm.query(":OUTP?") == "UNKNOWN"
        sm.write(":OUTP 0")
        assert sm.query(":OUTP?") == "0"


@pytest.mark.parametrize("case", DRIVER_CASES['sourcemeter'], ids=lambda case: case.cls.__name__)
def test_registered_driver_behavior(case, monkeypatch):
    """Every runtime registration executes an observable category operation."""
    case.check(monkeypatch)
