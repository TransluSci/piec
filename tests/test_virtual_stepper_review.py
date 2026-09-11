"""Regression cases for the checkpoint 28d review."""
import pytest
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper


@pytest.mark.parametrize("direction", [0.5, 1.5, -0.5, -1.5, float("inf"), float("nan")])
def test_invalid_direction_does_not_move_or_notify(direction):
    calls = []
    stepper = VirtualStepper(angle_hook=lambda angle: calls.append(angle))
    before = stepper.get_state()
    with pytest.raises(ValueError):
        stepper.step(10, direction)
    assert stepper.get_state() == before
    assert calls == []


def test_mixed_named_and_unnamed_arguments_bind_once():
    calls = []
    def hook(angle, change):
        calls.append((angle, change))
    stepper = VirtualStepper(angle_hook=hook)
    stepper.step(10)
    stepper.step(5)
    assert calls == [(18, 18), (27, 9)]


@pytest.mark.parametrize("positional_only", [False, True])
def test_unrelated_optional_hook_argument_keeps_default(positional_only):
    calls = []
    def ordinary(angle, gain=7):
        calls.append((angle, gain))
    def positional(angle, gain=7, /):
        calls.append((angle, gain))
    stepper = VirtualStepper(angle_hook=positional if positional_only else ordinary)
    stepper.step(10)
    assert calls == [(18, 7)]


def test_delta_only_model_tracks_reset_and_scale_changes():
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


def test_scale_notification_failure_is_unconfirmed_and_error_is_preserved():
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
