"""
Contract tests for Digital Multimeter (DMM) base driver and implementations.

Stage 0 Checkpoint 6: DMM voltage configuration and read audit across
advertised MOKE/AMR DMMs (VirtualDMM, Agilent34410A, Keithley2000, Keithley193a).
Verifies sense-function selection, DC coupling, optional range/integration settings,
get_voltage(), scalar-return contract, and finite/non-finite handling.
"""

import math
from unittest.mock import Mock, patch
import numpy as np
import pytest

from piec.drivers.dmm.dmm import DMM
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.dmm.agilent_34410a import Agilent34410A
from piec.drivers.dmm.keithley_2000 import Keithley2000
from piec.drivers.dmm.keithley193a import Keithley193a
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.analysis.field_calibration import FieldCalibration
from piec.measurement.moke import MokeMeasurement


ALL_DMM_DRIVERS = [
    VirtualDMM,
    Agilent34410A,
    Keithley2000,
    Keithley193a,
]


# ============================================================================
# 1. Base Class and Driver Inventory Conformance
# ============================================================================

class TestDMMInventory:
    """Verify that all advertised DMM drivers conform to DMM base class standards."""

    @pytest.mark.parametrize("driver_cls", ALL_DMM_DRIVERS)
    def test_inherits_from_dmm(self, driver_cls):
        """Every advertised DMM driver must inherit from DMM."""
        assert issubclass(driver_cls, DMM)

    @pytest.mark.parametrize("driver_cls", ALL_DMM_DRIVERS)
    def test_declares_channel_attribute(self, driver_cls):
        """Every advertised DMM driver must define channel attribute as [1]."""
        assert hasattr(driver_cls, "channel")
        assert list(driver_cls.channel) == [1]

    @pytest.mark.parametrize("driver_cls", ALL_DMM_DRIVERS)
    def test_declares_required_class_attributes(self, driver_cls):
        """Every driver declares sense_func, coupling, sense_mode, and sense_range."""
        assert hasattr(driver_cls, "sense_func")
        assert "VOLT" in driver_cls.sense_func
        assert hasattr(driver_cls, "coupling")
        assert "DC" in driver_cls.coupling
        assert hasattr(driver_cls, "sense_mode")
        assert "2W" in driver_cls.sense_mode
        assert hasattr(driver_cls, "sense_range")

    @pytest.mark.parametrize("driver_cls", [Agilent34410A, Keithley2000, Keithley193a])
    def test_hardware_drivers_declare_autodetect_id(self, driver_cls):
        """Hardware drivers must declare an AUTODETECT_ID string or list."""
        assert hasattr(driver_cls, "AUTODETECT_ID")
        autoid = driver_cls.AUTODETECT_ID
        assert isinstance(autoid, (str, list))


# ============================================================================
# 2. VirtualDMM Contract Tests
# ============================================================================

