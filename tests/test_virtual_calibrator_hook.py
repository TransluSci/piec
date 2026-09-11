"""
Tests for VirtualCalibrator generic per-instance virtual hooks (Checkpoint 28c).

Validates:
- Generic per-instance hook injection (output_hook and field_hook alias);
- Explicit injection precedence over deprecated global sample fallback;
- Fallback property is not accessed when explicit hook is present;
- Material-specific logic kept strictly outside generic driver;
- Command validation (finite numeric, mode validation, state preservation on failure);
- Declared physical units ({"voltage": "V", "current": "A"});
- Unchanged error propagation without retries (RuntimeError, TypeError, ValueError);
- Exact-once invocation and signature binding (1-arg, positional-only, mode, output_on, kwargs);
- Instance isolation protecting VirtualInstrument._shared_mag_sample;
- Reset ownership: driver-owned state restored with output disabled, hook preserved, setup-owned state untouched.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.virtual_instrument import VirtualInstrument


@pytest.fixture(autouse=True)
def clean_shared_mag_sample():
    """Ensure shared magnetic sample remains at zero field across tests."""
    yield
    if hasattr(VirtualInstrument, "_shared_mag_sample") and VirtualInstrument._shared_mag_sample is not None:
        VirtualInstrument._shared_mag_sample.current_field = 0.0


# ============================================================================
# 1. Hook Injection and Aliases
# ============================================================================

class TestVirtualCalibratorHookInjection:
    """Validation of hook injection, aliases, and properties."""

    def test_constructor_accepts_output_hook(self):
        hook = lambda v: None
        cal = VirtualCalibrator(output_hook=hook)
        assert cal.output_hook is hook
        assert cal.field_hook is hook

    def test_constructor_accepts_field_hook_alias(self):
        hook = lambda v: None
        cal = VirtualCalibrator(field_hook=hook)
        assert cal.output_hook is hook
        assert cal.field_hook is hook

    def test_constructor_identical_hooks_accepted(self):
        hook = lambda v: None
        cal = VirtualCalibrator(output_hook=hook, field_hook=hook)
        assert cal.output_hook is hook

    def test_constructor_conflicting_hooks_rejected(self):
        hook1 = lambda v: None
        hook2 = lambda v: None
        with pytest.raises(ValueError, match="Cannot specify both"):
            VirtualCalibrator(output_hook=hook1, field_hook=hook2)

    def test_constructor_rejects_non_callable_hook(self):
        with pytest.raises(TypeError, match="output_hook must be callable or None"):
            VirtualCalibrator(output_hook="not_a_callable")

    def test_method_and_property_injection(self):
        cal = VirtualCalibrator()
        assert cal.output_hook is None
        assert cal.field_hook is None

        hook1 = lambda v: None
        cal.set_output_hook(hook1)
        assert cal.output_hook is hook1

        hook2 = lambda v: None
        cal.set_field_hook(hook2)
        assert cal.output_hook is hook2

        hook3 = lambda v: None
        cal.output_hook = hook3
        assert cal.output_hook is hook3

        hook4 = lambda v: None
        cal.field_hook = hook4
        assert cal.field_hook is hook4

        cal.set_output_hook(None)
        assert cal.output_hook is None
        assert cal.field_hook is None

    def test_injection_rejects_non_callable(self):
        cal = VirtualCalibrator()
        with pytest.raises(TypeError, match="output_hook must be callable or None"):
            cal.set_output_hook(12345)
        with pytest.raises(TypeError, match="output_hook must be callable or None"):
            cal.output_hook = [1, 2]
        with pytest.raises(TypeError, match="output_hook must be callable or None"):
            cal.set_field_hook("invalid")
        with pytest.raises(TypeError, match="output_hook must be callable or None"):
            cal.field_hook = {"v": 1.0}


# ============================================================================
# 2. Precedence, Fallback, and Material Decoupling
# ============================================================================

class TestPrecedenceAndDecoupling:
    """Precedence of explicit injection over global fallback and material decoupling."""

    def test_explicit_injection_takes_precedence_over_mag_sample(self):
        class MockSample:
            current_field = 0.0

        cal = VirtualCalibrator(voltage_calibration=10000.0)
        cal.mag_sample = MockSample()

        # Without hook: fallback updates sample current_field
        cal.set_voltage(0.05)
        assert cal.mag_sample.current_field == pytest.approx(500.0)

        # Injected hook overrides fallback; sample is not updated by hook calls
        received_outputs = []
        cal.set_output_hook(lambda v: received_outputs.append(v))

        cal.set_voltage(0.1)
        assert received_outputs == [0.1]
        # Sample current_field was NOT updated from 500.0 to 1000.0
        assert cal.mag_sample.current_field == pytest.approx(500.0)

        # Clear hook: fallback is restored
        cal.set_output_hook(None)
        cal.set_voltage(0.2)
        assert cal.mag_sample.current_field == pytest.approx(2000.0)

    def test_hook_precedence_does_not_access_fallback_property(self):
        """When an explicit hook is set, mag_sample must not even be accessed."""
        class HookOnlyCalibrator(VirtualCalibrator):
            @property
            def mag_sample(self):
                raise AssertionError("mag_sample fallback must not be accessed when hook is present")

        received = []
        cal = HookOnlyCalibrator(output_hook=lambda v: received.append(v))
        cal.set_voltage(0.03)
        assert received == [0.03]
        cal.output(False)
        assert received == [0.03, 0.0]

    def test_material_logic_remains_outside_generic_driver(self):
        """VirtualCalibrator has no magnet or coil formulas; hook evaluates external physics."""
        # Simulated electromagnet coil with non-linear or calibrated factor
        coil_state = {"coil_current_a": 0.0, "field_oe": 0.0}

        def electromagnet_hook(voltage):
            # Coil resistance 10 Ohm, magnet factor 500 Oe/A
            i = voltage / 10.0
            coil_state["coil_current_a"] = i
            coil_state["field_oe"] = i * 500.0

        cal = VirtualCalibrator(output_hook=electromagnet_hook)
        cal.set_voltage(2.0)
        assert coil_state["coil_current_a"] == pytest.approx(0.2)
        assert coil_state["field_oe"] == pytest.approx(100.0)

        cal.set_voltage(-1.0)
        assert coil_state["coil_current_a"] == pytest.approx(-0.1)
        assert coil_state["field_oe"] == pytest.approx(-50.0)

        cal.output(False)
        assert coil_state["coil_current_a"] == 0.0
        assert coil_state["field_oe"] == 0.0


# ============================================================================
# 3. Declared Units, State, and Input Validation
# ============================================================================

class TestDeclaredUnitsAndInputValidation:
    """Validation of units, state copies, and command input checking."""

    def test_declared_units(self):
        cal = VirtualCalibrator()
        assert cal.declared_units["voltage"] == "V"
        assert cal.declared_units["current"] == "A"
        assert len(cal.declared_units) == 2
        with pytest.raises((TypeError, AttributeError)):
            cal.declared_units["voltage"] = "mV"  # type: ignore

    def test_initial_state_and_get_state_copy(self):
        cal = VirtualCalibrator()
        state = cal.get_state()
        assert state["output_on"] is True
        assert state["mode"] == "voltage"
        assert state["voltage"] == 0.0
        assert state["current"] == 0.0

        # State copy is detached
        state["voltage"] = 999.0
        assert cal.get_voltage() == 0.0

    def test_set_voltage_and_get_voltage(self):
        cal = VirtualCalibrator(output_hook=lambda v: None)
        cal.set_voltage(3.5)
        assert cal.get_voltage() == pytest.approx(3.5)
        assert cal.state["mode"] == "voltage"

    def test_set_current_and_get_current(self):
        cal = VirtualCalibrator(output_hook=lambda v: None)
        cal.set_current(0.025)
        assert cal.get_current() == pytest.approx(0.025)
        assert cal.state["mode"] == "current"

    @pytest.mark.parametrize("invalid_value", [
        float("nan"), float("inf"), float("-inf"),
    ])
    def test_non_finite_values_rejected_and_state_preserved(self, invalid_value):
        cal = VirtualCalibrator(output_hook=lambda v: None)
        cal.set_voltage(1.23)
        before = cal.get_state()

        with pytest.raises(ValueError, match="finite"):
            cal.set_voltage(invalid_value)
        assert cal.get_state() == before

        with pytest.raises(ValueError, match="finite"):
            cal.set_current(invalid_value)
        assert cal.get_state() == before

        with pytest.raises(ValueError, match="finite"):
            cal.set_output(invalid_value, mode="voltage")
        assert cal.get_state() == before

    @pytest.mark.parametrize("bad_type_value", [
        "not_a_number", None, [1.0], (1.0,), True, False, {"v": 1.0},
    ])
    def test_non_numeric_values_rejected(self, bad_type_value):
        cal = VirtualCalibrator()
        with pytest.raises(TypeError, match="numeric"):
            cal.set_output(bad_type_value)

    def test_unsupported_mode_rejected(self):
        cal = VirtualCalibrator()
        before = cal.get_state()
        with pytest.raises(ValueError, match="unsupported mode"):
            cal.set_output(1.0, mode="frequency")
        assert cal.get_state() == before

    @pytest.mark.parametrize("invalid_cal", [0.0, -100.0, float("nan"), float("inf")])
    def test_voltage_calibration_validation(self, invalid_cal):
        with pytest.raises(ValueError, match="positive finite number"):
            VirtualCalibrator(voltage_calibration=invalid_cal)

        cal = VirtualCalibrator()
        with pytest.raises(ValueError, match="positive finite number"):
            cal.voltage_calibration = invalid_cal
        with pytest.raises(ValueError, match="positive finite number"):
            cal.voltage_callibration = invalid_cal

    def test_voltage_calibration_alias_roundtrip(self):
        cal = VirtualCalibrator(voltage_callibration=5000.0)
        assert cal.voltage_calibration == 5000.0
        assert cal.voltage_callibration == 5000.0

        cal.voltage_callibration = 2500.0
        assert cal.voltage_calibration == 2500.0
        assert cal.voltage_callibration == 2500.0


# ============================================================================
# 4. Signature Binding, Error Propagation, and Exact-Once Invocation
# ============================================================================

class TestSignatureBindingAndErrorPropagation:
    """Exact-once invocation, signature binding, and error preservation."""

    def test_single_positional_argument_hook(self):
        calls = []
        def hook(v):
            calls.append(v)

        cal = VirtualCalibrator(output_hook=hook)
        cal.set_voltage(1.5)
        assert calls == [1.5]

    def test_positional_only_argument_hook(self):
        calls = []
        def hook(val, /):
            calls.append(val)

        cal = VirtualCalibrator(output_hook=hook)
        cal.set_voltage(2.5)
        assert calls == [2.5]

    def test_hook_with_mode_and_output_on(self):
        received = []
        def hook(value, mode, *, output_on):
            received.append((value, mode, output_on))

        cal = VirtualCalibrator(output_hook=hook)
        cal.set_voltage(0.1)
        assert received == [(0.1, "voltage", True)]

        cal.output(False)
        assert received[-1] == (0.0, "voltage", False)

        cal.set_current(0.005)
        assert received[-1] == (0.005, "current", True)

    def test_hook_with_voltage_keyword(self):
        received = []
        def hook(*, voltage, on):
            received.append((voltage, on))

        cal = VirtualCalibrator(output_hook=hook)
        cal.set_voltage(4.2)
        assert received == [(4.2, True)]

    def test_hook_with_kwargs(self):
        received = []
        def hook(**kwargs):
            received.append(kwargs)

        cal = VirtualCalibrator(output_hook=hook)
        cal.set_voltage(0.075)
        assert len(received) == 1
        assert received[0]["value"] == pytest.approx(0.075)
        assert received[0]["mode"] == "voltage"
        assert received[0]["output_on"] is True

    def test_zero_argument_hook(self):
        calls = []
        def hook():
            calls.append(1)

        cal = VirtualCalibrator(output_hook=hook)
        cal.set_voltage(1.0)
        assert len(calls) == 1

    def test_incompatible_hook_signature_raises_type_error(self):
        def bad_sig(a, b, c, d, e):
            pass

        cal = VirtualCalibrator(output_hook=bad_sig)
        with pytest.raises(TypeError, match="output_hook has incompatible signature"):
            cal.set_voltage(1.0)

    @pytest.mark.parametrize("error_cls", [RuntimeError, TypeError, ValueError, ZeroDivisionError])
    def test_hook_exception_propagates_unchanged_without_retries(self, error_cls):
        calls = []
        error = error_cls("Simulated DAC hardware timeout")

        def failing_hook(*args, **kwargs):
            calls.append((args, kwargs))
            raise error

        cal = VirtualCalibrator(output_hook=failing_hook)
        with pytest.raises(error_cls) as exc_info:
            cal.set_voltage(1.0)

        assert exc_info.value is error
        assert len(calls) == 1


# ============================================================================
# 5. Deterministic Reset and Instance Isolation
# ============================================================================

@pytest.mark.parametrize("mode", ["voltage", "current"])
def test_crowbar_sends_zero_in_both_electrical_units(mode):
    calls = []
    cal = VirtualCalibrator(output_hook=lambda **data: calls.append(data))
    cal.set_voltage(5.0)
    cal.set_current(0.02)
    cal.set_output(2.0, mode=mode)
    cal.set_output(0, mode="crowbar")
    assert calls[-1]["value"] == 0
    assert calls[-1]["voltage"] == calls[-1]["current"] == 0
    assert calls[-1]["mode"] == mode
    assert calls[-1]["output_on"] is False
    cal.output(True)
    assert calls[-1]["value"] == 2.0


def test_mode_switch_does_not_report_stale_inactive_output():
    calls = []
    cal = VirtualCalibrator(output_hook=lambda *, voltage, current: calls.append((voltage, current)))
    cal.set_voltage(5)
    cal.set_current(0.02)
    assert calls == [(5, 0), (0, 0.02)]


def test_variadic_output_hook_receives_the_command_value():
    calls = []
    cal = VirtualCalibrator(output_hook=lambda *args: calls.append(args))
    cal.set_voltage(3)
    cal.output(False)
    assert calls == [(3,), (0,)]


@pytest.mark.parametrize("operation", ["set", "off", "crowbar", "reset"])
def test_failed_hook_marks_output_unconfirmed_until_successful_command(operation):
    calls = []
    error = RuntimeError("output update failed")
    def fail(value):
        calls.append(value)
        raise error
    cal = VirtualCalibrator(output_hook=lambda value: None)
    cal.set_voltage(5)
    cal.output_hook = fail
    actions = {"set": lambda: cal.set_voltage(3), "off": lambda: cal.output(False),
               "crowbar": lambda: cal.set_output(0, mode="crowbar"), "reset": cal.reset}
    with pytest.raises(RuntimeError) as result:
        actions[operation]()
    assert result.value is error
    assert len(calls) == 1
    assert cal.get_state()["output_on"] is None
    assert cal._output_enabled is None
    cal.output_hook = lambda value: None
    cal.output(False)
    assert cal.get_state()["output_on"] is False


@pytest.mark.parametrize("bad_on", ["off", "false", None, 2])
def test_invalid_enable_setting_preserves_state(bad_on):
    cal = VirtualCalibrator()
    before = cal.get_state()
    with pytest.raises(TypeError):
        cal.output(bad_on)
    assert cal.get_state() == before


class TestDeterministicResetAndInstanceIsolation:
    """Reset ownership and isolation of state across instances."""

    def test_reset_disables_output_and_preserves_hook(self):
        calls = []
        hook = lambda v: calls.append(v)
        cal = VirtualCalibrator(output_hook=hook)

        # Energize
        cal.set_voltage(5.0)
        assert cal.get_voltage() == 5.0
        assert cal.state["output_on"] is True
        assert calls == [5.0]

        # Reset
        cal.reset()
        assert cal.state["output_on"] is False
        assert cal._output_enabled is False
        assert cal.state["voltage"] == 0.0
        assert cal.state["current"] == 0.0
        assert cal.state["mode"] == "voltage"

        # Hook was notified of zero output on reset
        assert calls[-1] == 0.0
        # Hook is preserved
        assert cal.output_hook is hook

    def test_reset_does_not_mutate_setup_owned_closure_state(self):
        """Driver reset does NOT reset setup-owned state (external material/timebase/RNG)."""
        external_state = {"flux_webers": 0.05}

        def flux_hook(voltage):
            external_state["flux_webers"] += voltage * 0.001

        cal = VirtualCalibrator(output_hook=flux_hook)
        cal.set_voltage(10.0)
        assert external_state["flux_webers"] == pytest.approx(0.06)

        # Reset driver
        cal.reset()
        # External setup-owned state is untouched by driver reset
        assert external_state["flux_webers"] == pytest.approx(0.06)

    def test_instance_sample_assignment_isolated_from_shared_and_other_instances(self, monkeypatch):
        """Mutating mag_sample on one instance does not mutate VirtualInstrument._shared_mag_sample."""
        class SharedSample:
            current_field = 0.0

        shared = SharedSample()
        monkeypatch.setattr(VirtualInstrument, "_shared_mag_sample", shared)

        cal1 = VirtualCalibrator()
        cal2 = VirtualCalibrator()

        assert cal1.mag_sample is shared
        assert cal2.mag_sample is shared

        # Mutate instance 1
        cal1.mag_sample = None
        hook_vals = []
        cal1.output_hook = lambda v: hook_vals.append(v)

        cal1.set_voltage(0.05)
        assert hook_vals == [0.05]
        # cal2 uses shared sample fallback
        cal2.set_voltage(0.1)
        assert cal2.mag_sample.current_field == pytest.approx(1000.0)

        # Global shared sample reflects cal2, completely isolated from cal1
        assert VirtualInstrument._shared_mag_sample is shared
        assert VirtualInstrument._shared_mag_sample.current_field == pytest.approx(1000.0)

        # Deleting instance override on cal1 restores access to shared sample
        del cal1.mag_sample
        cal1.output_hook = None
        assert cal1.mag_sample is shared
        cal1.set_voltage(0.02)
        assert cal1.mag_sample.current_field == pytest.approx(200.0)

    def test_clear_is_safe_noop(self):
        cal = VirtualCalibrator()
        assert cal.clear() is None

    def test_idn_returns_virtual_calibrator(self):
        cal = VirtualCalibrator()
        assert cal.idn() == "Virtual Calibrator"
