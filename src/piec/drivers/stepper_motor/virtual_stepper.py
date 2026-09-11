from __future__ import annotations

import inspect
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from piec.drivers.stepper_motor.stepper_motor import Stepper
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualStepper(VirtualInstrument, Stepper):
    """
    Virtual Stepper Motor with configurable state and per-instance angle hook.

    Supports per-instance hook injection (`angle_hook` / `position_hook` / `step_hook`)
    with strict precedence over the deprecated shared `mag_sample` fallback.
    Tracks position in steps and orientation angle in degrees.
    """

    _DECLARED_UNITS: Mapping[str, str] = MappingProxyType({
        "angle": "deg",
        "position": "steps",
    })

    def __init__(
        self,
        address: str = "VIRTUAL",
        angle_hook: Optional[Callable[..., Any]] = None,
        position_hook: Optional[Callable[..., Any]] = None,
        step_hook: Optional[Callable[..., Any]] = None,
        steps_per_revolution: int = 200,
        **kwargs: Any,
    ) -> None:
        """
        Initialize Virtual Stepper Motor.

        Args:
            address: Explicit virtual instrument address.
            angle_hook: Per-instance hook callable receiving angle/position updates.
            position_hook: Alias for angle_hook.
            step_hook: Alias for angle_hook.
            steps_per_revolution: Number of full steps per 360-degree revolution.
            **kwargs: Additional options forwarded to VirtualInstrument.
        """
        super().__init__(address=address, **kwargs)

        hooks = [h for h in (angle_hook, position_hook, step_hook) if h is not None]
        if len(hooks) > 1 and any(h is not hooks[0] for h in hooks[1:]):
            raise ValueError("Cannot specify multiple conflicting hook callables")

        hook = hooks[0] if hooks else None

        if isinstance(steps_per_revolution, bool) or not isinstance(steps_per_revolution, Real):
            raise TypeError("steps_per_revolution must be an integer")
        spr_f = float(steps_per_revolution)
        if not math.isfinite(spr_f) or not spr_f.is_integer() or spr_f <= 0:
            raise ValueError("steps_per_revolution must be a positive integer")
        spr = int(spr_f)

        self._initial_steps_per_revolution = spr
        self._steps_per_revolution = spr
        self.current_pos: int = 0
        self.state: dict[str, Any] = {
            "position": 0,
            "angle": 0.0,
            "moving": False,
            "steps_per_revolution": spr,
        }

        self._angle_hook: Optional[Callable[..., Any]] = None
        self.set_angle_hook(hook)

    @property
    def declared_units(self) -> Mapping[str, str]:
        """Declared physical units for virtual stepper quantities."""
        return self._DECLARED_UNITS

    @property
    def steps_per_revolution(self) -> int:
        """Number of steps per 360-degree motor revolution."""
        return self._steps_per_revolution

    @steps_per_revolution.setter
    def steps_per_revolution(self, val: int) -> None:
        if isinstance(val, bool) or not isinstance(val, Real):
            raise TypeError("steps_per_revolution must be an integer")
        spr_f = float(val)
        if not math.isfinite(spr_f) or not spr_f.is_integer() or spr_f <= 0:
            raise ValueError("steps_per_revolution must be a positive integer")
        spr = int(spr_f)
        old_angle = self.get_angle()
        self._steps_per_revolution = spr
        self.state["steps_per_revolution"] = spr
        self.state["angle"] = self.get_angle()
        if self._angle_hook is not None:
            self._notify_hook(self.get_angle() - old_angle, self.get_angle(), self.current_pos,
                              moving=self.state["moving"])
        elif self.mag_sample is not None:
            self.mag_sample.current_angle += self.get_angle() - old_angle

    @property
    def angle_hook(self) -> Optional[Callable[..., Any]]:
        """Return the injected per-instance angle hook."""
        return self._angle_hook

    @angle_hook.setter
    def angle_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_angle_hook(hook)

    @property
    def position_hook(self) -> Optional[Callable[..., Any]]:
        """Return the injected per-instance hook (alias)."""
        return self._angle_hook

    @position_hook.setter
    def position_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_angle_hook(hook)

    @property
    def step_hook(self) -> Optional[Callable[..., Any]]:
        """Return the injected per-instance hook (alias)."""
        return self._angle_hook

    @step_hook.setter
    def step_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_angle_hook(hook)

    def set_angle_hook(self, angle_hook: Optional[Callable[..., Any]]) -> None:
        """
        Inject a per-instance callable hook for angle / position updates.

        The hook takes precedence over the deprecated global mag_sample fallback.
        Passing None clears the hook and restores fallback behavior.

        Args:
            angle_hook: Callable accepting angle updates, or None.

        Raises:
            TypeError: If angle_hook is not callable and not None.
        """
        if angle_hook is not None and not callable(angle_hook):
            raise TypeError(f"angle_hook must be callable or None, got {type(angle_hook).__name__}")
        self._angle_hook = angle_hook

    def set_position_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        """Alias for set_angle_hook."""
        self.set_angle_hook(hook)

    def set_step_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        """Alias for set_angle_hook."""
        self.set_angle_hook(hook)

    @property
    def mag_sample(self) -> Any:
        """Return the instance-specific or shared magnetic sample fallback."""
        if hasattr(self, "_instance_mag_sample"):
            return self._instance_mag_sample
        return super().mag_sample

    @mag_sample.setter
    def mag_sample(self, sample: Any) -> None:
        self._instance_mag_sample = sample

    @mag_sample.deleter
    def mag_sample(self) -> None:
        if hasattr(self, "_instance_mag_sample"):
            del self._instance_mag_sample

    def idn(self) -> str:
        return "Virtual Stepper"

    def read_position(self) -> int:
        """Return the current motor position in steps."""
        return int(self.current_pos)

    def get_position(self) -> int:
        """Return the current motor position in steps (alias for read_position)."""
        return self.read_position()

    def get_angle(self) -> float:
        """Return the current calculated stage angle in degrees."""
        return float(self.current_pos * 360.0 / self._steps_per_revolution)

    def get_state(self) -> dict[str, Any]:
        """Return a copy of the current virtual stepper state."""
        return self.state.copy()

    def step(self, num_steps: int, direction: int = 1) -> int:
        """
        Step the motor by a commanded number of steps in a direction.

        Args:
            num_steps: Integer step count (non-negative).
            direction: Direction flag (1 for CW, 0 or -1 for CCW).

        Returns:
            int: Updated position in steps.

        Raises:
            TypeError: If num_steps or direction are of invalid type.
            ValueError: If num_steps is negative or non-finite, or direction is invalid.
        """
        if isinstance(num_steps, bool) or not isinstance(num_steps, Real):
            raise TypeError(f"num_steps must be numeric, got {type(num_steps).__name__}")
        num_f = float(num_steps)
        if not math.isfinite(num_f) or num_f < 0:
            raise ValueError(f"num_steps must be finite and non-negative, got {num_steps!r}")
        if not num_f.is_integer():
            raise ValueError(f"num_steps must be an integer number of steps, got {num_steps!r}")
        steps_int = int(num_f)

        if isinstance(direction, bool) or not isinstance(direction, Real):
            raise TypeError(f"direction must be an integer, got {type(direction).__name__}")
        if not math.isfinite(direction) or direction not in (1, 0, -1):
            raise ValueError(f"direction must be 1 (CW) or 0 / -1 (CCW), got {direction!r}")
        dir_int = int(direction)

        signed_delta = steps_int if dir_int == 1 else -steps_int
        new_pos = self.current_pos + signed_delta
        delta_angle = (signed_delta * 360.0 / self._steps_per_revolution)
        new_angle = (new_pos * 360.0 / self._steps_per_revolution)

        # Update driver-owned position and angle
        self.current_pos = new_pos
        self.state["position"] = new_pos
        self.state["angle"] = new_angle
        self.state["moving"] = False

        if self._angle_hook is not None:
            self._notify_hook(delta_angle, new_angle, new_pos, moving=False)
            return self.current_pos

        # Deprecated fallback to shared magnetic sample
        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            self.mag_sample.current_angle += delta_angle

        return self.current_pos

    def set_zero(self) -> None:
        """Reset internal position and angle tracking to zero."""
        old_angle = self.get_angle()
        self.current_pos = 0
        self.state["position"] = 0
        self.state["angle"] = 0.0
        self.state["moving"] = False

        if self._angle_hook is not None:
            self._notify_hook(-old_angle, 0.0, 0, moving=False)
            return

        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            self.mag_sample.current_angle = 0.0

    def set_position(self, position: int) -> int:
        """Set position tracking to a specified step count."""
        if isinstance(position, bool) or not isinstance(position, Real):
            raise TypeError("position must be an integer")
        pos_f = float(position)
        if not math.isfinite(pos_f) or not pos_f.is_integer():
            raise ValueError("position must be a finite integer")
        pos_int = int(pos_f)

        old_angle = self.get_angle()
        self.current_pos = pos_int
        new_angle = self.get_angle()
        self.state["position"] = pos_int
        self.state["angle"] = new_angle
        self.state["moving"] = False

        if self._angle_hook is not None:
            self._notify_hook(new_angle - old_angle, new_angle, pos_int, moving=False)
            return self.current_pos

        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            self.mag_sample.current_angle = new_angle

        return self.current_pos

    def halt(self) -> None:
        """Halt motor motion and confirm stopped state."""
        self.stop()

    def stop(self) -> None:
        """Stop motor motion and confirm stopped state."""
        self.state["moving"] = False
        if self._angle_hook is not None:
            self._notify_hook(0.0, self.get_angle(), self.current_pos, moving=False)

    def _notify_hook(
        self,
        delta_angle: float,
        total_angle: float,
        total_steps: int,
        moving: bool,
    ) -> Any:
        """Notify injected hook and mark motion state unconfirmed on failure."""
        try:
            return self._invoke_hook(self._angle_hook, delta_angle, total_angle, total_steps, moving)
        except BaseException:
            # If notification fails, the motion/safing may have only partially occurred.
            # Neither moving=False nor moving=True is confirmed.
            self.state["moving"] = None
            raise

    def _invoke_hook(
        self,
        hook: Callable[..., Any],
        delta_angle: float,
        total_angle: float,
        total_steps: int,
        moving: bool,
    ) -> Any:
        """Bind hook parameters before invoking once; propagate hook exceptions unchanged."""
        try:
            sig = inspect.signature(hook)
        except (ValueError, TypeError):
            return hook(total_angle)

        values = {
            "value": total_angle,
            "angle": total_angle,
            "total_angle": total_angle,
            "target_angle": total_angle,
            "total": total_angle,
            "delta_angle": delta_angle,
            "delta": delta_angle,
            "position": total_steps,
            "total_steps": total_steps,
            "target_position": total_steps,
            "steps": total_steps,
            "moving": moving,
        }

        params = list(sig.parameters.values())
        args: list[Any] = []
        kwargs: dict[str, Any] = {}

        # 1. Positional-only parameters
        positional = [p for p in params if p.kind == inspect.Parameter.POSITIONAL_ONLY]
        if positional:
            for i, p in enumerate(positional):
                if p.name in values:
                    args.append(values[p.name])
                elif p.default is not inspect.Parameter.empty:
                    args.append(p.default)
                elif i == 0:
                    args.append(total_angle)
                elif i == 1:
                    args.append(delta_angle)
                else:
                    raise TypeError(f"angle_hook has unsupported required positional parameter {p.name!r}")

        # Use keyword binding for ordinary parameters, including unnamed aliases,
        # so a later positional value cannot accidentally bind an earlier name twice.
        for i, p in enumerate(params):
            if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                if p.name in values:
                    kwargs[p.name] = values[p.name]
                elif p.default is not inspect.Parameter.empty:
                    continue
                elif not positional and i == 0:
                    kwargs[p.name] = total_angle
                elif not positional and i == 1:
                    kwargs[p.name] = delta_angle
            elif p.kind == inspect.Parameter.KEYWORD_ONLY and p.name in values:
                kwargs[p.name] = values[p.name]

        # 3. Variadic *args and **kwargs
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params) and not args and not kwargs:
            args.append(total_angle)
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            kwargs.update({k: v for k, v in values.items() if k not in sig.parameters})

        try:
            sig.bind(*args, **kwargs)
        except TypeError as error:
            if len(params) == 0:
                return hook()
            raise TypeError("angle_hook has incompatible signature") from error

        return hook(*args, **kwargs)

    def reset(self) -> None:
        """
        Reset virtual stepper motor configuration to factory defaults.

        Restores position to 0 steps, angle to 0.0 deg, moving to False,
        and steps_per_revolution to initial value while preserving the injected hook.

        Driver reset does NOT reset setup-owned state: closures, external material
        models, timebase clocks, and RNG seeds are owned by the test fixture or
        VirtualBench and must be reset there.
        """
        old_angle = self.get_angle()
        self._steps_per_revolution = self._initial_steps_per_revolution
        self.current_pos = 0
        self.state = {
            "position": 0,
            "angle": 0.0,
            "moving": False,
            "steps_per_revolution": self._initial_steps_per_revolution,
        }

        if self._angle_hook is not None:
            self._notify_hook(-old_angle, 0.0, 0, moving=False)
        elif hasattr(self, "mag_sample") and self.mag_sample is not None:
            self.mag_sample.current_angle = 0.0

    def clear(self) -> None:
        """Clear stepper status registers (safe no-op)."""
        return None