class TestVirtualDMMContract:
    """Verify VirtualDMM state transitions, call signatures, and scalar returns."""

    @pytest.fixture
    def v_dmm(self):
        return VirtualDMM()

    def test_initial_state(self, v_dmm):
        """VirtualDMM initializes into default DC Voltage, 2-wire, autorange state."""
        state = v_dmm.get_state()
        assert state["sense_func"] == "VOLT"
        assert state["coupling"] == "DC"
        assert state["sense_mode"] == "2W"
        assert state["autorange"] is True
        assert state["sense_range"] is None
        assert state["integration_time"] == 1.0

    def test_set_sense_function(self, v_dmm):
        """set_sense_function updates state and validates against permitted functions."""
        v_dmm.set_sense_function("CURR")
        assert v_dmm.state["sense_func"] == "CURR"

        v_dmm.set_sense_function("RES")
        assert v_dmm.state["sense_func"] == "RES"

        v_dmm.set_sense_function(sense_func="VOLT")
        assert v_dmm.state["sense_func"] == "VOLT"

        with pytest.raises(ValueError, match="unsupported sense function"):
            v_dmm.set_sense_function("MAGNETIC_FIELD")

    def test_set_measurement_coupling(self, v_dmm):
        """set_measurement_coupling updates state and rejects invalid coupling."""
        v_dmm.set_measurement_coupling("AC")
        assert v_dmm.state["coupling"] == "AC"

        v_dmm.set_measurement_coupling(coupling="DC")
        assert v_dmm.state["coupling"] == "DC"

        with pytest.raises(ValueError, match="unsupported measurement coupling"):
            v_dmm.set_measurement_coupling("OPTICAL")

    def test_set_sense_mode(self, v_dmm):
        """set_sense_mode updates 2W/4W mode and rejects invalid modes."""
        v_dmm.set_sense_mode("4W")
        assert v_dmm.state["sense_mode"] == "4W"

        v_dmm.set_sense_mode(sense_mode="2W")
        assert v_dmm.state["sense_mode"] == "2W"

        with pytest.raises(ValueError, match="unsupported sense mode"):
            v_dmm.set_sense_mode("8W")

    def test_set_sense_range(self, v_dmm):
        """set_sense_range supports auto and manual range settings."""
        v_dmm.set_sense_range(range_val=10.0, auto=False)
        assert v_dmm.state["sense_range"] == 10.0
        assert v_dmm.state["autorange"] is False

        v_dmm.set_sense_range(auto=True)
        assert v_dmm.state["sense_range"] is None
        assert v_dmm.state["autorange"] is True

        with pytest.raises(ValueError, match="range_val is required"):
            v_dmm.set_sense_range(auto=False)

    def test_set_integration_time(self, v_dmm):
        """set_integration_time validates positive NPLC and updates state."""
        v_dmm.set_integration_time(10.0)
        assert v_dmm.state["integration_time"] == 10.0

        v_dmm.set_integration_time(nplc=0.1)
        assert v_dmm.state["integration_time"] == 0.1

        with pytest.raises(ValueError, match="nplc must be positive"):
            v_dmm.set_integration_time(-1.0)
        with pytest.raises(ValueError, match="nplc must be positive"):
            v_dmm.set_integration_time(0.0)

    def test_voltage_reader_injection(self, v_dmm):
        """Custom voltage reader callable can be injected or cleared."""
        v_dmm.set_voltage_reader(lambda: 3.14159)
        assert v_dmm.get_voltage() == pytest.approx(3.14159)

        v_dmm.set_voltage_reader(None)
        assert isinstance(v_dmm.get_voltage(), float)
        # Default with mag_sample (current_field=0) is 0.0
        assert v_dmm.get_voltage() == pytest.approx(0.0)
        # With mag_sample=None, fallback constant is 0.0015
        v_dmm.mag_sample = None
        assert v_dmm.get_voltage() == pytest.approx(0.0015)

        with pytest.raises(TypeError, match="must be callable or None"):
            v_dmm.set_voltage_reader("not_a_callable")

    def test_get_voltage_finite_and_non_finite_handling(self, v_dmm):
        """get_voltage returns scalar floats and normalizes overload/non-finite values."""
        # Normal finite float
        v_dmm.set_voltage_reader(lambda: 1.234)
        v = v_dmm.get_voltage()
        assert isinstance(v, float)
        assert math.isclose(v, 1.234)
        assert np.isfinite(v)

        # NaN return
        v_dmm.set_voltage_reader(lambda: float("nan"))
        v_nan = v_dmm.get_voltage()
        assert isinstance(v_nan, float)
        assert math.isnan(v_nan)
        assert not np.isfinite(v_nan)

        # Inf return
        v_dmm.set_voltage_reader(lambda: float("inf"))
        v_inf = v_dmm.get_voltage()
        assert isinstance(v_inf, float)
        assert math.isinf(v_inf)
        assert not np.isfinite(v_inf)

        # -Inf return
        v_dmm.set_voltage_reader(lambda: float("-inf"))
        v_ninf = v_dmm.get_voltage()
        assert isinstance(v_ninf, float)
        assert math.isinf(v_ninf) and v_ninf < 0
        assert not np.isfinite(v_ninf)

    def test_get_voltage_ac_mode(self, v_dmm):
        """get_voltage(ac=True) switches coupling state to AC."""
        v_dmm.get_voltage(ac=True)
        assert v_dmm.state["coupling"] == "AC"

        v_dmm.get_voltage(ac=False)
        assert v_dmm.state["coupling"] == "DC"

    def test_quick_read_delegation(self, v_dmm):
        """quick_read delegates to get_voltage with active coupling."""
        v_dmm.set_voltage_reader(lambda: 2.718)
        assert v_dmm.quick_read() == pytest.approx(2.718)

    def test_reset_preserves_injected_reader(self, v_dmm):
        """reset restores defaults while preserving injected reader callable."""
        custom_reader = lambda: 42.0
        v_dmm.set_voltage_reader(custom_reader)
        v_dmm.set_sense_function("CURR")
        v_dmm.set_measurement_coupling("AC")
        v_dmm.reset()

        state = v_dmm.get_state()
        assert state["sense_func"] == "VOLT"
        assert state["coupling"] == "DC"
        assert v_dmm.get_voltage() == pytest.approx(42.0)

    def test_clear_is_safe_noop(self, v_dmm):
        """clear() on VirtualDMM returns safely without error."""
        assert v_dmm.clear() is None

    def test_idn_returns_string(self, v_dmm):
        """idn() returns a human-readable identifier."""
        assert isinstance(v_dmm.idn(), str)
        assert "Virtual DMM" in v_dmm.idn()


# ============================================================================
# 3. Agilent34410A Contract Tests (Fake Transport)
# ============================================================================

