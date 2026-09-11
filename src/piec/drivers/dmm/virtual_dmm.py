from __future__ import annotations

import inspect
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

import numpy as np

from piec.drivers.dmm.dmm import DMM
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualDMM(VirtualInstrument, DMM):
    """
    Virtual DMM with configurable state and per-instance voltage reader hook.

    Supports per-instance hook injection (`voltage_reader` / `reader_hook`)
    with strict precedence over the deprecated shared `mag_sample` fallback.
    Returns scalar voltage readings in Volts.
    """

    _DECLARED_UNITS: Mapping[str, str] = MappingProxyType({
        "voltage": "V",
    })

    def __init__(
        self,
        address: str = "VIRTUAL",
        voltage_reader: Optional[Callable[..., float]] = None,
        reader_hook: Optional[Callable[..., float]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize Virtual DMM.

        Args:
            address: Explicit virtual instrument address.
            voltage_reader: Per-instance hook callable returning voltage in Volts.
            reader_hook: Alias for voltage_reader.
            **kwargs: Additional options forwarded to VirtualInstrument.
        """
        super().__init__(address=address, **kwargs)

        if voltage_reader is not None and reader_hook is not None:
            if voltage_reader is not reader_hook:
                raise ValueError("Cannot specify both voltage_reader and reader_hook with different callables")

        hook = voltage_reader if voltage_reader is not None else reader_hook

        self.state: dict[str, Any] = {
            "sense_func": "VOLT",
            "coupling": "DC",
            "sense_mode": "2W",
            "sense_range": None,
            "autorange": True,
            "integration_time": 1.0,
        }
        self._voltage_reader: Optional[Callable[..., float]] = None
        self.set_voltage_reader(hook)

    @property
    def declared_units(self) -> Mapping[str, str]:
        """Declared physical units for virtual DMM quantities."""
        return self._DECLARED_UNITS

    @property
    def voltage_reader(self) -> Optional[Callable[..., float]]:
        """Return the injected per-instance voltage reader hook."""
        return self._voltage_reader

    @voltage_reader.setter
    def voltage_reader(self, hook: Optional[Callable[..., float]]) -> None:
        self.set_voltage_reader(hook)

    @property
    def reader_hook(self) -> Optional[Callable[..., float]]:
        """Return the injected per-instance voltage reader hook (alias)."""
        return self._voltage_reader

    @reader_hook.setter
    def reader_hook(self, hook: Optional[Callable[..., float]]) -> None:
        self.set_voltage_reader(hook)

    def set_voltage_reader(self, voltage_reader: Optional[Callable[..., float]]) -> None:
        """
        Inject a per-instance callable hook for voltage readings in Volts.

        The hook takes precedence over the deprecated global mag_sample fallback.
        The hook may accept no arguments, or optional `ac` or `coupling` parameters.
        Passing None clears the hook and restores fallback behavior.

        Args:
            voltage_reader: Callable returning float voltage in Volts, or None.

        Raises:
            TypeError: If voltage_reader is not callable and not None.
        """
        if voltage_reader is not None and not callable(voltage_reader):
            raise TypeError(f"voltage_reader must be callable or None, got {type(voltage_reader).__name__}")
        self._voltage_reader = voltage_reader

    def set_reader_hook(self, reader_hook: Optional[Callable[..., float]]) -> None:
        """Alias for set_voltage_reader."""
        self.set_voltage_reader(reader_hook)

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
        return "Virtual DMM"

    def set_sense_function(self, sense_func: str) -> None:
        sense_func = str(sense_func).upper()
        if sense_func not in self.sense_func:
            raise ValueError(f"unsupported sense function {sense_func!r}")
        self.state["sense_func"] = sense_func

    def set_measurement_coupling(self, coupling: str) -> None:
        coupling = str(coupling).upper()
        if coupling not in self.coupling:
            raise ValueError(f"unsupported measurement coupling {coupling!r}")
        self.state["coupling"] = coupling

    def set_sense_mode(self, sense_mode: str) -> None:
        sense_mode = str(sense_mode).upper()
        if sense_mode not in self.sense_mode:
            raise ValueError(f"unsupported sense mode {sense_mode!r}")
        self.state["sense_mode"] = sense_mode

    def set_sense_range(self, range_val: Optional[float] = None, auto: bool = True) -> None:
        if not auto and range_val is None:
            raise ValueError("range_val is required when autorange is disabled")
        selected_range = None if auto else float(range_val)
        if selected_range is not None and (not math.isfinite(selected_range) or selected_range <= 0):
            raise ValueError("range_val must be positive and finite")
        self.state["sense_range"] = selected_range
        self.state["autorange"] = bool(auto)

    def set_integration_time(self, nplc: float = 1) -> None:
        nplc = float(nplc)
        if not math.isfinite(nplc) or nplc <= 0:
            raise ValueError("nplc must be positive and finite")
        self.state["integration_time"] = nplc

    def get_voltage(self, ac: bool = False) -> float:
        """
        Measure voltage in Volts.

        Precedence:
        1. Explicit per-instance hook (`voltage_reader`) if injected;
        2. Deprecated shared magnetic sample fallback (`self.mag_sample`);
        3. Default idle reading (0.0015 V).

        Args:
            ac: If True, measure in AC coupling mode; otherwise DC mode.

        Returns:
            float: Measured voltage in Volts.
        """
        self.state["sense_func"] = "VOLT"
        self.state["coupling"] = "AC" if ac else "DC"

        if self._voltage_reader is not None:
            raw = self._invoke_voltage_reader(self._voltage_reader)
            return self._validate_voltage(raw)

        if hasattr(self, "mag_sample") and self.mag_sample is not None:
            return float(self.mag_sample.current_field / 10000.0)

        return 0.0015

    def _invoke_voltage_reader(self, hook: Callable[..., Any]) -> Any:
        """Invoke the injected hook without retries; propagate hook exceptions unchanged."""
        try:
            sig = inspect.signature(hook)
        except (ValueError, TypeError):
            return hook()

        is_ac = self.state["coupling"] == "AC"
        coupling = self.state["coupling"]

        params = list(sig.parameters.values())
        values = {"ac": is_ac, "coupling": coupling}
        args = []
        kwargs = {}
        positional = [p for p in params if p.kind == inspect.Parameter.POSITIONAL_ONLY]
        requested_positions = [i for i, p in enumerate(positional) if p.name in values]
        if requested_positions:
            for p in positional[:max(requested_positions) + 1]:
                if p.name in values:
                    args.append(values[p.name])
                elif p.default is not inspect.Parameter.empty:
                    args.append(p.default)
                else:
                    raise TypeError("voltage_reader has an unsupported required positional parameter")
        for p in params:
            if p.name in values and p.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
            ):
                kwargs[p.name] = values[p.name]
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            kwargs.update({name: value for name, value in values.items() if name not in sig.parameters})
        # Binding failures precede invocation; exceptions from the hook are never caught.
        try:
            sig.bind(*args, **kwargs)
        except TypeError as error:
            raise TypeError("voltage_reader must accept no arguments or coupling/ac settings") from error
        return hook(*args, **kwargs)

    @staticmethod
    def _validate_voltage(response: Any) -> float:
        """Validate and coerce response into a scalar float in Volts."""
        if isinstance(response, (tuple, list, set, dict)) or (isinstance(response, np.ndarray) and response.ndim != 0):
            raise TypeError(
                f"voltage_reader must return a scalar float in Volts, got {type(response).__name__}"
            )
        try:
            val = float(response)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"voltage_reader returned non-numeric value: {response!r}") from exc
        return val

    def quick_read(self) -> float:
        return self.get_voltage(ac=self.state["coupling"] == "AC")

    def reset(self) -> None:
        """
        Reset virtual DMM instrument configuration to factory defaults.

        State owned by this driver (sense_func, coupling, sense_mode, sense_range,
        autorange, integration_time) is restored to default values.
        The injected per-instance voltage_reader hook is preserved.

        Driver reset does NOT reset setup-owned state: closures, external material
        models, timebase clocks, and RNG seeds are owned by the test fixture or
        VirtualBench and must be reset there.
        """
        self.state = {
            "sense_func": "VOLT",
            "coupling": "DC",
            "sense_mode": "2W",
            "sense_range": None,
            "autorange": True,
            "integration_time": 1.0,
        }

    def clear(self) -> None:
        return None

    def get_state(self) -> dict[str, Any]:
        return self.state.copy()
