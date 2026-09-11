from __future__ import annotations

import inspect
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

import numpy as np

from piec.drivers.lockin.lockin import Lockin
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualLockin(VirtualInstrument, Lockin):
    """
    Virtual version of a Lock-in amplifier with per-instance hook injection.

    Supports per-instance generic hook injection (`xy_reader` / `transport_hook`)
    with strict precedence over the deprecated shared `mag_sample` fallback.
    Returns plain 2-tuples of (X, Y) voltages in Volts.
    """

    _DECLARED_UNITS: Mapping[str, str] = MappingProxyType({
        "x": "V",
        "y": "V",
        "excitation_current": "A",
    })

    def __init__(
        self,
        address: str = "VIRTUAL",
        *,
        excitation_current: float = 1e-6,
        xy_reader: Optional[Callable[..., Tuple[float, float]]] = None,
        transport_hook: Optional[Callable[..., Tuple[float, float]]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize virtual lock-in amplifier.

        Args:
            address: Explicit virtual instrument address.
            excitation_current: Declared sample excitation current in Amperes
                (default: 1 uA; simulation-only parameter).
            xy_reader: Per-instance hook callable returning (X, Y) voltages in Volts.
            transport_hook: Alias for xy_reader.
            **kwargs: Additional options forwarded to VirtualInstrument.
        """
        if xy_reader is not None and transport_hook is not None:
            if xy_reader is not transport_hook:
                raise ValueError("Cannot specify both xy_reader and transport_hook with different callables")

        hook = xy_reader if xy_reader is not None else transport_hook

        self._initial_excitation_current = float(excitation_current)
        self.excitation_current = float(excitation_current)
        self._xy_reader: Optional[Callable[..., Tuple[float, float]]] = None
        self.set_xy_reader(hook)

        self.state: dict[str, Any] = {
            "reference_voltage": 0.0,
            "reference_frequency": 1000.0,
            "reference_source": "internal",
            "sensitivity": 1.0,
            "time_constant": 0.1,
            "phase": 0.0,
        }

        super().__init__(address=address, **kwargs)

    @property
    def declared_units(self) -> Mapping[str, str]:
        """Declared physical units for virtual lock-in quantities."""
        return self._DECLARED_UNITS

    @property
    def excitation_current(self) -> float:
        """Declared simulated current in A; zero disables drive and sign sets polarity."""
        return self._excitation_current

    @excitation_current.setter
    def excitation_current(self, value: float) -> None:
        current = float(value)
        if not math.isfinite(current):
            raise ValueError("excitation_current must be finite")
        self._excitation_current = current

    @property
    def xy_reader(self) -> Optional[Callable[..., Tuple[float, float]]]:
        """Return the injected per-instance X/Y reader hook."""
        return self._xy_reader

    @xy_reader.setter
    def xy_reader(self, hook: Optional[Callable[..., Tuple[float, float]]]) -> None:
        self.set_xy_reader(hook)

    @property
    def transport_hook(self) -> Optional[Callable[..., Tuple[float, float]]]:
        """Return the injected per-instance transport hook (alias for xy_reader)."""
        return self._xy_reader

    @transport_hook.setter
    def transport_hook(self, hook: Optional[Callable[..., Tuple[float, float]]]) -> None:
        self.set_xy_reader(hook)

    def set_xy_reader(self, xy_reader: Optional[Callable[..., Tuple[float, float]]]) -> None:
        """
        Inject a per-instance callable hook for dual-channel (X, Y) voltage reading.

        The hook takes precedence over the deprecated global mag_sample fallback.
        The hook may be:
        - a 0-argument callable returning (X, Y) in Volts;
        - a callable accepting `excitation_current` keyword argument returning (X, Y) in Volts;
        - a callable accepting a single positional argument for excitation_current;
        - or None to remove the explicit hook and restore fallback behavior.

        Args:
            xy_reader: Callable hook returning a 2-tuple of floats, or None.

        Raises:
            TypeError: If xy_reader is not callable and not None.
        """
        if xy_reader is not None and not callable(xy_reader):
            raise TypeError(f"xy_reader must be callable or None, got {type(xy_reader).__name__}")
        self._xy_reader = xy_reader

    def set_transport_hook(self, transport_hook: Optional[Callable[..., Tuple[float, float]]]) -> None:
        """Alias for set_xy_reader."""
        self.set_xy_reader(transport_hook)

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
        return "Virtual Lock-in"

    def initialize(self) -> None:
        """Mock initialize from Scpi."""
        pass

    def reset(self) -> None:
        """
        Reset virtual lock-in state while preserving explicit hook injection.

        Restores default configuration and excitation current while keeping
        the injected xy_reader intact.
        """
        self.excitation_current = self._initial_excitation_current
        self.state = {
            "reference_voltage": 0.0,
            "reference_frequency": 1000.0,
            "reference_source": "internal",
            "sensitivity": 1.0,
            "time_constant": 0.1,
            "phase": 0.0,
        }

    def clear(self) -> None:
        """Clear virtual lock-in status registers."""
        pass

    def configure_reference(self, **kwargs: Any) -> None:
        """Configure reference channel settings (voltage, frequency, source, phase)."""
        updated = self.state.copy()
        if "voltage" in kwargs and kwargs["voltage"] is not None:
            voltage = float(kwargs["voltage"])
            if not math.isfinite(voltage) or voltage < 0:
                raise ValueError("amplitude must be non-negative and finite")
            updated["reference_voltage"] = voltage
        if "frequency" in kwargs and kwargs["frequency"] is not None:
            frequency = float(kwargs["frequency"])
            if not math.isfinite(frequency) or frequency <= 0:
                raise ValueError("frequency must be positive and finite")
            updated["reference_frequency"] = frequency
        if "source" in kwargs and kwargs["source"] is not None:
            source = str(kwargs["source"]).lower()
            if source not in ("internal", "external"):
                raise ValueError("source must be internal or external")
            updated["reference_source"] = source
        if "phase" in kwargs and kwargs["phase"] is not None:
            phase = float(kwargs["phase"])
            if not math.isfinite(phase):
                raise ValueError("phase must be finite")
            updated["phase"] = phase
        for name in ("trig", "harmonic"):
            if kwargs.get(name) is not None:
                updated[name] = kwargs[name]
        self.state = updated

    def set_amplitude(self, amplitude: float) -> None:
        """Set sine out reference amplitude in Volts."""
        amp = float(amplitude)
        if not math.isfinite(amp) or amp < 0:
            raise ValueError("amplitude must be non-negative and finite")
        self.state["reference_voltage"] = amp

    def get_amplitude(self) -> float:
        """Get sine out reference amplitude in Volts."""
        return float(self.state.get("reference_voltage", 0.0))

    def set_frequency(self, frequency: float) -> None:
        """Set reference oscillator frequency in Hz."""
        freq = float(frequency)
        if not math.isfinite(freq) or freq <= 0:
            raise ValueError("frequency must be positive and finite")
        self.state["reference_frequency"] = freq

    def get_frequency(self) -> float:
        """Get reference oscillator frequency in Hz."""
        return float(self.state.get("reference_frequency", 1000.0))

    def configure_input(self, **kwargs: Any) -> None:
        """Configure input channel settings (coupling, configuration, etc.)."""
        self.state.update(kwargs)

    def configure_gain_filters(self, **kwargs: Any) -> None:
        """Configure gain and filter settings (sensitivity, time constant, etc.)."""
        self.state.update(kwargs)

    def get_state(self) -> dict[str, Any]:
        """Return a copy of the current virtual lock-in state."""
        return self.state.copy()

    def quick_read(self) -> Tuple[float, float]:
        """
        Read in-phase (X) and quadrature (Y) voltages in Volts.

        Precedence:
        1. Explicit per-instance hook (xy_reader / transport_hook) if injected;
        2. Deprecated shared magnetic sample fallback (self.mag_sample);
        3. Default idle reading (0.0001 V, 0.0002 V).

        Returns:
            Tuple[float, float]: Plain 2-tuple of (X, Y) voltages in Volts.
        """
        if self._xy_reader is not None:
            raw_response = self._invoke_hook(self._xy_reader)
            return self._validate_response(raw_response)

        # Deprecated fallback to shared magnetic sample
        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            raw_response = self.mag_sample.get_voltage_response(
                excitation_current=self.excitation_current
            )
            return self._validate_response(raw_response)

        return (0.0001, 0.0002)

    def _invoke_hook(self, hook: Callable[..., Any]) -> Any:
        """Bind arguments before invoking once; never catch a hook's own errors."""
        try:
            sig = inspect.signature(hook)
        except (ValueError, TypeError):
            # Opaque callables follow the zero-argument reader contract.
            return hook()
        for args, kwargs in (
            ((), {"excitation_current": self.excitation_current}),
            ((self.excitation_current,), {}),
            ((), {}),
        ):
            try:
                sig.bind(*args, **kwargs)
            except TypeError:
                continue
            return hook(*args, **kwargs)
        raise TypeError("xy_reader must accept excitation_current or no arguments")

    @staticmethod
    def _validate_response(response: Any) -> Tuple[float, float]:
        """Validate and coerce response into a plain 2-tuple (X, Y) of finite floats."""
        if (not isinstance(response, (tuple, list, np.ndarray))
                or np.ndim(response) != 1 or len(response) != 2):
            raise TypeError(
                f"Lock-in transport response must be a 2-element sequence (X, Y) in Volts, got {response!r}"
            )
        try:
            x = float(response[0])
            y = float(response[1])
        except (TypeError, ValueError) as exc:
            raise TypeError(f"X and Y must be convertible to float, got ({response[0]!r}, {response[1]!r})") from exc

        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"X and Y voltages must be finite, got ({x}, {y})")

        return (x, y)

    def read_data(self) -> dict[str, float]:
        """
        Simulation of SNAP? 1,2,3,4.

        Returns:
            Dictionary containing X, Y, R, Theta.
        """
        x, y = self.quick_read()
        r = math.hypot(x, y)
        theta = math.degrees(math.atan2(y, x))
        return {"X": x, "Y": y, "R": r, "Theta": theta}

    def get_X(self) -> float:
        """Return the in-phase (X) voltage in Volts."""
        x, _ = self.quick_read()
        return x

    def get_Y(self) -> float:
        """Return the quadrature (Y) voltage in Volts."""
        _, y = self.quick_read()
        return y