class TestAgilent34410AContract:
    """Verify Agilent 34410A SCPI command generation, function tracking, and parsing."""

    @pytest.fixture
    def agilent(self):
        inst = Agilent34410A.__new__(Agilent34410A)
        inst.instrument = Mock()
        return inst

    def test_set_sense_function_defaults(self, agilent):
        """set_sense_function without coupling/mode defaults safely to DC and 2W."""
        agilent.set_sense_function("VOLT")
        agilent.instrument.write.assert_called_with("CONF:VOLT:DC")
        assert agilent._scpi_sense_func == "VOLT:DC"

        agilent.set_sense_function("CURR")
        agilent.instrument.write.assert_called_with("CONF:CURR:DC")
        assert agilent._scpi_sense_func == "CURR:DC"

        agilent.set_sense_function("RES")
        agilent.instrument.write.assert_called_with("CONF:RES")
        assert agilent._scpi_sense_func == "RES"

    def test_set_sense_function_with_explicit_options(self, agilent):
        """set_sense_function accepts explicit coupling, mode, and non-volt functions."""
        agilent.set_sense_function("VOLT", coupling="AC")
        agilent.instrument.write.assert_called_with("CONF:VOLT:AC")

        agilent.set_sense_function("RES", sense_mode="4W")
        agilent.instrument.write.assert_called_with("CONF:FRES")

        agilent.set_sense_function("FREQ")
        agilent.instrument.write.assert_called_with("CONF:FREQ")

        agilent.set_sense_function("CAP")
        agilent.instrument.write.assert_called_with("CONF:CAP")

    def test_set_measurement_coupling(self, agilent):
        """set_measurement_coupling issues CONF:VOLT:<coupling> or CONF:CURR:<coupling>."""
        agilent.set_sense_function("VOLT")
        agilent.set_measurement_coupling("AC")
        agilent.instrument.write.assert_called_with("CONF:VOLT:AC")

        agilent.set_measurement_coupling(coupling="DC")
        agilent.instrument.write.assert_called_with("CONF:VOLT:DC")

    def test_set_sense_mode(self, agilent):
        """set_sense_mode routes between 2W (RES) and 4W (FRES)."""
        agilent.set_sense_function("RES")
        agilent.set_sense_mode("4W")
        agilent.instrument.write.assert_called_with("CONF:FRES")

        agilent.set_sense_mode(sense_mode="2W")
        agilent.instrument.write.assert_called_with("CONF:RES")

    def test_set_sense_range(self, agilent):
        """set_sense_range queries FUNC? and writes RANGe:AUTO or fixed range."""
        agilent.instrument.query.return_value = '"VOLT:DC"\n'

        agilent.set_sense_range(auto=True)
        agilent.instrument.write.assert_called_with("VOLT:DC:RANGe:AUTO ON")

        agilent.set_sense_range(range_val=10.0, auto=False)
        agilent.instrument.write.assert_called_with("VOLT:DC:RANGe 10.0")

    def test_set_integration_time(self, agilent):
        """set_integration_time queries FUNC? and writes NPLC for DC/RES modes; AC raises."""
        agilent.instrument.query.return_value = '"VOLT:DC"\n'
        agilent.set_integration_time(10)
        agilent.instrument.write.assert_called_with("VOLT:DC:NPLC 10")

        # AC function is capability-gated and raises NotImplementedError
        agilent.instrument.write.reset_mock()
        agilent.instrument.query.return_value = '"VOLT:AC"\n'
        with pytest.raises(NotImplementedError, match="does not support NPLC"):
            agilent.set_integration_time(10)

    def test_get_voltage(self, agilent):
        """get_voltage configures mode, queries READ?, and returns scalar float."""
        agilent.instrument.query.return_value = "+1.23456700E+00\n"

        v = agilent.get_voltage(ac=False)
        agilent.instrument.write.assert_called_with("CONF:VOLT:DC")
        agilent.instrument.query.assert_called_with("READ?")
        assert isinstance(v, float)
        assert v == pytest.approx(1.234567)

        v_ac = agilent.get_voltage(ac=True)
        agilent.instrument.write.assert_called_with("CONF:VOLT:AC")
        assert isinstance(v_ac, float)

    def test_get_voltage_finite_and_overflow_handling(self, agilent):
        """Agilent 34410A normalizes SCPI overflow string (+9.90000000E+37) to float('inf')."""
        # Positive overload normalized to +inf
        agilent.instrument.query.return_value = "+9.90000000E+37\n"
        v_ovfl = agilent.get_voltage()
        assert isinstance(v_ovfl, float)
        assert np.isinf(v_ovfl) and v_ovfl > 0
        assert not np.isfinite(v_ovfl)

        # Negative overload normalized to -inf
        agilent.instrument.query.return_value = "-9.90000000E+37\n"
        v_novfl = agilent.get_voltage()
        assert isinstance(v_novfl, float)
        assert np.isinf(v_novfl) and v_novfl < 0
        assert not np.isfinite(v_novfl)

        # INF and NaN strings
        agilent.instrument.query.return_value = "+INF\n"
        assert math.isinf(agilent.get_voltage())

        agilent.instrument.query.return_value = "-INF\n"
        assert math.isinf(agilent.get_voltage())

        agilent.instrument.query.return_value = "NAN\n"
        assert math.isnan(agilent.get_voltage())

        # Malformed response raises ValueError
        agilent.instrument.query.return_value = ""
        with pytest.raises(ValueError):
            agilent.get_voltage()

    def test_quick_read(self, agilent):
        """quick_read queries READ? directly and returns float."""
        agilent.instrument.query.return_value = "+0.00500000\n"
        val = agilent.quick_read()
        agilent.instrument.query.assert_called_with("READ?")
        assert val == pytest.approx(0.005)

    def test_function_tracking_synchronization_after_reads(self, agilent):
        """Getters update internal _scpi_sense_func so subsequent coupling/mode use the active function."""
        agilent.set_sense_function("CURR")
        agilent.instrument.write.assert_called_with("CONF:CURR:DC")
        assert agilent._scpi_sense_func == "CURR:DC"

        # Calling get_voltage() changes hardware state to VOLT:DC and updates tracking
        agilent.instrument.query.return_value = "0.5\n"
        agilent.get_voltage()
        agilent.instrument.write.assert_called_with("CONF:VOLT:DC")
        assert agilent._scpi_sense_func == "VOLT:DC"

        # Subsequent set_measurement_coupling operates on VOLT, NOT CURR
        agilent.set_measurement_coupling("AC")
        agilent.instrument.write.assert_called_with("CONF:VOLT:AC")
        assert agilent._scpi_sense_func == "VOLT:AC"

        # Calling get_current() updates tracking to CURR:DC
        agilent.get_current()
        agilent.instrument.write.assert_called_with("CONF:CURR:DC")
        assert agilent._scpi_sense_func == "CURR:DC"

        # Subsequent coupling operates on CURR
        agilent.set_measurement_coupling("AC")
        agilent.instrument.write.assert_called_with("CONF:CURR:AC")

        # Calling get_resistance() updates tracking to RES
        agilent.get_resistance()
        agilent.instrument.write.assert_called_with("CONF:RES")
        assert agilent._scpi_sense_func == "RES"

        # Subsequent set_sense_mode("4W") operates on resistance
        agilent.set_sense_mode("4W")
        agilent.instrument.write.assert_called_with("CONF:FRES")

    def test_other_measurement_functions(self, agilent):
        """get_current, get_resistance, get_frequency, get_capacitance emit SCPI and return float."""
        agilent.instrument.query.return_value = "0.01\n"
        assert agilent.get_current() == pytest.approx(0.01)
        agilent.instrument.write.assert_called_with("CONF:CURR:DC")

        agilent.instrument.query.return_value = "100.0\n"
        assert agilent.get_resistance(four_wire=True) == pytest.approx(100.0)
        agilent.instrument.write.assert_called_with("CONF:FRES")

        agilent.instrument.query.return_value = "1000.0\n"
        assert agilent.get_frequency() == pytest.approx(1000.0)
        agilent.instrument.write.assert_called_with("CONF:FREQ")

        agilent.instrument.query.return_value = "1e-9\n"
        assert agilent.get_capacitance() == pytest.approx(1e-9)
        agilent.instrument.write.assert_called_with("CONF:CAP")

    def test_scpi_reset_and_clear(self, agilent):
        """reset and clear send standard SCPI *RST and *CLS."""
        agilent.reset()
        agilent.instrument.write.assert_called_with("*RST")

        agilent.clear()
        agilent.instrument.write.assert_called_with("*CLS")

    def test_reset_restores_function_cache_and_enables_clean_reconfiguration(self, agilent):
        """reset restores _scpi_sense_func to VOLT:DC so subsequent configs target DCV, not pre-reset function."""
        # Query a non-voltage function to displace the cache
        agilent.instrument.query.return_value = "0.01\n"
        agilent.get_current()
        assert agilent._scpi_sense_func == "CURR:DC"

        # Execute reset
        agilent.reset()
        agilent.instrument.write.assert_called_with("*RST")
        assert agilent._scpi_sense_func == "VOLT:DC"

        # Reconfiguration after reset targets VOLT, NOT CURR
        agilent.set_measurement_coupling("AC")
        agilent.instrument.write.assert_called_with("CONF:VOLT:AC")
        assert agilent._scpi_sense_func == "VOLT:AC"

        # Another reset restores VOLT:DC
        agilent.reset()
        assert agilent._scpi_sense_func == "VOLT:DC"

        # 4W sense mode does not switch to FRES when in reset VOLT:DC state
        agilent.instrument.write.reset_mock()
        agilent.set_sense_mode("4W")
        agilent.instrument.write.assert_not_called()


