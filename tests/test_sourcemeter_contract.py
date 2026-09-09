"""
Contract tests for Sourcemeter Level 2 source/sense surface and VirtualSourcemeter channel alignment.

Stage 0 Checkpoint 5: VirtualSourcemeter channel contract alignment.
"""

import inspect
from unittest.mock import Mock

import pytest

from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter


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


class TestSourcemeterSurfaceContract:
    """Audit the Level 2 source/sense surface across all sourcemeter drivers."""

    @pytest.mark.parametrize("method_name", LEVEL_2_SOURCEMETER_METHODS)
    @pytest.mark.parametrize("cls", [Sourcemeter, VirtualSourcemeter, Keithley2400])
    def test_level_2_method_exists_and_is_callable(self, cls, method_name):
        """Every sourcemeter class must expose all Level 2 methods as callables."""
        assert hasattr(cls, method_name), f"{cls.__name__} missing method {method_name}"
        assert callable(getattr(cls, method_name)), f"{cls.__name__}.{method_name} is not callable"

    @pytest.mark.parametrize("method_name", LEVEL_2_SOURCEMETER_METHODS)
    @pytest.mark.parametrize("cls", [Sourcemeter, VirtualSourcemeter, Keithley2400])
    def test_level_2_method_channel_parameter_convention(self, cls, method_name):
        """Every Level 2 method must accept channel as its first parameter with default value 1."""
        raw_func = getattr(cls, method_name)
        unwrapped = inspect.unwrap(raw_func)
        sig = inspect.signature(unwrapped)
        params = list(sig.parameters.values())

        assert len(params) >= 2, f"{cls.__name__}.{method_name} must have self and channel parameters"
        assert params[0].name == "self"
        assert params[1].name == "channel", (
            f"{cls.__name__}.{method_name} first parameter after self must be 'channel', got '{params[1].name}'"
        )
        assert params[1].default == 1, (
            f"{cls.__name__}.{method_name} 'channel' parameter must have default 1, got {params[1].default}"
        )


