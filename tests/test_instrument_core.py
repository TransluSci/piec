"""

Tests for the core instrument framework in piec.drivers.instrument

Run with pytest tests/test_instrument_core.py
"""

import pytest

from piec.drivers.instrument import (
    is_contained,
    is_value_between,
    convert_to_lowercase,
    Instrument,
    AutoCheckMeta,
    VirtualRMInstrument,
)
from piec.drivers.scpi import Scpi

# Helper drivers defined once and reused across test classes

class _DemoDriver(Instrument, metaclass=AutoCheckMeta):
    """
    Minimal driver with two constrained parameters.
    Used to test check_params validation and state tracking.
    """
    waveform  = ["SIN", "SQU", "RAMP"]
    frequency = (1, 1e6)

    def set_waveform(self, waveform):
        pass

    def set_frequency(self, frequency):
        pass

    def configure(self, waveform, frequency):
        pass 


class _NoneAttrDriver(Instrument, metaclass=AutoCheckMeta):
    """
    Driver whose class attribute is set to None.
    None is the documented off switch, so the framework must skip validation
    """
    waveform = None   # skip auto-validation; driver handles it manually

    def set_waveform(self, waveform):
        pass


class _DependentDriver(Instrument, metaclass=AutoCheckMeta):
    """
    Driver that demonstrates dependent validation.
    The valid sensitivity values depend on the input configuration
    """
    input_configuration = ["A", "A-B"]
    sensitivity = {
        "input_configuration": {
            "A":   [1e-9, 1e-8, 1e-7],
            "A-B": [1e-9, 1e-8],  # 1e-7 is not valid in differential mode
        }
    }

    def set_input(self, input_configuration):
        # Sets input configuration; state-tracking will store _current_input_configuration.
        pass

    def set_sensitivity(self, sensitivity, input_configuration=None): 
        pass


class _DemoScpiDriver(Scpi):
    """
    used to test every Scpi command.
    Has one constrained parameter so we can verify that reset() clears state.
    """
    frequency = (1, 1e6)

    def set_frequency(self, frequency):
        pass


# Helper function tests

class TestIsContained:
    """is_contained checks whether a value exists in an allowed list."""

    def test_exact_match(self):
        assert is_contained("AC", ["AC", "DC"]) is True

    def test_case_insensitive_match(self):
        assert is_contained("ac", ["AC", "DC"]) is True

    def test_float_in_int_list(self):
        assert is_contained(1.0, [1, 2, 3]) is True

    def test_scientific_notation_float(self):
        assert is_contained(1e-9, [1e-9, 1e-8, 1e-7]) is True

    def test_missing_value_returns_false(self):
        assert is_contained("GND", ["AC", "DC"]) is False

    def test_none_always_passes(self):
        assert is_contained(None, ["AC", "DC"]) is True

class TestIsValueBetween:
    """is_value_between checks whether a number falls within a (min, max) tuple."""

    def test_value_in_range(self):
        assert is_value_between(500, (0, 1e6)) is True

    def test_value_at_lower_bound(self):
        assert is_value_between(0, (0, 1e6)) is True

    def test_value_at_upper_bound(self):
        assert is_value_between(1e6, (0, 1e6)) is True

    def test_value_below_range(self):
        assert is_value_between(-1, (0, 1e6)) is False

    def test_value_above_range(self):
        assert is_value_between(2e6, (0, 1e6)) is False

    def test_string_numeric_value(self):
        assert is_value_between("500", (0, 1e6)) is True

    def test_none_always_passes(self):
        assert is_value_between(None, (0, 1e6)) is True


class TestConvertToLowercase:
    """convert_to_lowercase normalises string values in a parameter dict."""

    def test_string_is_lowercased(self):
        result = convert_to_lowercase({"coupling": "AC"})
        assert result["coupling"] == "ac"

    def test_non_string_unchanged(self):
        result = convert_to_lowercase({"frequency": 1000})
        assert result["frequency"] == 1000

    def test_mixed_dict(self):
        result = convert_to_lowercase({"coupling": "DC", "frequency": 5000})
        assert result["coupling"] == "dc"
        assert result["frequency"] == 5000


# VirtualRMInstrument

class TestVirtualRMInstrument:

    def setup_method(self):
        self.rm = VirtualRMInstrument(address="VIRTUAL")

    def test_idn_query_returns_expected_string(self):
        response = self.rm.query("*IDN?")
        assert "VirtualInstrument" in response

    def test_known_query_returns_json_value(self):
        response = self.rm.query("MEAS:VOLT:DC?")
        assert response == "3.14159"

    def test_opc_query_returns_one(self):
        assert self.rm.query("*OPC?") == "1"

    def test_esr_query_returns_zero(self):
        assert self.rm.query("*ESR?") == "0"

    def test_unknown_query_returns_fallback_string(self):
        response = self.rm.query("COMPLETELY:UNKNOWN:QUERY?")
        assert response is not None
        assert isinstance(response, str)

    def test_write_does_not_raise(self):
        self.rm.write("*RST")  

    def test_query_binary_returns_list(self):
        # query_binary_values is used by oscilloscope waveform transfers.
        result = self.rm.query_binary_values("WAVeform:DATA?")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_query_ascii_returns_list(self):
        # query_ascii_values is used by instruments that return CSV data.
        result = self.rm.query_ascii_values("FETCH?")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_resource_name_is_stored(self):
        # The address is stored as resource_name for downstream inspection.
        assert self.rm.resource_name == "VIRTUAL"