# ============================================================================
# 4. Keithley 2000 Contract Tests (Fake Transport)
# ============================================================================

class TestKeithley2000Contract:
    """Verify Keithley 2000 SCPI command generation, function tracking, and parsing."""

    @pytest.fixture
    def k2000(self):
        inst = Keithley2000.__new__(Keithley2000)
        inst.instrument = Mock()
        return inst

    def test_set_sense_function_defaults(self, k2000):
        """set_sense_function defaults coupling to DC and mode to 2W."""
        k2000.set_sense_function("VOLT")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:DC'")
        assert k2000._scpi_sense_func == "VOLT:DC"

        k2000.set_sense_function("CURR")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'CURR:DC'")
        assert k2000._scpi_sense_func == "CURR:DC"

        k2000.set_sense_function("RES")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'RES'")
        assert k2000._scpi_sense_func == "RES"

    def test_set_sense_function_with_explicit_options(self, k2000):
        """set_sense_function accepts explicit coupling, mode, and additional functions."""
        k2000.set_sense_function("VOLT", coupling="AC")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:AC'")

        k2000.set_sense_function("RES", sense_mode="4W")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'FRES'")

        k2000.set_sense_function("FREQ")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'FREQ'")

        k2000.set_sense_function("TEMP")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'TEMP'")

    def test_set_measurement_coupling(self, k2000):
        """set_measurement_coupling updates SENS:FUNC with specified coupling."""
        k2000.set_sense_function("VOLT")
        k2000.set_measurement_coupling("AC")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:AC'")

        k2000.set_measurement_coupling(coupling="DC")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:DC'")

    def test_set_sense_mode(self, k2000):
        """set_sense_mode routes between 2W (RES) and 4W (FRES)."""
        k2000.set_sense_function("RES")
        k2000.set_sense_mode("4W")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'FRES'")

        k2000.set_sense_mode(sense_mode="2W")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'RES'")

    def test_set_sense_range(self, k2000):
        """set_sense_range writes :SENS:<func>:RANG:AUTO ON or fixed range."""
        k2000.set_sense_function("VOLT")
        k2000.set_sense_range(auto=True)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:RANG:AUTO ON")

        k2000.set_sense_range(range_val=10.0, auto=False)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:RANG 10.0")

    def test_set_integration_time(self, k2000):
        """set_integration_time writes :SENS:<func>:NPLC <nplc>; AC raises NotImplementedError."""
        k2000.set_sense_function("VOLT")
        k2000.set_integration_time(5)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:NPLC 5")

        # In AC mode, NPLC is capability gated and raises NotImplementedError
        k2000.instrument.query.return_value = "0.0\n"
        k2000.get_voltage(ac=True)
        with pytest.raises(NotImplementedError, match="does not support NPLC"):
            k2000.set_integration_time(5)

    def test_get_voltage(self, k2000):
        """get_voltage configures mode, queries :READ?, and returns scalar float."""
        k2000.instrument.query.return_value = "+2.50000000E-01\n"

        v = k2000.get_voltage(ac=False)
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:DC'")
        k2000.instrument.query.assert_called_with(":READ?")
        assert isinstance(v, float)
        assert v == pytest.approx(0.25)

        v_ac = k2000.get_voltage(ac=True)
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:AC'")
        assert isinstance(v_ac, float)

    def test_get_voltage_finite_and_overflow_handling(self, k2000):
        """Keithley 2000 normalizes overflow string (+9.99999900E+37) to float('inf')."""
        # Positive overload normalized to +inf
        k2000.instrument.query.return_value = "+9.99999900E+37\n"
        v_ovfl = k2000.get_voltage()
        assert isinstance(v_ovfl, float)
        assert np.isinf(v_ovfl) and v_ovfl > 0
        assert not np.isfinite(v_ovfl)

        # Negative overload normalized to -inf
        k2000.instrument.query.return_value = "-9.99999900E+37\n"
        v_novfl = k2000.get_voltage()
        assert isinstance(v_novfl, float)
        assert np.isinf(v_novfl) and v_novfl < 0
        assert not np.isfinite(v_novfl)

        k2000.instrument.query.return_value = "+INF\n"
        assert math.isinf(k2000.get_voltage())

        k2000.instrument.query.return_value = "-INF\n"
        assert math.isinf(k2000.get_voltage())

    def test_quick_read(self, k2000):
        """quick_read queries :READ? directly and returns float."""
        k2000.instrument.query.return_value = "+1.00000000\n"
        assert k2000.quick_read() == pytest.approx(1.0)
        k2000.instrument.query.assert_called_with(":READ?")

    def test_function_tracking_synchronization_after_reads(self, k2000):
        """Getters update internal _scpi_sense_func so subsequent coupling/range/NPLC use active function."""
        k2000.set_sense_function("CURR")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'CURR:DC'")
        assert k2000._scpi_sense_func == "CURR:DC"

        # Calling get_voltage() changes hardware function to VOLT:DC and updates tracking
        k2000.instrument.query.return_value = "0.5\n"
        k2000.get_voltage()
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:DC'")
        assert k2000._scpi_sense_func == "VOLT:DC"

        # Subsequent set_measurement_coupling operates on VOLT, NOT CURR
        k2000.set_measurement_coupling("AC")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:AC'")
        assert k2000._scpi_sense_func == "VOLT:AC"

        # Calling get_voltage(ac=False) restores VOLT:DC
        k2000.get_voltage(ac=False)
        assert k2000._scpi_sense_func == "VOLT:DC"

        # Subsequent range and integration commands operate on VOLT:DC
        k2000.set_sense_range(auto=True)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:RANG:AUTO ON")
        k2000.set_integration_time(5)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:NPLC 5")

        # Calling get_current() updates tracking to CURR:DC
        k2000.get_current()
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'CURR:DC'")
        assert k2000._scpi_sense_func == "CURR:DC"

        # Range command now targets CURR:DC
        k2000.set_sense_range(auto=True)
        k2000.instrument.write.assert_called_with(":SENS:CURR:DC:RANG:AUTO ON")

        # Calling get_resistance() updates tracking to RES
        k2000.get_resistance()
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'RES'")
        assert k2000._scpi_sense_func == "RES"

        k2000.set_sense_range(auto=True)
        k2000.instrument.write.assert_called_with(":SENS:RES:RANG:AUTO ON")
        k2000.set_integration_time(2)
        k2000.instrument.write.assert_called_with(":SENS:RES:NPLC 2")

        # set_sense_mode("4W") writes FRES and updates tracking
        k2000.set_sense_mode("4W")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'FRES'")
        assert k2000._scpi_sense_func == "FRES"

    def test_other_measurement_functions(self, k2000):
        """get_current, get_resistance, get_frequency, get_temperature emit SCPI and return float."""
        k2000.instrument.query.return_value = "0.005\n"
        assert k2000.get_current() == pytest.approx(0.005)
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'CURR:DC'")

        k2000.instrument.query.return_value = "500.0\n"
        assert k2000.get_resistance(four_wire=False) == pytest.approx(500.0)
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'RES'")

        k2000.instrument.query.return_value = "60.0\n"
        assert k2000.get_frequency() == pytest.approx(60.0)
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'FREQ'")

        k2000.instrument.query.return_value = "23.5\n"
        assert k2000.get_temperature(probe_type="TC") == pytest.approx(23.5)
        k2000.instrument.write.assert_called_with(":SENS:TEMP:TRAN TC")

    def test_scpi_reset_and_clear(self, k2000):
        """reset and clear send standard SCPI *RST and *CLS."""
        k2000.reset()
        k2000.instrument.write.assert_called_with("*RST")

        k2000.clear()
        k2000.instrument.write.assert_called_with("*CLS")

    def test_reset_restores_function_cache_and_enables_clean_reconfiguration(self, k2000):
        """reset restores _scpi_sense_func to VOLT:DC so range, NPLC, and coupling target DCV, not pre-reset function."""
        # Query frequency so NPLC is unsupported and range is different
        k2000.instrument.query.return_value = "1000.0\n"
        k2000.get_frequency()
        assert k2000._scpi_sense_func == "FREQ"

        # Before reset, NPLC on FREQ raises NotImplementedError
        with pytest.raises(NotImplementedError):
            k2000.set_integration_time(10)

        # Execute reset
        k2000.reset()
        k2000.instrument.write.assert_called_with("*RST")
        assert k2000._scpi_sense_func == "VOLT:DC"

        # After reset, set_integration_time operates cleanly on VOLT:DC without error
        k2000.set_integration_time(10)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:NPLC 10")

        # Range configuration after reset operates on VOLT:DC
        k2000.set_sense_range(range_val=10.0, auto=False)
        k2000.instrument.write.assert_called_with(":SENS:VOLT:DC:RANG 10.0")

        # Coupling configuration after reset operates on VOLT:DC -> VOLT:AC
        k2000.set_measurement_coupling("AC")
        k2000.instrument.write.assert_called_with(":SENS:FUNC 'VOLT:AC'")
        assert k2000._scpi_sense_func == "VOLT:AC"