class TestVirtualSourcemeterChannelContract:
    """Verify VirtualSourcemeter behavior with channel keywords, defaults, and legacy calls."""

    @pytest.fixture
    def vsm(self):
        """Create a clean VirtualSourcemeter instance."""
        return VirtualSourcemeter()

    # --- 1. Explicit channel keyword calls ---

    def test_output_explicit_channel_keyword(self, vsm):
        """output accepts channel=1 explicitly."""
        vsm.output(channel=1, on=True)
        assert vsm.state["output_on"] is True
        vsm.output(channel=1, on=False)
        assert vsm.state["output_on"] is False

    def test_set_source_function_explicit_channel_keyword(self, vsm):
        """set_source_function accepts channel=1 explicitly."""
        vsm.set_source_function(channel=1, source_func="CURR")
        assert vsm.state["source_func"] == "CURR"
        vsm.set_source_function(channel=1, source_func="VOLT")
        assert vsm.state["source_func"] == "VOLT"

    def test_set_sense_function_explicit_channel_keyword(self, vsm):
        """set_sense_function accepts channel=1 explicitly."""
        vsm.set_sense_function(channel=1, sense_func="CURR")
        assert vsm.state["sense_func"] == "CURR"
        vsm.set_sense_function(channel=1, sense_func="RES")
        assert vsm.state["sense_func"] == "RES"

    def test_set_sense_mode_explicit_channel_keyword(self, vsm):
        """set_sense_mode accepts channel=1 explicitly."""
        vsm.set_sense_mode(channel=1, sense_mode="4W")
        assert vsm.state["sense_mode"] == "4W"
        vsm.set_sense_mode(channel=1, sense_mode="2W")
        assert vsm.state["sense_mode"] == "2W"

    def test_set_source_voltage_explicit_channel_keyword(self, vsm):
        """set_source_voltage accepts channel=1 explicitly."""
        vsm.set_source_voltage(channel=1, voltage=7.5)
        assert vsm.state["source_voltage"] == 7.5

    def test_set_source_current_explicit_channel_keyword(self, vsm):
        """set_source_current accepts channel=1 explicitly."""
        vsm.set_source_current(channel=1, current=0.025)
        assert vsm.state["source_current"] == 0.025

    def test_set_voltage_compliance_explicit_channel_keyword(self, vsm):
        """set_voltage_compliance accepts channel=1 explicitly."""
        vsm.set_voltage_compliance(channel=1, voltage_compliance=42.0)
        assert vsm.state["voltage_compliance"] == 42.0

    def test_set_current_compliance_explicit_channel_keyword(self, vsm):
        """set_current_compliance accepts channel=1 explicitly."""
        vsm.set_current_compliance(channel=1, current_compliance=0.25)
        assert vsm.state["current_compliance"] == 0.25

    def test_configure_voltage_source_explicit_channel_keyword(self, vsm):
        """configure_voltage_source accepts channel=1 explicitly."""
        vsm.configure_voltage_source(channel=1, voltage=3.3, current_compliance=0.05)
        assert vsm.state["source_func"] == "VOLT"
        assert vsm.state["source_voltage"] == 3.3
        assert vsm.state["current_compliance"] == 0.05

    def test_configure_current_source_explicit_channel_keyword(self, vsm):
        """configure_current_source accepts channel=1 explicitly."""
        vsm.configure_current_source(channel=1, current=0.002, voltage_compliance=15.0)
        assert vsm.state["source_func"] == "CURR"
        assert vsm.state["source_current"] == 0.002
        assert vsm.state["voltage_compliance"] == 15.0

    def test_getters_explicit_channel_keyword(self, vsm):
        """quick_read, get_voltage, get_current, get_resistance accept channel=1 explicitly."""
        vsm.set_source_voltage(channel=1, voltage=5.0)
        vsm.set_source_current(channel=1, current=0.01)

        vsm.set_sense_function(channel=1, sense_func="VOLT")
        assert vsm.quick_read(channel=1) == 5.0
        assert vsm.get_voltage(channel=1) == 5.0

        vsm.set_sense_function(channel=1, sense_func="CURR")
        assert vsm.quick_read(channel=1) == 0.01
        assert vsm.get_current(channel=1) == 0.01

        vsm.set_sense_function(channel=1, sense_func="RES")
        assert vsm.quick_read(channel=1) == 500.0
        assert vsm.get_resistance(channel=1) == 500.0

    # --- 2. Default channel (omitted) calls ---

    def test_default_channel_when_omitted(self, vsm):
        """Calling Level 2 methods without channel defaults to channel 1."""
        vsm.output(on=True)
        assert vsm.state["output_on"] is True

        vsm.set_source_function(source_func="VOLT")
        assert vsm.state["source_func"] == "VOLT"

        vsm.set_source_voltage(voltage=1.5)
        assert vsm.state["source_voltage"] == 1.5

        vsm.set_current_compliance(current_compliance=0.1)
        assert vsm.state["current_compliance"] == 0.1

        vsm.configure_voltage_source(voltage=2.0, current_compliance=0.2)
        assert vsm.state["source_voltage"] == 2.0
        assert vsm.state["current_compliance"] == 0.2

        assert vsm.get_voltage() == 2.0
        assert vsm.quick_read() == 2.0
        assert vsm.get_current() == 0.0

        vsm.output(on=False)
        assert vsm.state["output_on"] is False

    # --- 3. Old positional calls remain unchanged ---

    def test_legacy_positional_calls_preserved(self, vsm):
        """Single-argument and legacy positional calls continue to work seamlessly."""
        # output(bool)
        vsm.output(True)
        assert vsm.state["output_on"] is True
        vsm.output(False)
        assert vsm.state["output_on"] is False

        # set_source_function(source_func)
        vsm.set_source_function("CURR")
        assert vsm.state["source_func"] == "CURR"

        # set_sense_function(sense_func)
        vsm.set_sense_function("RES")
        assert vsm.state["sense_func"] == "RES"

        # set_sense_mode(sense_mode)
        vsm.set_sense_mode("4W")
        assert vsm.state["sense_mode"] == "4W"

        # set_source_voltage(voltage)
        vsm.set_source_voltage(4.2)
        assert vsm.state["source_voltage"] == 4.2

        # set_source_current(current)
        vsm.set_source_current(0.007)
        assert vsm.state["source_current"] == 0.007

        # set_voltage_compliance(voltage_compliance)
        vsm.set_voltage_compliance(30.0)
        assert vsm.state["voltage_compliance"] == 30.0

        # set_current_compliance(current_compliance)
        vsm.set_current_compliance(0.4)
        assert vsm.state["current_compliance"] == 0.4

    # --- 4. Safety-critical output-disable path ---

    def test_safety_critical_output_disable_surface(self, vsm):
        """Every disable variation safely and unambiguously turns off the output."""
        # 1. output(on=False)
        vsm.output(on=True)
        vsm.output(on=False)
        assert vsm.state["output_on"] is False

        # 2. output(channel=1, on=False)
        vsm.output(channel=1, on=True)
        vsm.output(channel=1, on=False)
        assert vsm.state["output_on"] is False

        # 3. output(False)
        vsm.output(True)
        vsm.output(False)
        assert vsm.state["output_on"] is False

        # 4. output(1, False)
        vsm.output(1, True)
        vsm.output(1, False)
        assert vsm.state["output_on"] is False

    # --- 5. Channel validation and invalid channel rejection ---

    @pytest.mark.parametrize("bad_channel", [0, 2, -1, 99, "CH2"])
    def test_invalid_channel_rejected_with_value_error(self, vsm, bad_channel):
        """Calling any Level 2 method with an unsupported channel raises ValueError."""
        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.output(channel=bad_channel, on=False)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_source_function(channel=bad_channel, source_func="VOLT")

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_sense_function(channel=bad_channel, sense_func="CURR")

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_sense_mode(channel=bad_channel, sense_mode="2W")

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_source_voltage(channel=bad_channel, voltage=1.0)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_source_current(channel=bad_channel, current=0.01)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_voltage_compliance(channel=bad_channel, voltage_compliance=10.0)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.set_current_compliance(channel=bad_channel, current_compliance=0.1)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.configure_voltage_source(channel=bad_channel, voltage=1.0, current_compliance=0.1)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.configure_current_source(channel=bad_channel, current=0.01, voltage_compliance=10.0)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.quick_read(channel=bad_channel)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.get_voltage(channel=bad_channel)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.get_current(channel=bad_channel)

        with pytest.raises(ValueError, match=r"Invalid channel"):
            vsm.get_resistance(channel=bad_channel)