# Instrument class
class TestInstrumentVirtualMode:
    """Instrument initialises correctly in virtual mode (no hardware needed)."""

    def test_virtual_instrument_creates(self):
        inst = Instrument(address="VIRTUAL")
        assert inst is not None

    def test_virtual_flag_is_set(self):
        inst = Instrument(address="VIRTUAL")
        assert inst.virtual is True

    def test_instrument_attribute_exists(self):
        inst = Instrument(address="VIRTUAL")
        assert hasattr(inst, "instrument")

    def test_idn_returns_string(self):
        inst = Instrument(address="VIRTUAL")
        result = inst.idn()
        assert isinstance(result, str)

    def test_check_params_flag_stored(self):
        inst = Instrument(address="VIRTUAL", check_params=True)
        assert inst.check_params is True

    def test_verbose_flag_stored(self):
        inst = Instrument(address="VIRTUAL", verbose=True)
        assert inst.verbose is True

    def test_all_current_attrs_start_as_none(self):
        driver = _DemoDriver(address="VIRTUAL")
        assert driver._current_waveform is None
        assert driver._current_frequency is None

class TestCheckParams:
    """When check_params=True, invalid arguments must raise ValueError."""

    def setup_method(self):
        self.driver = _DemoDriver(address="VIRTUAL", check_params=True)

    def test_valid_waveform_accepted(self):
        # 'SIN' is in the allowed list, must not raise.
        self.driver.set_waveform(waveform="SIN")

    def test_invalid_waveform_rejected(self):
        # 'TRI' is not in the allowed list, must raise ValueError.
        with pytest.raises(ValueError):
            self.driver.set_waveform(waveform="TRI")

    def test_valid_frequency_accepted(self):
        self.driver.set_frequency(frequency=1000)

    def test_frequency_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            self.driver.set_frequency(frequency=2e6)

    def test_check_params_false_allows_bad_value(self):
        # With check_params=False (default) bad values must NOT raise
        # the driver is responsible for its own handling.
        permissive = _DemoDriver(address="VIRTUAL", check_params=False)
        permissive.set_waveform(waveform="TRI") 

    def test_none_class_attr_skips_validation(self):
        # A class attribute set to None
        # Even with check_params=True, any value must be accepted.
        driver = _NoneAttrDriver(address="VIRTUAL", check_params=True)
        driver.set_waveform(waveform="ANYTHING_AT_ALL")   # must not raise

    def test_none_argument_always_passes(self):
        self.driver.set_waveform(waveform=None)


class TestStateTracking:

    def setup_method(self):
        self.driver = _DemoDriver(address="VIRTUAL", check_params=False)

    def test_current_waveform_updated_after_set(self):
        assert self.driver._current_waveform is None
        self.driver.set_waveform(waveform="SIN")
        assert self.driver._current_waveform == "sin"

    def test_current_frequency_updated_after_set(self):
        assert self.driver._current_frequency is None
        self.driver.set_frequency(frequency=5000)
        assert self.driver._current_frequency == 5000

    def test_multiple_params_both_states_updated(self):
        self.driver.configure(waveform="SQU", frequency=1000)
        assert self.driver._current_waveform == "squ"
        assert self.driver._current_frequency == 1000

    def test_state_not_updated_when_validation_raises(self):
        # If check_params raises before the method body runs, the
        # _current_* attribute must stay at its previous value.
        strict = _DemoDriver(address="VIRTUAL", check_params=True)

        strict.set_frequency(frequency=500)
        assert strict._current_frequency == 500

        # Attempt to set a bad value, this must raise.
        with pytest.raises(ValueError):
            strict.set_frequency(frequency=2e6)

        assert strict._current_frequency == 500

    def test_state_updates_reflect_most_recent_call(self):
        # Calling the same setter twice must store the latest value.
        self.driver.set_frequency(frequency=1000)
        self.driver.set_frequency(frequency=50000)
        assert self.driver._current_frequency == 50000

    def test_initialize_state_resets_all_current_attrs(self):
        # _initialize_state() is called by Scpi.reset(), verify it wipes
        self.driver.set_waveform(waveform="SIN")
        self.driver.set_frequency(frequency=1000)
        assert self.driver._current_waveform == "sin"

        self.driver._initialize_state()

        assert self.driver._current_waveform is None
        assert self.driver._current_frequency is None