# ============================================================================
# 5. Keithley 193A Contract Tests (Fake Transport)
# ============================================================================

class TestKeithley193aContract:
    """Verify Keithley 193A DDC command generation, regex parsing, and capability gating."""

    @pytest.fixture
    def k193(self):
        inst = Keithley193a.__new__(Keithley193a)
        inst.instrument = Mock()
        inst.instrument.resource_name = "GPIB::12::INSTR"
        return inst

    def test_idn_query(self, k193):
        """idn sends U0X and returns identification string."""
        k193.instrument.read.return_value = "193A 01.0\r\n"

        ident = k193.idn()
        k193.instrument.write.assert_called_with("U0X")
        assert "193A" in ident

    def test_set_sense_function(self, k193):
        """set_sense_function writes DDC function codes F0X, F3X, F2X."""
        k193.set_sense_function("VOLT")
        k193.instrument.write.assert_called_with("F0X")

        k193.set_sense_function("CURR")
        k193.instrument.write.assert_called_with("F3X")

        k193.set_sense_function("RES")
        k193.instrument.write.assert_called_with("F2X")

        with pytest.raises(ValueError, match=r"(not supported|is not in list of acceptable)"):
            k193.set_sense_function("FREQ")

    def test_set_measurement_coupling(self, k193):
        """set_measurement_coupling writes F0X for DC and F1X for AC."""
        k193.set_measurement_coupling("AC")
        k193.instrument.write.assert_called_with("F1X")

        k193.set_measurement_coupling(coupling="DC")
        k193.instrument.write.assert_called_with("F0X")

    def test_set_sense_mode(self, k193):
        """set_sense_mode: 2W is safe no-op; 4W raises NotImplementedError."""
        k193.set_sense_mode("2W")

        with pytest.raises(NotImplementedError, match="does not support software-commanded 4-wire mode"):
            k193.set_sense_mode("4W")

    def test_set_sense_range_autorange(self, k193):
        """set_sense_range(auto=True) writes R0X; auto=False raises NotImplementedError."""
        k193.set_sense_range(auto=True)
        k193.instrument.write.assert_called_with("R0X")

        with pytest.raises(NotImplementedError, match="manual range configuration is not supported"):
            k193.set_sense_range(range_val=10.0, auto=False)

    def test_set_integration_time_rate_mapping(self, k193):
        """set_integration_time maps NPLC thresholds to S0X–S3X."""
        k193.set_integration_time(0.005)
        k193.instrument.write.assert_called_with("S0X")

        k193.set_integration_time(0.05)
        k193.instrument.write.assert_called_with("S1X")

        k193.set_integration_time(0.5)
        k193.instrument.write.assert_called_with("S2X")

        k193.set_integration_time(2.0)
        k193.instrument.write.assert_called_with("S3X")

    def test_get_voltage(self, k193):
        """get_voltage sends F0X/F1X and extracts numeric float from response."""
        k193.instrument.read.return_value = "NDCV+001.2345E-03\r\n"

        v = k193.get_voltage(ac=False)
        k193.instrument.write.assert_called_with("F0X")
        assert isinstance(v, float)
        assert v == pytest.approx(0.0012345)

        k193.instrument.read.return_value = "NACV+002.5000E-01\r\n"
        v_ac = k193.get_voltage(ac=True)
        k193.instrument.write.assert_called_with("F1X")
        assert isinstance(v_ac, float)
        assert v_ac == pytest.approx(0.25)

    def test_get_voltage_finite_and_overflow_parsing(self, k193):
        """Keithley 193A normalizes OVOL overflow responses to float('inf')."""
        # Negative voltage
        k193.instrument.read.return_value = "NDCV-003.5000E+00\r\n"
        assert k193.get_voltage() == pytest.approx(-3.5)

        # Positive overflow response normalized to +inf
        k193.instrument.read.return_value = "OVOL+999.9999E+30\r\n"
        v_ovfl = k193.get_voltage()
        assert isinstance(v_ovfl, float)
        assert np.isinf(v_ovfl) and v_ovfl > 0
        assert not np.isfinite(v_ovfl)

        # Negative overflow response normalized to -inf
        k193.instrument.read.return_value = "OVOL-999.9999E+30\r\n"
        v_novfl = k193.get_voltage()
        assert isinstance(v_novfl, float)
        assert np.isinf(v_novfl) and v_novfl < 0
        assert not np.isfinite(v_novfl)

    def test_quick_read(self, k193):
        """quick_read delegates to get_voltage() and returns float."""
        k193.instrument.read.return_value = "NDCV+000.0420E+00\r\n"
        assert k193.quick_read() == pytest.approx(0.042)

    def test_other_measurement_functions(self, k193):
        """get_current, get_resistance, get_temperature send DDC codes and extract floats."""
        k193.instrument.read.return_value = "NDCA+000.0050E-03\r\n"
        assert k193.get_current() == pytest.approx(5e-6)
        k193.instrument.write.assert_called_with("F3X")

        k193.instrument.read.return_value = "NOHM+001.0000E+03\r\n"
        assert k193.get_resistance() == pytest.approx(1000.0)
        k193.instrument.write.assert_called_with("F2X")

        k193.instrument.read.return_value = "NTMP+000.0010E+00\r\n"
        assert k193.get_temperature(probe_type="RTD") == pytest.approx(1e-3)
        k193.instrument.write.assert_called_with("F6X")

    def test_ddc_reset_and_clear(self, k193):
        """reset sends L0X and clear invokes instrument.clear()."""
        k193.reset()
        k193.instrument.write.assert_called_with("L0X")

        k193.clear()
        k193.instrument.clear.assert_called_once()