class TestKeithley2400Contract:
    """Verify Keithley2400 concrete driver compliance with channel keywords and safety disable."""

    @pytest.fixture
    def k2400(self):
        """Create a Keithley2400 instance with mocked VISA transport."""
        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        return inst

    def test_output_disable_commands(self, k2400):
        """output disable generates :OUTP OFF via all call conventions."""
        k2400.output(channel=1, on=False)
        k2400.instrument.write.assert_called_with(":OUTP OFF")

        k2400.output(on=False)
        k2400.instrument.write.assert_called_with(":OUTP OFF")

        k2400.output(1, False)
        k2400.instrument.write.assert_called_with(":OUTP OFF")

        # When check_params is False, legacy boolean output(False) safely writes :OUTP OFF
        k2400.check_params = False
        k2400.output(False)
        k2400.instrument.write.assert_called_with(":OUTP OFF")

        # When check_params is True, normalized arguments safely write :OUTP OFF without raising
        k2400.instrument.write.reset_mock()
        k2400.check_params = True
        k2400.output(False)
        k2400.instrument.write.assert_called_with(":OUTP OFF")

    def test_output_enable_commands(self, k2400):
        """output enable generates :OUTP ON."""
        k2400.output(channel=1, on=True)
        k2400.instrument.write.assert_called_with(":OUTP ON")

        k2400.output(on=True)
        k2400.instrument.write.assert_called_with(":OUTP ON")

        k2400.output(1, True)
        k2400.instrument.write.assert_called_with(":OUTP ON")

    def test_output_invalid_channel_rejected(self, k2400):
        """Keithley2400 output rejects invalid channels."""
        with pytest.raises(ValueError, match=r"(Invalid channel|not in list of acceptable)"):
            k2400.output(channel=2, on=False)

    def test_level_2_commands(self, k2400):
        """Level 2 methods write standard SCPI commands with channel=1 keyword."""
        k2400.set_source_function(channel=1, source_func="VOLT")
        k2400.instrument.write.assert_called_with(":SOUR:FUNC VOLT")

        k2400.set_sense_function(channel=1, sense_func="CURR")
        k2400.instrument.write.assert_called_with(':SENS:FUNC "CURRent"')

        k2400.set_sense_mode(channel=1, sense_mode="4W")
        k2400.instrument.write.assert_called_with(":SYST:RSEN ON")

        k2400.set_source_voltage(channel=1, voltage=2.5)
        k2400.instrument.write.assert_called_with(":SOUR:VOLT:LEV 2.5")

        k2400.set_source_current(channel=1, current=0.01)
        k2400.instrument.write.assert_called_with(":SOUR:CURR:LEV 0.01")

        k2400.set_voltage_compliance(channel=1, voltage_compliance=25.0)
        k2400.instrument.write.assert_called_with(":SENS:VOLT:PROT 25.0")

        k2400.set_current_compliance(channel=1, current_compliance=0.05)
        k2400.instrument.write.assert_called_with(":SENS:CURR:PROT 0.05")

        # configure_voltage_source
        k2400.configure_voltage_source(channel=1, voltage=1.0, current_compliance=0.1)
        k2400.instrument.write.assert_any_call(":SOUR:FUNC VOLT")
        k2400.instrument.write.assert_any_call(":SOUR:VOLT:LEV 1.0")
        k2400.instrument.write.assert_any_call(":SENS:CURR:PROT 0.1")

        # configure_current_source
        k2400.configure_current_source(channel=1, current=0.02, voltage_compliance=50.0)
        k2400.instrument.write.assert_any_call(":SOUR:FUNC CURR")
        k2400.instrument.write.assert_any_call(":SOUR:CURR:LEV 0.02")
        k2400.instrument.write.assert_any_call(":SENS:VOLT:PROT 50.0")

    def test_getters_query_read(self, k2400):
        """get_voltage, get_current, get_resistance query :READ?."""
        k2400.instrument.query.return_value = "1.234000E+00,5.678000E-03,2.173000E+02,0.0,0"

        v = k2400.get_voltage(channel=1)
        assert v == pytest.approx(1.234)

        i = k2400.get_current(channel=1)
        assert i == pytest.approx(5.678e-3)

        r = k2400.get_resistance(channel=1)
        assert r == pytest.approx(217.3)


