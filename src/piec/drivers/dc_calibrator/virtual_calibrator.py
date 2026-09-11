from __future__ import annotations

import inspect
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualCalibrator(VirtualInstrument, DCCalibrator):
    """
    Virtual DC Calibrator with configurable state and per-instance output hook.

    Supports per-instance hook injection (`output_hook` / `field_hook`)
    with strict precedence over the deprecated shared `mag_sample` fallback.
    Sources voltage in Volts or current in Amps.
    """

    _DECLARED_UNITS: Mapping[str, str] = MappingProxyType({
        "voltage": "V",
        "current": "A",
    })

    def __init__(
        self,
        address: str = "VIRTUAL",
        output_hook: Optional[Callable[..., Any]] = None,
        field_hook: Optional[Callable[..., Any]] = None,
        voltage_calibration: float = 10000.0,
        **kwargs: Any,
    ) -> None:
        """
        Initialize Virtual DC Calibrator.

        Args:
            address: Explicit virtual instrument address.
            output_hook: Per-instance hook callable receiving output updates.
            field_hook: Alias for output_hook.
            voltage_calibration: Legacy scale factor (Oe/V) for deprecated mag_sample fallback.
            **kwargs: Additional options forwarded to VirtualInstrument, including
                legacy 'voltage_callibration' alias.
        """
        super().__init__(address=address, **kwargs)

        if output_hook is not None and field_hook is not None:
            if output_hook is not field_hook:
                raise ValueError("Cannot specify both output_hook and field_hook with different callables")

        hook = output_hook if output_hook is not None else field_hook

        cal_val = kwargs.get("voltage_callibration", kwargs.get("voltage_calibration", voltage_calibration))
        cal_f = float(cal_val)
        if not math.isfinite(cal_f) or cal_f <= 0:
            raise ValueError("voltage_calibration must be a positive finite number")
        self._voltage_calibration = cal_f

        self.state: dict[str, Any] = {
            "output_on": True,
            "mode": "voltage",
            "voltage": 0.0,
            "current": 0.0,
        }
        self._output_enabled: bool = True
        self._output_hook: Optional[Callable[..., Any]] = None
        self.set_output_hook(hook)

    @property
    def declared_units(self) -> Mapping[str, str]:
        """Declared physical units for virtual calibrator quantities."""
        return self._DECLARED_UNITS

    @property
    def output_hook(self) -> Optional[Callable[..., Any]]:
        """Return the injected per-instance output hook."""
        return self._output_hook

    @output_hook.setter
    def output_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_output_hook(hook)

    @property
    def field_hook(self) -> Optional[Callable[..., Any]]:
        """Return the injected per-instance output hook (alias)."""
        return self._output_hook

    @field_hook.setter
    def field_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_output_hook(hook)

    def set_output_hook(self, output_hook: Optional[Callable[..., Any]]) -> None:
        """
        Inject a per-instance callable hook for output commands.

        The hook takes precedence over the deprecated global mag_sample fallback.
        Passing None clears the hook and restores fallback behavior.

        Args:
            output_hook: Callable accepting output updates, or None.

        Raises:
            TypeError: If output_hook is not callable and not None.
        """
        if output_hook is not None and not callable(output_hook):
            raise TypeError(f"output_hook must be callable or None, got {type(output_hook).__name__}")
        self._output_hook = output_hook

    def set_field_hook(self, field_hook: Optional[Callable[..., Any]]) -> None:
        """Alias for set_output_hook."""
        self.set_output_hook(field_hook)

    @property
    def voltage_calibration(self) -> float:
        """Legacy calibration scale factor for shared mag_sample fallback."""
        return self._voltage_calibration

    @voltage_calibration.setter
    def voltage_calibration(self, val: float) -> None:
        val_f = float(val)
        if not math.isfinite(val_f) or val_f <= 0:
            raise ValueError("voltage_calibration must be a positive finite number")
        self._voltage_calibration = val_f

    @property
    def voltage_callibration(self) -> float:
        """Deprecated spelling alias for voltage_calibration."""
        return self._voltage_calibration

    @voltage_callibration.setter
    def voltage_callibration(self, val: float) -> None:
        self.voltage_calibration = val

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
        return "Virtual Calibrator"

    def set_voltage(self, voltage: float) -> None:
        """Set output voltage in Volts."""
        return self.set_output(voltage, mode="voltage")

    def set_current(self, current: float) -> None:
        """Set output current in Amps."""
        return self.set_output(current, mode="current")

    def set_output(self, value: float, mode: str = "voltage", **kwargs: Any) -> None:
        """
        Set calibrator output value and mode.

        Args:
            value: Desired output value in Volts or Amps.
            mode: 'voltage', 'current', or 'crowbar'.

        Raises:
            TypeError: If value is not numeric.
            ValueError: If value is non-finite or mode is unsupported.
        """
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"Input value must be numeric (int or float), got {type(value).__name__}")
        value_f = float(value)
        if not math.isfinite(value_f):
            raise ValueError(f"Output value must be finite, got {value!r}")

        norm_mode = str(mode).lower()
        if norm_mode in ("voltage", "volt"):
            norm_mode = "voltage"
        elif norm_mode in ("current", "curr"):
            norm_mode = "current"
        elif norm_mode == "crowbar":
            norm_mode = "crowbar"
        else:
            raise ValueError(f"unsupported mode {mode!r}; must be 'voltage', 'current', or 'crowbar'")

        if norm_mode == "crowbar":
            self.state["output_on"] = False
            self._output_enabled = False
            effective_val = 0.0
        else:
            self.state["mode"] = norm_mode
            self.state["output_on"] = True
            self._output_enabled = True
            if norm_mode == "voltage":
                self.state["voltage"] = value_f
            else:
                self.state["current"] = value_f
            effective_val = value_f

        if self._output_hook is not None:
            self._invoke_output_hook(self._output_hook, effective_val, norm_mode, self.state["output_on"])
            return

        # Deprecated fallback to shared magnetic sample
        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            if norm_mode == "voltage":
                self.mag_sample.current_field = effective_val * self._voltage_calibration
            elif norm_mode == "crowbar":
                self.mag_sample.current_field = 0.0

    def output(self, on: bool = True) -> None:
        """
        Enable or disable calibrator main output.

        Disabling output engages crowbar / zero output.
        """
        on_bool = bool(on)
        self.state["output_on"] = on_bool
        self._output_enabled = on_bool

        effective_val = (
            self.state["voltage"] if self.state["mode"] == "voltage" else self.state["current"]
        ) if on_bool else 0.0

        if self._output_hook is not None:
            self._invoke_output_hook(self._output_hook, effective_val, self.state["mode"], on_bool)
            return

        # Deprecated fallback to shared magnetic sample
        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            if not on_bool:
                self.mag_sample.current_field = 0.0
            elif self.state["mode"] == "voltage":
                self.mag_sample.current_field = effective_val * self._voltage_calibration

    def _invoke_output_hook(
        self,
        hook: Callable[..., Any],
        value: float,
        mode: str,
        output_on: bool,
    ) -> Any:
        """Bind hook parameters before invoking once; propagate hook exceptions unchanged."""
        try:
            sig = inspect.signature(hook)
        except (ValueError, TypeError):
            return hook(value)

        values = {
            "value": value,
            "mode": mode,
            "output_on": output_on,
            "on": output_on,
            "voltage": value if mode == "voltage" else self.state["voltage"],
            "current": value if mode == "current" else self.state["current"],
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
                elif i == 0:
                    args.append(value)
                elif p.default is not inspect.Parameter.empty:
                    args.append(p.default)
                else:
                    raise TypeError(f"output_hook has unsupported required positional parameter {p.name!r}")

        # 2. Positional or keyword parameters
        for i, p in enumerate(params):
            if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                if not positional and i == 0 and p.name not in values:
                    args.append(value)
                elif p.name in values:
                    kwargs[p.name] = values[p.name]
            elif p.kind == inspect.Parameter.KEYWORD_ONLY:
                if p.name in values:
                    kwargs[p.name] = values[p.name]

        # 3. **kwargs
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            kwargs.update({k: v for k, v in values.items() if k not in sig.parameters})

        try:
            sig.bind(*args, **kwargs)
        except TypeError as error:
            if len(params) == 0:
                return hook()
            raise TypeError("output_hook has incompatible signature") from error

        return hook(*args, **kwargs)

    def reset(self) -> None:
        """
        Reset virtual calibrator configuration to factory defaults with output disabled.

        Restores driver-owned state (output_on=False, voltage=0.0, current=0.0,
        mode='voltage') while preserving the injected per-instance hook.

        Driver reset does NOT reset setup-owned state: closures, external material
        models, timebase clocks, and RNG seeds are owned by the test fixture or
        VirtualBench and must be reset there.
        """
        self.state = {
            "output_on": False,
            "mode": "voltage",
            "voltage": 0.0,
            "current": 0.0,
        }
        self._output_enabled = False

        if self._output_hook is not None:
            self._invoke_output_hook(self._output_hook, 0.0, "voltage", False)
        elif hasattr(self, "mag_sample") and self.mag_sample is not None:
            self.mag_sample.current_field = 0.0

    def clear(self) -> None:
        """Clear calibrator status registers (safe no-op)."""
        return None

    def get_state(self) -> dict[str, Any]:
        """Return a copy of the current calibrator state."""
        return self.state.copy()

    def get_voltage(self) -> float:
        """Return the current voltage setting in Volts."""
        return float(self.state["voltage"])

    def get_current(self) -> float:
        """Return the current setting in Amps."""
        return float(self.state["current"])
