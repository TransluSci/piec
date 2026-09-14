"""
Consolidated Stepper Motor Category Tests.

Covers:
- Base class, parameter restrictions, and driver inheritance
- Automatic discovery of all Stepper Motor drivers
- VirtualStepper state management, angle/step tracking, hook injection, and unit declarations
- Review/regression cases from checkpoint 28d (argument binding, scale tracking, failure preservation)
- Geos_Stepper serial protocol formatting, position reading, and zeroing
"""

import math
from unittest.mock import Mock, patch
import pytest
from piec.drivers.stepper_motor.stepper_motor import Stepper
from piec.drivers.stepper_motor.arduino_stepper import Geos_Stepper
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from tests.support.driver_contracts import DriverCase, physical, virtual, case_for, assert_driver_contract
from tests.support.discovery import discover_driver_classes, discover_instrument_categories
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver

# Independent device responses and expectations; discovery supplies the test inventory.
CASES = [
        DriverCase(Geos_Stepper, physical(Geos_Stepper, {'10,1': '10 Complete'}), lambda inst: inst.step(10, 1), 10),
        DriverCase(VirtualStepper, virtual(VirtualStepper, angle_hook=lambda angle: None), lambda inst: inst.step(10, 1), 10),
    ]



ALL_STEPPER_DRIVERS = discover_driver_classes()["stepper_motor"]


# ============================================================================
# 1. Base Class & Driver Inventory Conformance
# ============================================================================

class TestStepperDiscovery:
    """Verify that all advertised and discovered stepper drivers conform to standards."""

    def test_discovery_and_registration(self):
        assert_all_drivers_registered('stepper_motor', [case.cls for case in CASES])

    @pytest.mark.parametrize("driver_cls", ALL_STEPPER_DRIVERS)
    def test_inherits_from_stepper(self, driver_cls):
        assert issubclass(driver_cls, Stepper)


# ============================================================================
# 2. VirtualStepper Contract Tests
# ============================================================================

class TestVirtualStepperContract:
    """Verify VirtualStepper stepping, angle calculation, and units."""

    @pytest.fixture
    def v_stepper(self):
        return VirtualStepper()

    def test_initial_state(self, v_stepper):
        assert v_stepper.declared_units == {"angle": "deg", "position": "steps"}
        assert v_stepper.get_position() == 0
        assert v_stepper.get_angle() == 0.0

    def test_stepping_and_angle(self, v_stepper):
        # 200 steps/rev -> 1.8 deg per step
        v_stepper.step(10, 1)
        assert v_stepper.get_position() == 10
        assert v_stepper.get_angle() == pytest.approx(18.0)

        v_stepper.step(5, 0)
        assert v_stepper.get_position() == 5
        assert v_stepper.get_angle() == pytest.approx(9.0)

    def test_set_zero(self, v_stepper):
        v_stepper.step(20, 1)
        assert v_stepper.get_position() == 20
        v_stepper.set_zero()
        assert v_stepper.get_position() == 0
        assert v_stepper.get_angle() == 0.0

    def test_hook_aliases(self, v_stepper):
        hook = lambda a: None
        v_stepper.angle_hook = hook
        assert v_stepper.angle_hook is hook
        assert v_stepper.position_hook is hook
        assert v_stepper.step_hook is hook


# ============================================================================
# 3. Checkpoint 28d Review & Regression Cases
# ============================================================================

class TestVirtualStepperReviewRegressions:
    """Preserved regression cases from checkpoint 28d review."""

    @pytest.mark.parametrize("direction", [0.5, 1.5, -0.5, -1.5, float("inf"), float("nan")])
    def test_invalid_direction_does_not_move_or_notify(self, direction):
        calls = []
        stepper = VirtualStepper(angle_hook=lambda angle: calls.append(angle))
        before = stepper.get_state()
        with pytest.raises(ValueError):
            stepper.step(10, direction)
        assert stepper.get_state() == before
        assert calls == []

    def test_mixed_named_and_unnamed_arguments_bind_once(self):
        calls = []
        def hook(angle, change):
            calls.append((angle, change))
        stepper = VirtualStepper(angle_hook=hook)
        stepper.step(10)
        stepper.step(5)
        assert calls == [(18, 18), (27, 9)]

    @pytest.mark.parametrize("positional_only", [False, True])
    def test_unrelated_optional_hook_argument_keeps_default(self, positional_only):
        calls = []
        def ordinary(angle, gain=7):
            calls.append((angle, gain))
        def positional(angle, gain=7, /):
            calls.append((angle, gain))
        stepper = VirtualStepper(angle_hook=positional if positional_only else ordinary)
        stepper.step(10)
        assert calls == [(18, 7)]

    def test_delta_only_model_tracks_reset_and_scale_changes(self):
        angle = [0.0]
        def hook(*, delta_angle):
            angle[0] += delta_angle
        stepper = VirtualStepper(angle_hook=hook)
        stepper.step(10)
        assert angle[0] == stepper.get_angle() == 18
        stepper.steps_per_revolution = 400
        assert angle[0] == stepper.get_angle() == 9
        stepper.reset()
        assert angle[0] == stepper.get_angle() == 0

    def test_scale_notification_failure_is_unconfirmed_and_error_is_preserved(self):
        stepper = VirtualStepper(angle_hook=lambda angle: None)
        error = RuntimeError("notification failed")
        calls = []
        def hook(angle):
            calls.append(angle)
            raise error
        stepper.angle_hook = hook
        with pytest.raises(RuntimeError) as result:
            stepper.steps_per_revolution = 400
        assert result.value is error
        assert calls == [0]
        assert stepper.get_state()["moving"] is None


# ============================================================================
# 4. Geos_Stepper Serial Protocol Tests
# ============================================================================

class TestGeosStepperProtocol:
    """Verify Geos_Stepper Arduino serial command formatting and response parsing."""

    @pytest.fixture
    def stepper(self):
        inst = create_test_driver(
            Geos_Stepper,
            responses={
                "0,0": "0 Complete",
                "10,0": "10 Complete",
                "0,9": "0 Complete",
            },
        )
        return inst

    def test_step_command(self, stepper):
        pos = stepper.step(10, 0)
        assert pos == 10
        assert "10,0" in [q[0] for q in stepper.instrument.queries]

    @patch("time.sleep", return_value=None)
    def test_set_zero_and_read_position(self, mock_sleep, stepper):
        stepper.set_zero()
        assert "0,9" in [q[0] for q in stepper.instrument.queries]

        pos = stepper.read_position()
        assert pos == 0
        assert "0,0" in [q[0] for q in stepper.instrument.queries]

    def test_idn(self, stepper):
        ident = stepper.idn()
        assert "Custom Arduino_Stepper Object" in ident


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["stepper_motor"], ids=lambda cls: cls.__name__)
def test_driver_contract(driver_cls):
    assert_driver_contract(driver_cls, discover_instrument_categories()["stepper_motor"])


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["stepper_motor"], ids=lambda cls: cls.__name__)
def test_driver_behavior(driver_cls, monkeypatch):
    case_for(driver_cls, CASES).check(monkeypatch, discover_instrument_categories()["stepper_motor"])