class TestProfiledVirtualSourcemeterContract:
    """Verify that constructor-dispatched Keithley2400(address='VIRTUAL') complies with channel contract."""

    def test_profiled_virtual_satisfies_channel_contract(self):
        """Keithley2400(address='VIRTUAL') inherits aligned VirtualSourcemeter channel handling."""
        vsm = Keithley2400(address="VIRTUAL")

        # Disable via keyword
        vsm.output(channel=1, on=False)
        assert vsm.state["output_on"] is False

        # Configure via keyword
        vsm.configure_voltage_source(channel=1, voltage=1.2, current_compliance=0.05)
        assert vsm.state["source_voltage"] == 1.2
        assert vsm.state["current_compliance"] == 0.05

        # Getters via keyword
        assert vsm.get_voltage(channel=1) == 1.2
        assert vsm.get_current(channel=1) == 0.0

        # Invalid channel raises
        with pytest.raises(ValueError, match=r"(Invalid channel|not in list of acceptable)"):
            vsm.output(channel=2, on=False)


class TestLegacyAndCheckParamsNormalization:
    """Verify that legacy positional arguments work seamlessly with check_params=True and False."""

    @pytest.mark.parametrize("check_params", [False, True])
    def test_virtual_sourcemeter_legacy_calls_with_check_params(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params

        # output(False)
        vsm.output(True)
        assert vsm.state["output_on"] is True
        vsm.output(False)
        assert vsm.state["output_on"] is False

        # set_source_voltage(4.2)
        vsm.set_source_voltage(4.2)
        assert vsm.state["source_voltage"] == 4.2

        # set_source_current(0.015)
        vsm.set_source_current(0.015)
        assert vsm.state["source_current"] == 0.015

        # set_voltage_compliance(50.0)
        vsm.set_voltage_compliance(50.0)
        assert vsm.state["voltage_compliance"] == 50.0

        # set_current_compliance(0.2)
        vsm.set_current_compliance(0.2)
        assert vsm.state["current_compliance"] == 0.2

        # set_source_function("VOLT") / ("CURR")
        vsm.set_source_function("CURR")
        assert vsm.state["source_func"] == "CURR"
        vsm.set_source_function("VOLT")
        assert vsm.state["source_func"] == "VOLT"

        # set_sense_function("CURR") / ("RES")
        vsm.set_sense_function("CURR")
        assert vsm.state["sense_func"] == "CURR"
        vsm.set_sense_function("RES")
        assert vsm.state["sense_func"] == "RES"

        # set_sense_mode("4W") / ("2W")
        vsm.set_sense_mode("4W")
        assert vsm.state["sense_mode"] == "4W"
        vsm.set_sense_mode("2W")
        assert vsm.state["sense_mode"] == "2W"

    @pytest.mark.parametrize("check_params", [False, True])
    def test_keithley2400_legacy_calls_with_check_params(self, check_params):
        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params

        # output(False)
        inst.output(False)
        inst.instrument.write.assert_called_with(":OUTP OFF")

        # set_source_voltage(4.2)
        inst.set_source_voltage(4.2)
        inst.instrument.write.assert_called_with(":SOUR:VOLT:LEV 4.2")

        # set_source_current(0.015)
        inst.set_source_current(0.015)
        inst.instrument.write.assert_called_with(":SOUR:CURR:LEV 0.015")

        # set_voltage_compliance(50.0)
        inst.set_voltage_compliance(50.0)
        inst.instrument.write.assert_called_with(":SENS:VOLT:PROT 50.0")

        # set_current_compliance(0.2)
        inst.set_current_compliance(0.2)
        inst.instrument.write.assert_called_with(":SENS:CURR:PROT 0.2")

        # set_source_function("VOLT")
        inst.set_source_function("VOLT")
        inst.instrument.write.assert_called_with(":SOUR:FUNC VOLT")

        # set_sense_function("CURR")
        inst.set_sense_function("CURR")
        inst.instrument.write.assert_called_with(':SENS:FUNC "CURRent"')

        # set_sense_mode("4W")
        inst.set_sense_mode("4W")
        inst.instrument.write.assert_called_with(":SYST:RSEN ON")


class TestMissingValuesAndChannelRejection:
    """Verify that omitted values and invalid channels raise without changing state or writing commands."""

    @pytest.mark.parametrize("check_params", [False, True])
    def test_virtual_sourcemeter_rejects_missing_values_without_state_change(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params

        # Establish baseline state
        vsm.set_source_voltage(channel=1, voltage=5.0)
        vsm.set_source_current(channel=1, current=0.01)
        vsm.set_voltage_compliance(channel=1, voltage_compliance=30.0)
        vsm.set_current_compliance(channel=1, current_compliance=0.1)

        # set_source_voltage() must NOT program 1 V or change state
        with pytest.raises(ValueError):
            vsm.set_source_voltage()
        assert vsm.state["source_voltage"] == 5.0

        # set_source_voltage(channel=99) must NOT program 99 V or change state
        with pytest.raises(ValueError):
            vsm.set_source_voltage(channel=99)
        assert vsm.state["source_voltage"] == 5.0

        # set_source_voltage(channel=1) without voltage must raise and leave state unchanged
        with pytest.raises(ValueError):
            vsm.set_source_voltage(channel=1)
        assert vsm.state["source_voltage"] == 5.0

        # Current setters
        with pytest.raises(ValueError):
            vsm.set_source_current()
        assert vsm.state["source_current"] == 0.01
        with pytest.raises(ValueError):
            vsm.set_source_current(channel=99)
        assert vsm.state["source_current"] == 0.01

        # Compliance setters
        with pytest.raises(ValueError):
            vsm.set_voltage_compliance()
        assert vsm.state["voltage_compliance"] == 30.0
        with pytest.raises(ValueError):
            vsm.set_voltage_compliance(channel=99)
        assert vsm.state["voltage_compliance"] == 30.0

        with pytest.raises(ValueError):
            vsm.set_current_compliance()
        assert vsm.state["current_compliance"] == 0.1
        with pytest.raises(ValueError):
            vsm.set_current_compliance(channel=99)
        assert vsm.state["current_compliance"] == 0.1

        # Mode and function setters
        with pytest.raises(ValueError):
            vsm.set_source_function()
        with pytest.raises(ValueError):
            vsm.set_source_function(channel=99)
        with pytest.raises(ValueError):
            vsm.set_sense_function()
        with pytest.raises(ValueError):
            vsm.set_sense_function(channel=99)
        with pytest.raises(ValueError):
            vsm.set_sense_mode()
        with pytest.raises(ValueError):
            vsm.set_sense_mode(channel=99)

    @pytest.mark.parametrize("check_params", [False, True])
    def test_keithley2400_rejects_missing_values_without_transport_write(self, check_params):
        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params

        # set_source_voltage()
        with pytest.raises(ValueError):
            inst.set_source_voltage()
        inst.instrument.write.assert_not_called()

        # set_source_voltage(channel=99)
        with pytest.raises(ValueError):
            inst.set_source_voltage(channel=99)
        inst.instrument.write.assert_not_called()

        # set_source_current()
        with pytest.raises(ValueError):
            inst.set_source_current()
        inst.instrument.write.assert_not_called()

        # set_voltage_compliance()
        with pytest.raises(ValueError):
            inst.set_voltage_compliance()
        inst.instrument.write.assert_not_called()

        # set_current_compliance()
        with pytest.raises(ValueError):
            inst.set_current_compliance()
        inst.instrument.write.assert_not_called()

        # set_source_function()
        with pytest.raises(ValueError):
            inst.set_source_function()
        inst.instrument.write.assert_not_called()

        # set_sense_function()
        with pytest.raises(ValueError):
            inst.set_sense_function()
        inst.instrument.write.assert_not_called()

        # set_sense_mode()
        with pytest.raises(ValueError):
            inst.set_sense_mode()
        inst.instrument.write.assert_not_called()

    @pytest.mark.parametrize("check_params", [False, True])
    def test_invalid_channels_with_values_rejected_without_side_effects(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        vsm.set_source_voltage(channel=1, voltage=2.0)

        # Calling with invalid channel must raise and NOT modify state
        with pytest.raises(ValueError):
            vsm.set_source_voltage(channel=99, voltage=10.0)
        assert vsm.state["source_voltage"] == 2.0

        with pytest.raises(ValueError):
            vsm.set_source_current(channel=99, current=0.05)

        with pytest.raises(ValueError):
            vsm.set_voltage_compliance(channel=99, voltage_compliance=50.0)

        with pytest.raises(ValueError):
            vsm.set_current_compliance(channel=99, current_compliance=0.5)

        # Keithley2400 must NOT issue transport writes for invalid channel
        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params

        with pytest.raises(ValueError):
            inst.set_source_voltage(channel=99, voltage=10.0)
        inst.instrument.write.assert_not_called()

        with pytest.raises(ValueError):
            inst.set_source_current(channel=99, current=0.05)
        inst.instrument.write.assert_not_called()

        with pytest.raises(ValueError):
            inst.set_voltage_compliance(channel=99, voltage_compliance=50.0)
        inst.instrument.write.assert_not_called()

        with pytest.raises(ValueError):
            inst.set_current_compliance(channel=99, current_compliance=0.5)
        inst.instrument.write.assert_not_called()


class TestLegacyConfigurationCalls:
    """Verify that configure_voltage_source and configure_current_source preserve legacy meanings."""

    @pytest.mark.parametrize("check_params", [False, True])
    def test_configure_voltage_source_legacy_positional(self, check_params):
        # configure_voltage_source(1.0, 0.05) -> 1.0 V, 0.05 A compliance
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        vsm.configure_voltage_source(1.0, 0.05)
        assert vsm.state["source_func"] == "VOLT"
        assert vsm.state["source_voltage"] == 1.0
        assert vsm.state["current_compliance"] == 0.05

        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params
        inst.configure_voltage_source(1.0, 0.05)
        inst.instrument.write.assert_any_call(":SOUR:FUNC VOLT")
        inst.instrument.write.assert_any_call(":SOUR:VOLT:LEV 1.0")
        inst.instrument.write.assert_any_call(":SENS:CURR:PROT 0.05")

    @pytest.mark.parametrize("check_params", [False, True])
    def test_configure_current_source_legacy_positional(self, check_params):
        # configure_current_source(0.01, 20.0) -> 0.01 A, 20.0 V compliance
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        vsm.configure_current_source(0.01, 20.0)
        assert vsm.state["source_func"] == "CURR"
        assert vsm.state["source_current"] == 0.01
        assert vsm.state["voltage_compliance"] == 20.0

        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params
        inst.configure_current_source(0.01, 20.0)
        inst.instrument.write.assert_any_call(":SOUR:FUNC CURR")
        inst.instrument.write.assert_any_call(":SOUR:CURR:LEV 0.01")
        inst.instrument.write.assert_any_call(":SENS:VOLT:PROT 20.0")

    @pytest.mark.parametrize("check_params", [False, True])
    def test_configure_rejects_invalid_channel_without_side_effects(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        vsm.configure_voltage_source(channel=1, voltage=2.0, current_compliance=0.1)

        with pytest.raises(ValueError):
            vsm.configure_voltage_source(channel=99, voltage=10.0, current_compliance=0.5)
        assert vsm.state["source_voltage"] == 2.0
        assert vsm.state["current_compliance"] == 0.1

        with pytest.raises(ValueError):
            vsm.configure_current_source(channel=99, current=0.05, voltage_compliance=50.0)

        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params

        with pytest.raises(ValueError):
            inst.configure_voltage_source(channel=99, voltage=10.0, current_compliance=0.5)
        inst.instrument.write.assert_not_called()

        with pytest.raises(ValueError):
            inst.configure_current_source(channel=99, current=0.05, voltage_compliance=50.0)
        inst.instrument.write.assert_not_called()


class TestMixedPositionalKeywordCalls:
    """Verify that valid mixed positional-channel and keyword-value calls succeed."""

    @pytest.mark.parametrize("check_params", [False, True])
    def test_virtual_sourcemeter_mixed_calls(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params

        # output(1, on=False)
        vsm.output(1, on=False)
        assert vsm.state["output_on"] is False

        # output(1, on=True)
        vsm.output(1, on=True)
        assert vsm.state["output_on"] is True

        # set_source_voltage(1, voltage=3.5)
        vsm.set_source_voltage(1, voltage=3.5)
        assert vsm.state["source_voltage"] == 3.5

        # set_source_current(1, current=0.01)
        vsm.set_source_current(1, current=0.01)
        assert vsm.state["source_current"] == 0.01

        # set_voltage_compliance(1, voltage_compliance=10.0)
        vsm.set_voltage_compliance(1, voltage_compliance=10.0)
        assert vsm.state["voltage_compliance"] == 10.0

        # set_current_compliance(1, current_compliance=0.05)
        vsm.set_current_compliance(1, current_compliance=0.05)
        assert vsm.state["current_compliance"] == 0.05

        # set_source_function(1, source_func="VOLT")
        vsm.set_source_function(1, source_func="VOLT")
        assert vsm.state["source_func"] == "VOLT"

        # set_sense_function(1, sense_func="CURR")
        vsm.set_sense_function(1, sense_func="CURR")
        assert vsm.state["sense_func"] == "CURR"

        # set_sense_mode(1, sense_mode="4W")
        vsm.set_sense_mode(1, sense_mode="4W")
        assert vsm.state["sense_mode"] == "4W"

        # configure_voltage_source(1, voltage=2.0, current_compliance=0.1)
        vsm.configure_voltage_source(1, voltage=2.0, current_compliance=0.1)
        assert vsm.state["source_func"] == "VOLT"
        assert vsm.state["source_voltage"] == 2.0
        assert vsm.state["current_compliance"] == 0.1

        # configure_voltage_source(1, 4.0, current_compliance=0.2)
        vsm.configure_voltage_source(1, 4.0, current_compliance=0.2)
        assert vsm.state["source_voltage"] == 4.0
        assert vsm.state["current_compliance"] == 0.2

        # configure_current_source(1, current=0.02, voltage_compliance=50.0)
        vsm.configure_current_source(1, current=0.02, voltage_compliance=50.0)
        assert vsm.state["source_func"] == "CURR"
        assert vsm.state["source_current"] == 0.02
        assert vsm.state["voltage_compliance"] == 50.0

        # configure_current_source(1, 0.03, voltage_compliance=60.0)
        vsm.configure_current_source(1, 0.03, voltage_compliance=60.0)
        assert vsm.state["source_current"] == 0.03
        assert vsm.state["voltage_compliance"] == 60.0

    @pytest.mark.parametrize("check_params", [False, True])
    def test_keithley2400_mixed_calls(self, check_params):
        inst = Keithley2400.__new__(Keithley2400)
        inst.instrument = Mock()
        inst.check_params = check_params

        inst.output(1, on=False)
        inst.instrument.write.assert_called_with(":OUTP OFF")

        inst.set_source_voltage(1, voltage=3.5)
        inst.instrument.write.assert_called_with(":SOUR:VOLT:LEV 3.5")

        inst.set_source_current(1, current=0.01)
        inst.instrument.write.assert_called_with(":SOUR:CURR:LEV 0.01")

        inst.set_voltage_compliance(1, voltage_compliance=10.0)
        inst.instrument.write.assert_called_with(":SENS:VOLT:PROT 10.0")

        inst.set_current_compliance(1, current_compliance=0.05)
        inst.instrument.write.assert_called_with(":SENS:CURR:PROT 0.05")

        inst.set_source_function(1, source_func="VOLT")
        inst.instrument.write.assert_called_with(":SOUR:FUNC VOLT")

        inst.set_sense_function(1, sense_func="CURR")
        inst.instrument.write.assert_called_with(':SENS:FUNC "CURRent"')

        inst.set_sense_mode(1, sense_mode="4W")
        inst.instrument.write.assert_called_with(":SYST:RSEN ON")

        inst.configure_voltage_source(1, voltage=2.0, current_compliance=0.1)
        inst.instrument.write.assert_any_call(":SOUR:FUNC VOLT")
        inst.instrument.write.assert_any_call(":SOUR:VOLT:LEV 2.0")
        inst.instrument.write.assert_any_call(":SENS:CURR:PROT 0.1")

        inst.configure_voltage_source(1, 4.0, current_compliance=0.2)
        inst.instrument.write.assert_any_call(":SOUR:VOLT:LEV 4.0")
        inst.instrument.write.assert_any_call(":SENS:CURR:PROT 0.2")

        inst.configure_current_source(1, current=0.02, voltage_compliance=50.0)
        inst.instrument.write.assert_any_call(":SOUR:FUNC CURR")
        inst.instrument.write.assert_any_call(":SOUR:CURR:LEV 0.02")
        inst.instrument.write.assert_any_call(":SENS:VOLT:PROT 50.0")

        inst.configure_current_source(1, 0.03, voltage_compliance=60.0)
        inst.instrument.write.assert_any_call(":SOUR:CURR:LEV 0.03")
        inst.instrument.write.assert_any_call(":SENS:VOLT:PROT 60.0")


class TestRejectDuplicateArguments:
    """Verify that duplicate arguments raise TypeError before state changes or transport writes."""

    duplicate_calls = [
        lambda dev: dev.output(False, on=True),
        lambda dev: dev.output(False, channel=1),
        lambda dev: dev.output(1, channel=1),
        lambda dev: dev.output(1, False, channel=1),
        lambda dev: dev.output(1, False, on=False),
        lambda dev: dev.set_source_voltage(1, channel=1),
        lambda dev: dev.set_source_voltage(1, 4.2, channel=1),
        lambda dev: dev.set_source_voltage(1, 4.2, voltage=4.2),
        lambda dev: dev.set_source_current(1, channel=1),
        lambda dev: dev.set_source_current(1, 0.01, channel=1),
        lambda dev: dev.set_source_current(1, 0.01, current=0.01),
        lambda dev: dev.set_voltage_compliance(1, channel=1),
        lambda dev: dev.set_voltage_compliance(1, 10.0, channel=1),
        lambda dev: dev.set_voltage_compliance(1, 10.0, voltage_compliance=10.0),
        lambda dev: dev.set_current_compliance(1, channel=1),
        lambda dev: dev.set_current_compliance(1, 0.05, channel=1),
        lambda dev: dev.set_current_compliance(1, 0.05, current_compliance=0.05),
        lambda dev: dev.set_source_function(1, channel=1),
        lambda dev: dev.set_source_function(1, "VOLT", channel=1),
        lambda dev: dev.set_source_function(1, "VOLT", source_func="VOLT"),
        lambda dev: dev.set_sense_function(1, channel=1),
        lambda dev: dev.set_sense_function(1, "CURR", channel=1),
        lambda dev: dev.set_sense_function(1, "CURR", sense_func="CURR"),
        lambda dev: dev.set_sense_mode(1, channel=1),
        lambda dev: dev.set_sense_mode(1, "4W", channel=1),
        lambda dev: dev.set_sense_mode(1, "4W", sense_mode="4W"),
        lambda dev: dev.configure_voltage_source(1, channel=1),
        lambda dev: dev.configure_voltage_source(1.0, 0.05, channel=1),
        lambda dev: dev.configure_voltage_source(1.0, 0.05, voltage=1.0),
        lambda dev: dev.configure_voltage_source(1, 1.0, 0.05, channel=1),
        lambda dev: dev.configure_voltage_source(1, 1.0, 0.05, voltage=1.0),
        lambda dev: dev.configure_voltage_source(1, 1.0, 0.05, current_compliance=0.05),
        lambda dev: dev.configure_current_source(1, channel=1),
        lambda dev: dev.configure_current_source(0.01, 20.0, channel=1),
        lambda dev: dev.configure_current_source(0.01, 20.0, current=0.01),
        lambda dev: dev.configure_current_source(1, 0.01, 20.0, channel=1),
        lambda dev: dev.configure_current_source(1, 0.01, 20.0, current=0.01),
        lambda dev: dev.configure_current_source(1, 0.01, 20.0, voltage_compliance=20.0),
        lambda dev: dev.quick_read(1, channel=1),
        lambda dev: dev.get_voltage(1, channel=1),
        lambda dev: dev.get_current(1, channel=1),
        lambda dev: dev.get_resistance(1, channel=1),
    ]

    @pytest.mark.parametrize("check_params", [False, True])
    def test_virtual_sourcemeter_rejects_duplicate_arguments(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        initial_state = dict(vsm.state)

        for call_fn in self.duplicate_calls:
            with pytest.raises(TypeError):
                call_fn(vsm)
            assert vsm.state == initial_state

    @pytest.mark.parametrize("check_params", [False, True])
    def test_keithley2400_rejects_duplicate_arguments(self, check_params):
        for call_fn in self.duplicate_calls:
            inst = Keithley2400.__new__(Keithley2400)
            inst.instrument = Mock()
            inst.check_params = check_params

            with pytest.raises(TypeError):
                call_fn(inst)
            inst.instrument.write.assert_not_called()
            inst.instrument.query.assert_not_called()


class TestRejectExcessPositionalArguments:
    """Verify that excess positional arguments raise TypeError before state changes or transport writes."""

    excess_calls = [
        lambda dev: dev.output(1, False, "excess"),
        lambda dev: dev.set_source_voltage(1, 4.2, 5.0),
        lambda dev: dev.set_source_current(1, 0.01, 0.02),
        lambda dev: dev.set_voltage_compliance(1, 10.0, 20.0),
        lambda dev: dev.set_current_compliance(1, 0.05, 0.1),
        lambda dev: dev.set_source_function(1, "VOLT", "CURR"),
        lambda dev: dev.set_sense_function(1, "CURR", "VOLT"),
        lambda dev: dev.set_sense_mode(1, "4W", "2W"),
        lambda dev: dev.configure_voltage_source(1, 1.0, 0.05, "excess"),
        lambda dev: dev.configure_current_source(1, 0.01, 20.0, "excess"),
        lambda dev: dev.quick_read(1, "excess"),
        lambda dev: dev.get_voltage(1, "excess"),
        lambda dev: dev.get_current(1, "excess"),
        lambda dev: dev.get_resistance(1, "excess"),
    ]

    @pytest.mark.parametrize("check_params", [False, True])
    def test_virtual_sourcemeter_rejects_excess_arguments(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        initial_state = dict(vsm.state)

        for call_fn in self.excess_calls:
            with pytest.raises(TypeError):
                call_fn(vsm)
            assert vsm.state == initial_state

    @pytest.mark.parametrize("check_params", [False, True])
    def test_keithley2400_rejects_excess_arguments(self, check_params):
        for call_fn in self.excess_calls:
            inst = Keithley2400.__new__(Keithley2400)
            inst.instrument = Mock()
            inst.check_params = check_params

            with pytest.raises(TypeError):
                call_fn(inst)
            inst.instrument.write.assert_not_called()
            inst.instrument.query.assert_not_called()


class TestRejectUnknownKeywordArguments:
    """Verify that unknown keyword arguments raise TypeError before state changes or transport writes."""

    unknown_calls = [
        lambda dev: dev.output(on=False, unknown_arg=1),
        lambda dev: dev.output(False, unknown_arg=1),
        lambda dev: dev.set_source_voltage(4.2, unknown_arg=1),
        lambda dev: dev.set_source_voltage(1, 4.2, unknown_arg=1),
        lambda dev: dev.set_source_voltage(voltage=4.2, unknown_arg=1),
        lambda dev: dev.set_source_current(0.01, unknown_arg=1),
        lambda dev: dev.set_voltage_compliance(10.0, unknown_arg=1),
        lambda dev: dev.set_current_compliance(0.05, unknown_arg=1),
        lambda dev: dev.set_source_function("VOLT", unknown_arg=1),
        lambda dev: dev.set_sense_function("CURR", unknown_arg=1),
        lambda dev: dev.set_sense_mode("4W", unknown_arg=1),
        lambda dev: dev.configure_voltage_source(1.0, 0.05, unknown_arg=1),
        lambda dev: dev.configure_voltage_source(1, 1.0, 0.05, unknown_arg=1),
        lambda dev: dev.configure_current_source(0.01, 20.0, unknown_arg=1),
        lambda dev: dev.configure_current_source(1, 0.01, 20.0, unknown_arg=1),
        lambda dev: dev.quick_read(unknown_arg=1),
        lambda dev: dev.get_voltage(unknown_arg=1),
        lambda dev: dev.get_current(unknown_arg=1),
        lambda dev: dev.get_resistance(unknown_arg=1),
    ]

    @pytest.mark.parametrize("check_params", [False, True])
    def test_virtual_sourcemeter_rejects_unknown_arguments(self, check_params):
        vsm = VirtualSourcemeter()
        vsm.check_params = check_params
        initial_state = dict(vsm.state)

        for call_fn in self.unknown_calls:
            with pytest.raises(TypeError):
                call_fn(vsm)
            assert vsm.state == initial_state

    @pytest.mark.parametrize("check_params", [False, True])
    def test_keithley2400_rejects_unknown_arguments(self, check_params):
        for call_fn in self.unknown_calls:
            inst = Keithley2400.__new__(Keithley2400)
            inst.instrument = Mock()
            inst.check_params = check_params

            with pytest.raises(TypeError):
                call_fn(inst)
            inst.instrument.write.assert_not_called()
            inst.instrument.query.assert_not_called()


