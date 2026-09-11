"""
Tests for VirtualDMM generic per-instance virtual hooks (Checkpoint 28b).

Validates:
- Generic per-instance hook injection (voltage_reader and reader_hook alias);
- Explicit injection precedence over deprecated global sample fallback;
- Fallback property is not accessed when explicit hook is present;
- Material-specific logic kept strictly outside generic driver;
- Scalar float voltage responses in Volts;
- IEEE 754 non-finite floats (inf, -inf, nan) allowed for overload contract;
- Rejection of non-scalar collections (tuple, list, non-0d ndarray) with TypeError;
- Declared physical units ({"voltage": "V"});
- Unchanged error propagation without retries (RuntimeError, TypeError);
- Exact-once invocation and signature binding (0-arg, ac kwarg, coupling kwarg, positional ac);
- Instance isolation protecting VirtualInstrument._shared_mag_sample;
- Reset ownership: driver-owned state restored, hook preserved, setup-owned state untouched.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation.magnetic_material import MagneticSample


# ============================================================================
# 1. Hook Injection and Aliases
# ============================================================================

class TestVirtualDMMHookInjection:
    """Validation of hook injection, aliases, and properties."""

    def test_constructor_accepts_voltage_reader(self):
        hook = lambda: 1.234
        dmm = VirtualDMM(voltage_reader=hook)
        assert dmm.voltage_reader is hook
        assert dmm.reader_hook is hook

    def test_constructor_accepts_reader_hook_alias(self):
        hook = lambda: 5.678
        dmm = VirtualDMM(reader_hook=hook)
        assert dmm.voltage_reader is hook
        assert dmm.reader_hook is hook

    def test_constructor_identical_hooks_accepted(self):
        hook = lambda: 2.468
        dmm = VirtualDMM(voltage_reader=hook, reader_hook=hook)
        assert dmm.voltage_reader is hook

    def test_constructor_conflicting_hooks_rejected(self):
        hook1 = lambda: 1.0
        hook2 = lambda: 2.0
        with pytest.raises(ValueError, match="Cannot specify both"):
            VirtualDMM(voltage_reader=hook1, reader_hook=hook2)

    def test_constructor_rejects_non_callable_hook(self):
        with pytest.raises(TypeError, match="voltage_reader must be callable or None"):
            VirtualDMM(voltage_reader="not_a_callable")

    def test_method_and_property_injection(self):
        dmm = VirtualDMM()
        assert dmm.voltage_reader is None
        assert dmm.reader_hook is None

        hook1 = lambda: 0.1
        dmm.set_voltage_reader(hook1)
        assert dmm.voltage_reader is hook1

        hook2 = lambda: 0.2
        dmm.set_reader_hook(hook2)
        assert dmm.voltage_reader is hook2

        hook3 = lambda: 0.3
        dmm.voltage_reader = hook3
        assert dmm.voltage_reader is hook3

        hook4 = lambda: 0.4
        dmm.reader_hook = hook4
        assert dmm.reader_hook is hook4

        dmm.set_voltage_reader(None)
        assert dmm.voltage_reader is None
        assert dmm.reader_hook is None

    def test_injection_rejects_non_callable(self):
        dmm = VirtualDMM()
        with pytest.raises(TypeError, match="voltage_reader must be callable or None"):
            dmm.set_voltage_reader(12345)
        with pytest.raises(TypeError, match="voltage_reader must be callable or None"):
            dmm.voltage_reader = [1, 2]
        with pytest.raises(TypeError, match="voltage_reader must be callable or None"):
            dmm.set_reader_hook("invalid")
        with pytest.raises(TypeError, match="voltage_reader must be callable or None"):
            dmm.reader_hook = {"v": 1.0}


# ============================================================================
# 2. Precedence, Fallback, and Material Decoupling
# ============================================================================

class TestPrecedenceAndDecoupling:
    """Precedence of explicit injection over global fallback and material decoupling."""

    def test_explicit_injection_takes_precedence_over_mag_sample(self):
        class MockSample:
            current_field = 50000.0  # Would give 5.0 V in fallback

        dmm = VirtualDMM()
        dmm.mag_sample = MockSample()

        # Without hook: fallback computes current_field / 10000.0
        assert dmm.get_voltage() == pytest.approx(5.0)

        # Injected hook overrides fallback
        dmm.set_voltage_reader(lambda: 0.042)
        assert dmm.get_voltage() == pytest.approx(0.042)
        assert dmm.quick_read() == pytest.approx(0.042)

        # Clear hook: fallback is restored
        dmm.set_voltage_reader(None)
        assert dmm.get_voltage() == pytest.approx(5.0)

    def test_hook_precedence_does_not_access_fallback_property(self):
        """When an explicit hook is set, mag_sample must not even be accessed."""
        class HookOnlyDMM(VirtualDMM):
            @property
            def mag_sample(self):
                raise AssertionError("mag_sample fallback must not be accessed when hook is present")

        dmm = HookOnlyDMM(voltage_reader=lambda: 3.14)
        assert dmm.get_voltage() == pytest.approx(3.14)
        assert dmm.quick_read() == pytest.approx(3.14)

    def test_default_fallback_without_mag_sample(self):
        dmm = VirtualDMM()
        dmm.mag_sample = None
        assert dmm.get_voltage() == pytest.approx(0.0015)
        assert dmm.quick_read() == pytest.approx(0.0015)

    def test_material_logic_remains_outside_generic_driver(self):
        """VirtualDMM has no sensor or magnetic equations; hook evaluates external physics."""
        # Simulated Hall sensor with calibration 0.0001 V/Oe
        sensor_state = {"field_oe": 1500.0}

        def hall_sensor_hook():
            return sensor_state["field_oe"] * 1e-4

        dmm = VirtualDMM(voltage_reader=hall_sensor_hook)
        assert dmm.get_voltage() == pytest.approx(0.15)

        # Change external field; DMM observes new voltage via hook
        sensor_state["field_oe"] = -800.0
        assert dmm.get_voltage() == pytest.approx(-0.08)


# ============================================================================
# 3. Declared Units, Response Types, and Validation
# ============================================================================

class TestDeclaredUnitsAndResponseValidation:
    """Validation of return types, units, and non-finite numbers."""

    def test_declared_units(self):
        dmm = VirtualDMM()
        assert dmm.declared_units["voltage"] == "V"
        assert len(dmm.declared_units) == 1
        # Mapping should be read-only (MappingProxyType)
        with pytest.raises((TypeError, AttributeError)):
            dmm.declared_units["voltage"] = "mV"  # type: ignore

    def test_scalar_float_and_0d_array(self):
        dmm = VirtualDMM(voltage_reader=lambda: 1.5)
        val = dmm.get_voltage()
        assert isinstance(val, float)
        assert val == 1.5

        # 0-d numpy array converts to scalar float
        dmm.voltage_reader = lambda: np.array(2.75)
        val0d = dmm.get_voltage()
        assert isinstance(val0d, float)
        assert val0d == 2.75

        # int converts to float
        dmm.voltage_reader = lambda: 42
        val_int = dmm.get_voltage()
        assert isinstance(val_int, float)
        assert val_int == 42.0

    def test_ieee754_non_finite_values_preserved_for_overload(self):
        """Per DMM contract (Checkpoint 6), non-finite IEEE 754 floats represent overloads."""
        for non_finite in [float("inf"), float("-inf"), float("nan")]:
            dmm = VirtualDMM(voltage_reader=lambda nf=non_finite: nf)
            v = dmm.get_voltage()
            assert isinstance(v, float)
            if math.isnan(non_finite):
                assert math.isnan(v)
            else:
                assert math.isinf(v)
                assert (v > 0) == (non_finite > 0)

    @pytest.mark.parametrize("bad_response", [
        None,
        "not_a_number",
        (1.0, 2.0),
        [1.0],
        {1.0},
        {"voltage": 1.0},
        np.array([1.0]),
        np.ones((2, 2)),
    ])
    def test_non_scalar_and_invalid_responses_rejected(self, bad_response):
        dmm = VirtualDMM(voltage_reader=lambda: bad_response)
        with pytest.raises(TypeError):
            dmm.get_voltage()


# ============================================================================
# 4. Signature Binding, Error Propagation, and Exact-Once Invocation
# ============================================================================

class TestSignatureBindingAndErrorPropagation:
    """Exact-once invocation, signature binding, and error preservation."""

    def test_zero_argument_hook(self):
        calls = []
        def reader():
            calls.append(1)
            return 0.123

        dmm = VirtualDMM(voltage_reader=reader)
        assert dmm.get_voltage() == pytest.approx(0.123)
        assert len(calls) == 1

    def test_hook_with_ac_keyword_receives_coupling_state(self):
        received_ac = []
        def reader(*, ac):
            received_ac.append(ac)
            return 2.0 if ac else 1.0

        dmm = VirtualDMM(voltage_reader=reader)
        assert dmm.get_voltage(ac=False) == pytest.approx(1.0)
        assert received_ac[-1] is False

        assert dmm.get_voltage(ac=True) == pytest.approx(2.0)
        assert received_ac[-1] is True

    def test_hook_with_coupling_keyword_receives_coupling_state(self):
        received_coupling = []
        def reader(*, coupling):
            received_coupling.append(coupling)
            return 3.0 if coupling == "AC" else 0.5

        dmm = VirtualDMM(voltage_reader=reader)
        assert dmm.get_voltage(ac=False) == pytest.approx(0.5)
        assert received_coupling[-1] == "DC"

        assert dmm.get_voltage(ac=True) == pytest.approx(3.0)
        assert received_coupling[-1] == "AC"

    def test_hook_with_positional_only_ac(self):
        received = []
        def reader(ac, /):
            received.append(ac)
            return 9.9 if ac else 0.9

        dmm = VirtualDMM(voltage_reader=reader)
        assert dmm.get_voltage(ac=False) == pytest.approx(0.9)
        assert received[-1] is False
        assert dmm.get_voltage(ac=True) == pytest.approx(9.9)
        assert received[-1] is True

    def test_hook_with_optional_ac(self):
        def reader(ac=False):
            return 5.0 if ac else 2.5

        dmm = VirtualDMM(voltage_reader=reader)
        assert dmm.get_voltage(ac=False) == pytest.approx(2.5)
        assert dmm.get_voltage(ac=True) == pytest.approx(5.0)

    def test_incompatible_hook_signature_raises_type_error(self):
        def bad_sig(x, y, z):
            return 1.0

        dmm = VirtualDMM(voltage_reader=bad_sig)
        with pytest.raises(TypeError, match="voltage_reader must accept no arguments"):
            dmm.get_voltage()

    @pytest.mark.parametrize("error_cls", [RuntimeError, TypeError, ValueError, ZeroDivisionError])
    def test_hook_exception_propagates_unchanged_without_retries(self, error_cls):
        calls = []
        error = error_cls("Simulated sensor communication breakdown")

        def failing_hook(*args, **kwargs):
            calls.append((args, kwargs))
            raise error

        dmm = VirtualDMM(voltage_reader=failing_hook)
        with pytest.raises(error_cls) as exc_info:
            dmm.get_voltage()

        # Exact exception identity preserved
        assert exc_info.value is error
        # Invoked exactly once, no retry with alternative signatures
        assert len(calls) == 1


# ============================================================================
# 5. Deterministic Reset and Instance Isolation
# ============================================================================

class TestDeterministicResetAndInstanceIsolation:
    """Reset ownership and isolation of state across instances."""

    def test_reset_restores_driver_state_and_preserves_hook(self):
        hook = lambda: 1.234
        dmm = VirtualDMM(voltage_reader=hook)

        # Mutate driver-owned state
        dmm.set_sense_function("CURR")
        dmm.set_measurement_coupling("AC")
        dmm.set_sense_mode("4W")
        dmm.set_sense_range(10.0, auto=False)
        dmm.set_integration_time(5.0)

        # Verify mutated state
        state = dmm.get_state()
        assert state["sense_func"] == "CURR"
        assert state["coupling"] == "AC"
        assert state["sense_mode"] == "4W"
        assert state["autorange"] is False
        assert state["sense_range"] == 10.0
        assert state["integration_time"] == 5.0

        # Execute driver reset
        dmm.reset()

        # State is restored to factory defaults
        reset_state = dmm.get_state()
        assert reset_state["sense_func"] == "VOLT"
        assert reset_state["coupling"] == "DC"
        assert reset_state["sense_mode"] == "2W"
        assert reset_state["autorange"] is True
        assert reset_state["sense_range"] is None
        assert reset_state["integration_time"] == 1.0

        # Hook is preserved
        assert dmm.voltage_reader is hook
        assert dmm.get_voltage() == pytest.approx(1.234)

    def test_reset_does_not_mutate_setup_owned_closure_state(self):
        """Driver reset does NOT reset setup-owned state (external material/timebase/RNG)."""
        external_timebase = {"time": 10.5}

        def time_dependent_hook():
            return external_timebase["time"] * 0.1

        dmm = VirtualDMM(voltage_reader=time_dependent_hook)
        assert dmm.get_voltage() == pytest.approx(1.05)

        # Reset driver
        dmm.reset()
        # External state is untouched
        assert external_timebase["time"] == 10.5
        assert dmm.get_voltage() == pytest.approx(1.05)

    def test_instance_sample_assignment_isolated_from_shared_and_other_instances(self, monkeypatch):
        """Mutating mag_sample on one instance does not mutate VirtualInstrument._shared_mag_sample."""
        class SharedSample:
            current_field = 10000.0

        shared = SharedSample()
        monkeypatch.setattr(VirtualInstrument, "_shared_mag_sample", shared)

        dmm1 = VirtualDMM()
        dmm2 = VirtualDMM()

        assert dmm1.mag_sample is shared
        assert dmm2.mag_sample is shared

        # Mutate instance 1
        dmm1.mag_sample = None
        dmm1.voltage_reader = lambda: 7.77

        # dmm1 uses hook; dmm2 uses shared sample
        assert dmm1.get_voltage() == pytest.approx(7.77)
        assert dmm2.get_voltage() == pytest.approx(1.0)  # 10000 / 10000 = 1.0 V

        # Global shared sample is completely unaffected
        assert VirtualInstrument._shared_mag_sample is shared

        # Deleting instance override on dmm1 restores access to shared sample
        del dmm1.mag_sample
        dmm1.voltage_reader = None
        assert dmm1.mag_sample is shared
        assert dmm1.get_voltage() == pytest.approx(1.0)

    def test_clear_is_safe_noop(self):
        dmm = VirtualDMM()
        assert dmm.clear() is None

    def test_idn_returns_virtual_dmm(self):
        dmm = VirtualDMM()
        assert dmm.idn() == "Virtual DMM"