# ============================================================================
# 6. Real MOKE Measurement Integration Across All Advertised DMMs
# ============================================================================

class TestMokeMeasurementIntegration:
    """Verify real MokeMeasurement configuration, execution, and overload rejection across all DMMs."""

    def _setup_dmm(self, driver_cls, overload=False):
        if driver_cls is VirtualDMM:
            dmm = VirtualDMM()
            if overload:
                dmm.set_voltage_reader(lambda: float("inf"))
            else:
                dmm.set_voltage_reader(lambda: 0.1234)
            return dmm

        inst = driver_cls.__new__(driver_cls)
        inst.instrument = Mock()
        inst.idn = Mock(return_value=f"Mock {driver_cls.__name__}")

        if driver_cls is Agilent34410A:
            inst.instrument.query.return_value = "+9.90000000E+37\n" if overload else "+1.23450000E-01\n"
        elif driver_cls is Keithley2000:
            inst.instrument.query.return_value = "+9.99999900E+37\n" if overload else "+1.23450000E-01\n"
        elif driver_cls is Keithley193a:
            inst.instrument.read.return_value = "OVOL+999.9999E+30\r\n" if overload else "NDCV+001.2345E-01\r\n"

        return inst

    def _create_moke(self, dmm):
        source = VirtualSourcemeter()
        cal = FieldCalibration([(-5, -500), (0, 0), (5, 500)], name="test_cal")
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-1.0, 0.0, 1.0, 0.0, -1.0],
            compliance=0.01,
            max_output_step=2.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            n_cycles=1,
        )
        return moke

    @pytest.mark.parametrize("driver_cls", ALL_DMM_DRIVERS)
    def test_moke_configuration_sequence_across_drivers(self, driver_cls):
        """MokeMeasurement.configure_instruments configures voltage sense and DC coupling."""
        dmm = self._setup_dmm(driver_cls, overload=False)
        moke = self._create_moke(dmm)

        moke.configure_instruments()

        if driver_cls is VirtualDMM:
            assert dmm.state["sense_func"] == "VOLT"
            assert dmm.state["coupling"] == "DC"
        elif driver_cls is Agilent34410A:
            dmm.instrument.write.assert_any_call("CONF:VOLT:DC")
            assert dmm._scpi_sense_func == "VOLT:DC"
        elif driver_cls is Keithley2000:
            dmm.instrument.write.assert_any_call(":SENS:FUNC 'VOLT:DC'")
            assert dmm._scpi_sense_func == "VOLT:DC"
        elif driver_cls is Keithley193a:
            dmm.instrument.write.assert_any_call("F0X")

    @pytest.mark.parametrize("driver_cls", ALL_DMM_DRIVERS)
    def test_moke_measurement_normal_execution_with_each_dmm(self, driver_cls):
        """MokeMeasurement runs cleanly with every advertised DMM, recording finite voltages and safing source."""
        dmm = self._setup_dmm(driver_cls, overload=False)
        moke = self._create_moke(dmm)

        moke.configure_instruments()
        df = moke.capture_data()

        assert not df.empty
        assert moke.completed_cycles == 1
        assert "detector_voltage" in df.columns
        assert all(np.isfinite(df["detector_voltage"]))
        # Safing must have de-energized the sourcemeter output
        assert moke.sourcemeter.get_state()["output_on"] is False

    @pytest.mark.parametrize("driver_cls", ALL_DMM_DRIVERS)
    def test_moke_measurement_overload_rejection_and_safing(self, driver_cls):
        """Overload detector response is rejected by MOKE, raising ValueError and safing the sourcemeter."""
        dmm = self._setup_dmm(driver_cls, overload=True)
        moke = self._create_moke(dmm)

        moke.configure_instruments()

        with pytest.raises(ValueError, match="DMM returned a non-finite detector voltage"):
            moke.capture_data()

        # Crucial safety invariant: sourcemeter must be shut off despite the acquisition exception
        assert moke.sourcemeter.get_state()["output_on"] is False


