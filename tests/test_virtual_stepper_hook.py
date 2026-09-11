"""
Tests for VirtualStepper generic per-instance virtual hooks (Checkpoint 28d).

Validates:
- Generic per-instance hook injection (angle_hook, position_hook, and step_hook aliases);
- Explicit injection precedence over deprecated global sample fallback;
- Fallback property is not accessed when explicit hook is present;
- Material-specific logic kept strictly outside generic driver;
- Command validation (finite numeric, non-negative integer steps, valid direction, state preservation on failure);
- Declared physical units ({"angle": "deg", "position": "steps"});
- Unchanged error propagation without retries (RuntimeError, TypeError, ValueError, ZeroDivisionError);
- Exact-once invocation and signature binding (1-arg, 2-arg, positional-only, keywords, *args, **kwargs, zero-arg);
- Shutdown confirmation: failed commands must not falsely confirm shutdown (moving marked None / unconfirmed);
- Instance isolation protecting VirtualInstrument._shared_mag_sample;
- Reset ownership: driver-owned state restored, hook preserved, setup-owned state untouched.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.virtual_instrument import VirtualInstrument


@pytest.fixture(autouse=True)
def clean_shared_mag_sample():
    """Ensure shared magnetic sample remains at zero angle across tests."""
    yield
    if hasattr(VirtualInstrument, "_shared_mag_sample") and VirtualInstrument._shared_mag_sample is not None:
        VirtualInstrument._shared_mag_sample.current_angle = 0.0
        VirtualInstrument._shared_mag_sample.current_field = 0.0


# ============================================================================
# 1. Hook Injection and Aliases
# ============================================================================

class TestVirtualStepperHookInjection:
    """Validation of hook injection, aliases, and properties."""

    def test_constructor_accepts_angle_hook(self):
        hook = lambda a: None
        stepper = VirtualStepper(angle_hook=hook)
        assert stepper.angle_hook is hook
        assert stepper.position_hook is hook
        assert stepper.step_hook is hook

    def test_constructor_accepts_position_hook_alias(self):
        hook = lambda a: None
        stepper = VirtualStepper(position_hook=hook)
        assert stepper.angle_hook is hook
        assert stepper.position_hook is hook
        assert stepper.step_hook is hook

    def test_constructor_accepts_step_hook_alias(self):
        hook = lambda a: None
        stepper = VirtualStepper(step_hook=hook)
        assert stepper.angle_hook is hook
        assert stepper.position_hook is hook
        assert stepper.step_hook is hook

    def test_constructor_identical_hooks_accepted(self):
        hook = lambda a: None
        stepper = VirtualStepper(angle_hook=hook, position_hook=hook, step_hook=hook)
        assert stepper.angle_hook is hook

    def test_constructor_conflicting_hooks_rejected(self):
        hook1 = lambda a: None
        hook2 = lambda a: None
        with pytest.raises(ValueError, match="Cannot specify multiple conflicting hook callables"):
            VirtualStepper(angle_hook=hook1, position_hook=hook2)

    def test_constructor_rejects_non_callable_hook(self):
        with pytest.raises(TypeError, match="angle_hook must be callable or None"):
            VirtualStepper(angle_hook="not_a_callable")

    def test_method_and_property_injection(self):
        stepper = VirtualStepper()
        assert stepper.angle_hook is None
        assert stepper.position_hook is None
        assert stepper.step_hook is None

        hook1 = lambda a: None
        stepper.set_angle_hook(hook1)
        assert stepper.angle_hook is hook1

        hook2 = lambda a: None
        stepper.set_position_hook(hook2)
        assert stepper.angle_hook is hook2
        assert stepper.position_hook is hook2

        hook3 = lambda a: None
        stepper.set_step_hook(hook3)
        assert stepper.step_hook is hook3

        hook4 = lambda a: None
        stepper.angle_hook = hook4
        assert stepper.angle_hook is hook4

        hook5 = lambda a: None
        stepper.position_hook = hook5
        assert stepper.position_hook is hook5

        hook6 = lambda a: None
        stepper.step_hook = hook6
        assert stepper.step_hook is hook6

        stepper.set_angle_hook(None)
        assert stepper.angle_hook is None
        assert stepper.position_hook is None
        assert stepper.step_hook is None

    def test_injection_rejects_non_callable(self):
        stepper = VirtualStepper()
        with pytest.raises(TypeError, match="angle_hook must be callable or None"):
            stepper.set_angle_hook(12345)
        with pytest.raises(TypeError, match="angle_hook must be callable or None"):
            stepper.angle_hook = [1, 2]
        with pytest.raises(TypeError, match="angle_hook must be callable or None"):
            stepper.position_hook = "invalid"
        with pytest.raises(TypeError, match="angle_hook must be callable or None"):
            stepper.step_hook = {"angle": 0.0}


# ============================================================================
# 2. Precedence, Fallback, and Material Decoupling
# ============================================================================

class TestPrecedenceAndDecoupling:
    """Precedence of explicit injection over global fallback and material decoupling."""

    def test_explicit_injection_takes_precedence_over_mag_sample(self):
        class MockSample:
            current_angle = 0.0

        stepper = VirtualStepper(steps_per_revolution=200)
        stepper.mag_sample = MockSample()

        # Without hook: fallback updates sample current_angle
        # 50 steps CW = 50 * 360 / 200 = 90 deg
        stepper.step(50, 1)
        assert stepper.mag_sample.current_angle == pytest.approx(90.0)

        # Injected hook overrides fallback; sample is not updated by hook calls
        received_angles = []
        stepper.set_angle_hook(lambda a: received_angles.append(a))

        stepper.step(50, 1)
        assert received_angles == [180.0]
        # Sample current_angle was NOT updated from 90.0 to 180.0
        assert stepper.mag_sample.current_angle == pytest.approx(90.0)

        # Clear hook: fallback is restored
        stepper.set_angle_hook(None)
        stepper.step(50, 1)
        # Sample is updated by 90 deg to 180 deg
        assert stepper.mag_sample.current_angle == pytest.approx(180.0)

    def test_hook_precedence_does_not_access_fallback_property(self):
        """When an explicit hook is set, mag_sample must not even be accessed."""
        class HookOnlyStepper(VirtualStepper):
            @property
            def mag_sample(self):
                raise AssertionError("mag_sample fallback must not be accessed when hook is present")

        received = []
        stepper = HookOnlyStepper(angle_hook=lambda a: received.append(a))
        stepper.step(20, 1)
        assert received == [36.0]
        stepper.set_zero()
        assert received == [36.0, 0.0]
        stepper.set_position(50)
        assert received == [36.0, 0.0, 90.0]
        stepper.stop()
        stepper.reset()
        assert received == [36.0, 0.0, 90.0, 90.0, 0.0]

    def test_material_logic_remains_outside_generic_driver(self):
        """VirtualStepper has no material/magnetic formulas; hook evaluates external physics."""
        # Simulated anisotropic magnetoresistance (AMR) model: R(theta) = R0 + dR * cos^2(theta - easy_axis)
        amr_state = {"angle_deg": 0.0, "resistance_ohm": 110.0}

        def amr_stage_hook(angle):
            theta_rad = math.radians(angle)
            r0 = 100.0
            dr = 10.0
            amr_state["angle_deg"] = angle
            amr_state["resistance_ohm"] = r0 + dr * (math.cos(theta_rad) ** 2)

        stepper = VirtualStepper(angle_hook=amr_stage_hook, steps_per_revolution=200)
        # Move to 0 deg
        stepper.set_zero()
        assert amr_state["resistance_ohm"] == pytest.approx(110.0)

        # Move to 90 deg (cos(90) = 0 -> R = 100 Ohm)
        stepper.step(50, 1)
        assert stepper.get_angle() == pytest.approx(90.0)
        assert amr_state["resistance_ohm"] == pytest.approx(100.0)

        # Move to 45 deg (cos^2(45) = 0.5 -> R = 105 Ohm)
        stepper.set_position(25)
        assert stepper.get_angle() == pytest.approx(45.0)
        assert amr_state["resistance_ohm"] == pytest.approx(105.0)


# ============================================================================
# 3. Declared Units, State, and Input Validation
# ============================================================================

class TestDeclaredUnitsAndInputValidation:
    """Validation of units, state copies, and command input checking."""

    def test_declared_units(self):
        stepper = VirtualStepper()
        assert stepper.declared_units["angle"] == "deg"
        assert stepper.declared_units["position"] == "steps"
        assert len(stepper.declared_units) == 2
        with pytest.raises((TypeError, AttributeError)):
            stepper.declared_units["angle"] = "rad"  # type: ignore

    def test_initial_state_and_get_state_copy(self):
        stepper = VirtualStepper(steps_per_revolution=400)
        state = stepper.get_state()
        assert state["position"] == 0
        assert state["angle"] == 0.0
        assert state["moving"] is False
        assert state["steps_per_revolution"] == 400

        # State copy is detached
        state["position"] = 999
        assert stepper.read_position() == 0
        assert stepper.get_position() == 0

    def test_step_cw_and_ccw(self):
        stepper = VirtualStepper(steps_per_revolution=200, angle_hook=lambda a: None)
        # Step CW (direction = 1)
        pos = stepper.step(50, 1)
        assert pos == 50
        assert stepper.read_position() == 50
        assert stepper.get_position() == 50
        assert stepper.get_angle() == pytest.approx(90.0)

        # Step CCW (direction = 0)
        pos = stepper.step(25, 0)
        assert pos == 25
        assert stepper.read_position() == 25
        assert stepper.get_angle() == pytest.approx(45.0)

        # Step CCW (direction = -1)
        pos = stepper.step(25, -1)
        assert pos == 0
        assert stepper.read_position() == 0
        assert stepper.get_angle() == pytest.approx(0.0)

    def test_set_position_and_set_zero(self):
        stepper = VirtualStepper(steps_per_revolution=200, angle_hook=lambda a: None)
        pos = stepper.set_position(100)
        assert pos == 100
        assert stepper.read_position() == 100
        assert stepper.get_angle() == pytest.approx(180.0)

        stepper.set_zero()
        assert stepper.read_position() == 0
        assert stepper.get_angle() == pytest.approx(0.0)

    def test_steps_per_revolution_property_and_validation(self):
        stepper = VirtualStepper(steps_per_revolution=200)
        assert stepper.steps_per_revolution == 200

        stepper.current_pos = 100
        stepper.steps_per_revolution = 400
        assert stepper.steps_per_revolution == 400
        assert stepper.get_angle() == pytest.approx(90.0)
        assert stepper.get_state()["steps_per_revolution"] == 400

        # Validation
        for bad_spr in [0, -200, float("nan"), float("inf")]:
            with pytest.raises(ValueError):
                VirtualStepper(steps_per_revolution=bad_spr)
            with pytest.raises(ValueError):
                stepper.steps_per_revolution = bad_spr

        for bad_type in [True, False, "200", None, [200]]:
            with pytest.raises(TypeError):
                VirtualStepper(steps_per_revolution=bad_type)
            with pytest.raises(TypeError):
                stepper.steps_per_revolution = bad_type

    @pytest.mark.parametrize("invalid_steps", [
        -1, -100, float("nan"), float("inf"), float("-inf"), 10.5, 0.1,
    ])
    def test_invalid_num_steps_rejected_and_state_preserved(self, invalid_steps):
        stepper = VirtualStepper(angle_hook=lambda a: None)
        stepper.step(20, 1)
        before = stepper.get_state()

        with pytest.raises(ValueError):
            stepper.step(invalid_steps, 1)
        assert stepper.get_state() == before

    @pytest.mark.parametrize("bad_type_steps", [
        "ten", None, [10], (10,), True, False, {"steps": 10},
    ])
    def test_non_numeric_num_steps_rejected(self, bad_type_steps):
        stepper = VirtualStepper(angle_hook=lambda a: None)
        before = stepper.get_state()
        with pytest.raises(TypeError):
            stepper.step(bad_type_steps, 1)
        assert stepper.get_state() == before

    @pytest.mark.parametrize("invalid_dir", [2, -2, 99, 10, "cw", "ccw", None, True, False])
    def test_invalid_direction_rejected_and_state_preserved(self, invalid_dir):
        stepper = VirtualStepper(angle_hook=lambda a: None)
        stepper.step(10, 1)
        before = stepper.get_state()

        with pytest.raises((ValueError, TypeError)):
            stepper.step(10, invalid_dir)
        assert stepper.get_state() == before

    @pytest.mark.parametrize("invalid_pos", [
        float("nan"), float("inf"), float("-inf"), 10.5, "100", None, True, False,
    ])
    def test_invalid_set_position_rejected_and_state_preserved(self, invalid_pos):
        stepper = VirtualStepper(angle_hook=lambda a: None)
        stepper.step(10, 1)
        before = stepper.get_state()

        with pytest.raises((ValueError, TypeError)):
            stepper.set_position(invalid_pos)
        assert stepper.get_state() == before


# ============================================================================
# 4. Signature Binding, Error Propagation, and Exact-Once Invocation
# ============================================================================

class TestSignatureBindingAndErrorPropagation:
    """Exact-once invocation, signature binding, and error preservation."""

    def test_single_positional_argument_hook(self):
        calls = []
        def hook(angle):
            calls.append(angle)

        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)
        stepper.step(50, 1)
        assert calls == [90.0]

    def test_positional_only_argument_hook(self):
        calls = []
        def hook(ang, /):
            calls.append(ang)

        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)
        stepper.step(100, 1)
        assert calls == [180.0]

    def test_two_positional_arguments_hook(self):
        calls = []
        def hook(tot, delta):
            calls.append((tot, delta))

        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)
        stepper.step(50, 1)
        assert calls == [(90.0, 90.0)]
        stepper.step(25, 0)
        assert calls[-1] == (45.0, -45.0)

    def test_hook_with_keyword_arguments(self):
        received = []
        def hook(angle, *, delta_angle, position, moving):
            received.append((angle, delta_angle, position, moving))

        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)
        stepper.step(50, 1)
        assert received == [(90.0, 90.0, 50, False)]

        stepper.set_zero()
        assert received[-1] == (0.0, -90.0, 0, False)

    def test_hook_with_target_and_total_keywords(self):
        received = []
        def hook(*, total_angle, total_steps, target_angle):
            received.append((total_angle, total_steps, target_angle))

        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)
        stepper.set_position(80)
        assert received == [(144.0, 80, 144.0)]

    def test_hook_with_kwargs(self):
        received = []
        def hook(**kwargs):
            received.append(kwargs)

        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)
        stepper.step(50, 1)
        assert len(received) == 1
        assert received[0]["angle"] == pytest.approx(90.0)
        assert received[0]["total_angle"] == pytest.approx(90.0)
        assert received[0]["delta_angle"] == pytest.approx(90.0)
        assert received[0]["position"] == 50
        assert received[0]["total_steps"] == 50
        assert received[0]["moving"] is False

    def test_pure_args_hook_receives_command_angle(self):
        calls = []
        stepper = VirtualStepper(angle_hook=lambda *args: calls.append(args), steps_per_revolution=200)
        stepper.step(50, 1)
        stepper.stop()
        assert calls == [(90.0,), (90.0,)]

    def test_zero_argument_hook(self):
        calls = []
        stepper = VirtualStepper(angle_hook=lambda: calls.append(1))
        stepper.step(10, 1)
        assert len(calls) == 1

    def test_incompatible_hook_signature_raises_type_error(self):
        def bad_sig(a, b, c, d, e):
            pass

        stepper = VirtualStepper(angle_hook=bad_sig)
        with pytest.raises(TypeError, match="angle_hook has incompatible signature"):
            stepper.step(10, 1)

    @pytest.mark.parametrize("error_cls", [RuntimeError, TypeError, ValueError, ZeroDivisionError])
    def test_hook_exception_propagates_unchanged_without_retries(self, error_cls):
        calls = []
        error = error_cls("Simulated motor controller stall/timeout")

        def failing_hook(*args, **kwargs):
            calls.append((args, kwargs))
            raise error

        stepper = VirtualStepper(angle_hook=failing_hook)
        with pytest.raises(error_cls) as exc_info:
            stepper.step(20, 1)

        assert exc_info.value is error
        assert len(calls) == 1


# ============================================================================
# 5. Shutdown Confirmation, Motion Tracking, and Unconfirmed State
# ============================================================================

class TestShutdownConfirmationAndMotionState:
    """Safing, shutdown confirmation, and marking motion unconfirmed on hook failure."""

    def test_stop_and_halt_notify_hook_and_confirm_stopped(self):
        calls = []
        stepper = VirtualStepper(angle_hook=lambda **d: calls.append(d), steps_per_revolution=200)
        stepper.step(50, 1)
        assert calls[-1]["moving"] is False

        stepper.stop()
        assert calls[-1]["moving"] is False
        assert calls[-1]["delta_angle"] == 0.0
        assert calls[-1]["angle"] == 90.0
        assert stepper.get_state()["moving"] is False

        stepper.halt()
        assert calls[-1]["moving"] is False
        assert stepper.get_state()["moving"] is False

    @pytest.mark.parametrize("operation", ["step", "stop", "halt", "set_position", "set_zero", "reset"])
    def test_failed_hook_marks_moving_unconfirmed_until_successful_command(self, operation):
        calls = []
        error = RuntimeError("motor communication interrupted")

        def fail(*args, **kwargs):
            calls.append((args, kwargs))
            raise error

        stepper = VirtualStepper(angle_hook=lambda a: None, steps_per_revolution=200)
        stepper.step(50, 1)
        assert stepper.get_state()["moving"] is False

        stepper.angle_hook = fail

        actions = {
            "step": lambda: stepper.step(10, 1),
            "stop": stepper.stop,
            "halt": stepper.halt,
            "set_position": lambda: stepper.set_position(20),
            "set_zero": stepper.set_zero,
            "reset": stepper.reset,
        }

        with pytest.raises(RuntimeError) as result:
            actions[operation]()

        assert result.value is error
        assert len(calls) == 1
        # Failed command must NOT falsely confirm shutdown / stopped state!
        assert stepper.get_state()["moving"] is None
        assert stepper.state["moving"] is None

        # Subsequent successful command confirms state
        stepper.angle_hook = lambda a: None
        stepper.stop()
        assert stepper.get_state()["moving"] is False


# ============================================================================
# 6. Deterministic Reset and Instance Isolation
# ============================================================================

class TestDeterministicResetAndInstanceIsolation:
    """Reset ownership and isolation of state across instances."""

    def test_reset_restores_defaults_and_preserves_hook(self):
        calls = []
        hook = lambda a: calls.append(a)
        stepper = VirtualStepper(angle_hook=hook, steps_per_revolution=200)

        # Move stage
        stepper.step(50, 1)
        assert stepper.read_position() == 50
        assert stepper.get_angle() == 90.0
        assert stepper.state["moving"] is False
        assert calls == [90.0]

        # Reset
        stepper.reset()
        assert stepper.read_position() == 0
        assert stepper.get_angle() == 0.0
        assert stepper.state["position"] == 0
        assert stepper.state["angle"] == 0.0
        assert stepper.state["moving"] is False
        assert stepper.steps_per_revolution == 200

        # Hook was notified of zero angle on reset
        assert calls[-1] == 0.0
        # Hook is preserved
        assert stepper.angle_hook is hook

    def test_reset_does_not_mutate_setup_owned_closure_state(self):
        """Driver reset does NOT reset setup-owned state (external material/timebase/RNG)."""
        external_stage = {"accumulated_strain": 0.045}

        def strain_hook(angle):
            external_stage["accumulated_strain"] += angle * 0.0001

        stepper = VirtualStepper(angle_hook=strain_hook, steps_per_revolution=200)
        stepper.step(100, 1)
        assert external_stage["accumulated_strain"] == pytest.approx(0.045 + 180.0 * 0.0001)

        # Reset driver
        stepper.reset()
        # External setup-owned state is untouched by driver reset
        assert external_stage["accumulated_strain"] == pytest.approx(0.045 + 180.0 * 0.0001)

    def test_instance_sample_assignment_isolated_from_shared_and_other_instances(self, monkeypatch):
        """Mutating mag_sample on one instance does not mutate VirtualInstrument._shared_mag_sample."""
        class SharedSample:
            current_angle = 0.0
            current_field = 0.0

        shared = SharedSample()
        monkeypatch.setattr(VirtualInstrument, "_shared_mag_sample", shared)

        stepper1 = VirtualStepper(steps_per_revolution=200)
        stepper2 = VirtualStepper(steps_per_revolution=200)

        assert stepper1.mag_sample is shared
        assert stepper2.mag_sample is shared

        # Mutate instance 1
        stepper1.mag_sample = None
        hook_vals = []
        stepper1.angle_hook = lambda a: hook_vals.append(a)

        stepper1.step(50, 1)
        assert hook_vals == [90.0]
        # stepper2 uses shared sample fallback
        stepper2.step(25, 1)
        assert stepper2.mag_sample.current_angle == pytest.approx(45.0)

        # Global shared sample reflects stepper2, completely isolated from stepper1
        assert VirtualInstrument._shared_mag_sample is shared
        assert VirtualInstrument._shared_mag_sample.current_angle == pytest.approx(45.0)

        # Deleting instance override on stepper1 restores access to shared sample
        del stepper1.mag_sample
        stepper1.angle_hook = None
        assert stepper1.mag_sample is shared
        stepper1.step(25, 1)
        assert stepper1.mag_sample.current_angle == pytest.approx(90.0)

    def test_clear_is_safe_noop(self):
        stepper = VirtualStepper()
        assert stepper.clear() is None

    def test_idn_returns_virtual_stepper(self):
        stepper = VirtualStepper()
        assert stepper.idn() == "Virtual Stepper"