# ============================================================================
# 7. Optional Features and Explicit Capability Gating
# ============================================================================

class TestOptionalCapabilityGating:
    """Verify that optional DMM methods behave safely and unsupported configurations are explicitly gated."""

    def test_optional_decorators_on_unsupported_drivers(self):
        """Unsupported optional category methods gracefully return None via @optional decorator."""
        v_dmm = VirtualDMM()
        assert v_dmm.get_frequency() is None
        assert v_dmm.get_temperature() is None
        assert v_dmm.get_capacitance() is None

        k193 = Keithley193a.__new__(Keithley193a)
        k193.instrument = Mock()
        assert k193.get_frequency() is None
        assert k193.get_capacitance() is None

        agilent = Agilent34410A.__new__(Agilent34410A)
        agilent.instrument = Mock()
        assert agilent.get_temperature() is None

        k2000 = Keithley2000.__new__(Keithley2000)
        k2000.instrument = Mock()
        assert k2000.get_capacitance() is None

    def test_unsupported_configuration_capability_gating(self):
        """Unsupported optional configurations raise explicit NotImplementedError rather than silent no-ops."""
        # Keithley 193A does not support software manual range
        k193 = Keithley193a.__new__(Keithley193a)
        k193.instrument = Mock()
        with pytest.raises(NotImplementedError, match="manual range configuration is not supported"):
            k193.set_sense_range(range_val=10.0, auto=False)

        # Keithley 193A does not support software-commanded 4-wire mode
        with pytest.raises(NotImplementedError, match="does not support software-commanded 4-wire mode"):
            k193.set_sense_mode("4W")

        # Agilent 34410A does not support NPLC in AC mode
        agilent = Agilent34410A.__new__(Agilent34410A)
        agilent.instrument = Mock()
        agilent.instrument.query.return_value = '"VOLT:AC"\n'
        with pytest.raises(NotImplementedError, match="does not support NPLC"):
            agilent.set_integration_time(10)

        # Keithley 2000 does not support NPLC in AC mode
        k2000 = Keithley2000.__new__(Keithley2000)
        k2000.instrument = Mock()
        k2000.instrument.query.return_value = "0.0\n"
        k2000.get_voltage(ac=True)
        with pytest.raises(NotImplementedError, match="does not support NPLC"):
            k2000.set_integration_time(10)
