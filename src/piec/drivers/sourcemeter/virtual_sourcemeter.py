"""Generic virtual sourcemeter for testing and simulation."""

from __future__ import annotations

import inspect
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from ..virtual_instrument import VirtualInstrument
from .sourcemeter import Sourcemeter
from ..scpi import Scpi
from piec.simulation.contracts import (
    ElectricalLoadContract,
    LoadMode,
    LoadResponse,
)


class VirtualSourcemeter(VirtualInstrument, Scpi, Sourcemeter):
    """
    Virtual source-and-measure instrument for testing and simulation.

    Supports generic per-instance hook injection (`load_hook` and aliases
    `source_hook`, `measure_hook`, `transport_hook`) taking strict precedence
    over default unhooked fallback. Supports both voltage-source and current-source
    modes, compliance limit clamping, and tracking of effective terminal output.
    """

    channel = [1]
    source_func = ['VOLT', 'CURR']
    sense_func = ['VOLT', 'CURR', 'RES']
    sense_mode = ['2W', '4W']
    voltage = (-210, 210)
    current = (-1.05, 1.05)
    voltage_compliance = (-210, 210)
    current_compliance = (-1.05, 1.05)

    _DECLARED_UNITS: Mapping[str, str] = MappingProxyType({
        "voltage": "V",
        "current": "A",
        "resistance": "Ohm",
        "time": "s",
    })

    def __init__(
        self,
        address: str = 'VIRTUAL',
        load_hook: Optional[Any] = None,
        source_hook: Optional[Any] = None,
        measure_hook: Optional[Any] = None,
        transport_hook: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(address=address, **kwargs)

        hooks = [h for h in (load_hook, source_hook, measure_hook, transport_hook) if h is not None]
        if hooks:
            first = hooks[0]
            if any(h is not first for h in hooks):
                raise ValueError("Cannot specify multiple conflicting hook aliases")
            selected_hook = first
        else:
            selected_hook = None

        self.state: dict[str, Any] = {
            'output_on': False,
            'source_func': 'VOLT',
            'source_voltage': 0.0,
            'source_current': 0.0,
            'sense_func': 'VOLT',
            'sense_mode': '2W',
            'voltage_compliance': 210.0,
            'current_compliance': 1.05,
            'compliance_tripped': False,
        }
        self._output_enabled: Optional[bool] = False
        self._load_hook: Optional[Any] = None
        self._effective_voltage: float = 0.0
        self._effective_current: float = 0.0
        self._compliance_tripped: bool = False
        self.set_load_hook(selected_hook)

    # Hook Management

    @property
    def declared_units(self) -> Mapping[str, str]:
        """Declared physical units for virtual sourcemeter quantities."""
        return self._DECLARED_UNITS

    @property
    def compliance_tripped(self) -> bool:
        """Whether compliance was tripped during the last output evaluation."""
        return self._compliance_tripped

    @property
    def effective_voltage(self) -> float:
        """Effective terminal voltage in Volts (0.0 V when output is off)."""
        if self.state.get('output_on') is not True:
            return 0.0
        if self._load_hook is not None:
            return self._effective_voltage
        return float(self.state['source_voltage'])

    @property
    def effective_current(self) -> float:
        """Effective terminal current in Amperes (0.0 A when output is off)."""
        if self.state.get('output_on') is not True:
            return 0.0
        if self._load_hook is not None:
            return self._effective_current
        return float(self.state['source_current'])

    @property
    def load_hook(self) -> Optional[Any]:
        """Return the injected per-instance load hook."""
        return self._load_hook

    @load_hook.setter
    def load_hook(self, hook: Optional[Any]) -> None:
        self.set_load_hook(hook)

    @property
    def source_hook(self) -> Optional[Any]:
        """Alias for load_hook."""
        return self._load_hook

    @source_hook.setter
    def source_hook(self, hook: Optional[Any]) -> None:
        self.set_load_hook(hook)

    @property
    def measure_hook(self) -> Optional[Any]:
        """Alias for load_hook."""
        return self._load_hook

    @measure_hook.setter
    def measure_hook(self, hook: Optional[Any]) -> None:
        self.set_load_hook(hook)

    @property
    def transport_hook(self) -> Optional[Any]:
        """Alias for load_hook."""
        return self._load_hook

    @transport_hook.setter
    def transport_hook(self, hook: Optional[Any]) -> None:
        self.set_load_hook(hook)

    def set_load_hook(self, hook: Optional[Any]) -> None:
        """
        Inject a per-instance load hook (ElectricalLoadContract or callable).

        The hook takes precedence over the default fallback behavior.
        Passing None clears the hook and restores fallback behavior.

        Args:
            hook: Callable or ElectricalLoadContract, or None.

        Raises:
            TypeError: If hook is not callable, does not implement evaluate(), and is not None.
        """
        if hook is not None:
            if not (callable(hook) or (hasattr(hook, "evaluate") and callable(getattr(hook, "evaluate")))):
                raise TypeError(
                    f"load_hook must be callable or implement evaluate(), got {type(hook).__name__}"
                )
        self._load_hook = hook

    def set_source_hook(self, hook: Optional[Any]) -> None:
        """Alias for set_load_hook."""
        self.set_load_hook(hook)

    def set_measure_hook(self, hook: Optional[Any]) -> None:
        """Alias for set_load_hook."""
        self.set_load_hook(hook)

    def set_transport_hook(self, hook: Optional[Any]) -> None:
        """Alias for set_load_hook."""
        self.set_load_hook(hook)

    # Instance Isolation Descriptors

    @property
    def sample(self) -> Any:
        """Return instance-specific or shared sample fallback."""
        if hasattr(self, "_instance_sample"):
            return self._instance_sample
        return super().sample

    @sample.setter
    def sample(self, val: Any) -> None:
        self._instance_sample = val

    @sample.deleter
    def sample(self) -> None:
        if hasattr(self, "_instance_sample"):
            del self._instance_sample

    @property
    def mag_sample(self) -> Any:
        """Return instance-specific or shared magnetic sample fallback."""
        if hasattr(self, "_instance_mag_sample"):
            return self._instance_mag_sample
        return super().mag_sample

    @mag_sample.setter
    def mag_sample(self, val: Any) -> None:
        self._instance_mag_sample = val

    @mag_sample.deleter
    def mag_sample(self) -> None:
        if hasattr(self, "_instance_mag_sample"):
            del self._instance_mag_sample

    # Hook Invocation Dispatch

    def _notify_or_evaluate_hook(self, output_on: bool) -> None:
        """Evaluate or notify the hook, marking state unconfirmed on failure."""
        if self._load_hook is None:
            return
        try:
            self._evaluate_hook_dispatch(self._load_hook, output_on)
        except BaseException:
            # Command execution could not be confirmed
            self.state['output_on'] = None
            self._output_enabled = None
            raise

    def _evaluate_hook_dispatch(self, hook: Any, output_on: bool) -> None:
        source_func = self.state['source_func']
        if source_func == 'VOLT':
            mode = LoadMode.VOLTAGE_SOURCE
            stimulus = float(self.state['source_voltage']) if output_on else 0.0
            compliance = float(self.state['current_compliance'])
        else:
            mode = LoadMode.CURRENT_SOURCE
            stimulus = float(self.state['source_current']) if output_on else 0.0
            compliance = float(self.state['voltage_compliance'])

        # Case 1: ElectricalLoadContract or object with .evaluate()
        if hasattr(hook, "evaluate") and callable(getattr(hook, "evaluate")):
            if not output_on:
                if callable(hook):
                    try:
                        self._invoke_callable_hook(hook, mode, stimulus, compliance, output_on)
                    except TypeError:
                        pass
                self._effective_voltage = 0.0
                self._effective_current = 0.0
                self._compliance_tripped = False
                self.state['compliance_tripped'] = False
                return

            resp = hook.evaluate(mode, stimulus, compliance, time=0.0)
            if not isinstance(resp, LoadResponse):
                raise TypeError(f"load.evaluate must return LoadResponse, got {type(resp).__name__}")
            self._effective_voltage = float(resp.voltage)
            self._effective_current = float(resp.current)
            self._compliance_tripped = bool(resp.compliance_tripped)
            self.state['compliance_tripped'] = self._compliance_tripped
            return

        # Case 2: Generic callable
        result = self._invoke_callable_hook(hook, mode, stimulus, compliance, output_on)
        self._process_callable_result(result, source_func, stimulus, compliance, output_on)

    def _invoke_callable_hook(
        self,
        hook: Callable[..., Any],
        mode: LoadMode,
        stimulus: float,
        compliance: float,
        output_on: bool,
    ) -> Any:
        try:
            sig = inspect.signature(hook)
        except (ValueError, TypeError):
            return hook(mode, stimulus, compliance)

        source_func = self.state['source_func']
        eff_v = stimulus if (output_on and source_func == 'VOLT') else (0.0 if not output_on else self.state['source_voltage'])
        eff_i = stimulus if (output_on and source_func == 'CURR') else (0.0 if not output_on else self.state['source_current'])

        values: dict[str, Any] = {
            "mode": mode,
            "source_func": source_func,
            "stimulus": stimulus,
            "value": stimulus,
            "val": stimulus,
            "level": stimulus,
            "compliance": compliance,
            "limit": compliance,
            "voltage": eff_v,
            "v": eff_v,
            "volt": eff_v,
            "current": eff_i,
            "i": eff_i,
            "curr": eff_i,
            "source_voltage": self.state['source_voltage'],
            "source_current": self.state['source_current'],
            "voltage_compliance": self.state['voltage_compliance'],
            "current_compliance": self.state['current_compliance'],
            "output_on": output_on,
            "on": output_on,
            "channel": 1,
            "ch": 1,
            "time": 0.0,
            "t": 0.0,
        }

        params = list(sig.parameters.values())
        if len(params) == 0:
            return hook()

        args: list[Any] = []
        kwargs: dict[str, Any] = {}

        # 1. Positional-only parameters
        positional = [p for p in params if p.kind == inspect.Parameter.POSITIONAL_ONLY]
        if positional:
            for i, p in enumerate(positional):
                if p.name in values:
                    args.append(values[p.name])
                elif len(positional) == 1:
                    args.append(stimulus)
                elif len(positional) == 2:
                    args.append(eff_v if i == 0 else eff_i)
                elif len(positional) == 3:
                    args.append([mode, stimulus, compliance][i])
                elif p.default is not inspect.Parameter.empty:
                    args.append(p.default)
                else:
                    raise TypeError(f"load_hook has unsupported required positional parameter {p.name!r}")

        # 2. Positional or keyword parameters
        pos_kw = [p for p in params if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD]
        for i, p in enumerate(params):
            if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                if not positional and p.name not in values:
                    if i == 0:
                        args.append(stimulus)
                    elif i == 1 and len([x for x in pos_kw if x.default is inspect.Parameter.empty]) >= 2:
                        args.append(eff_i if source_func == 'VOLT' else eff_v)
                    elif p.default is not inspect.Parameter.empty:
                        pass
                    else:
                        raise TypeError(f"load_hook parameter {p.name!r} cannot be bound")
                elif p.name in values:
                    kwargs[p.name] = values[p.name]
            elif p.kind == inspect.Parameter.KEYWORD_ONLY:
                if p.name in values:
                    kwargs[p.name] = values[p.name]
                elif p.default is inspect.Parameter.empty:
                    raise TypeError(f"load_hook keyword-only parameter {p.name!r} cannot be bound")

        # 3. *args
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params) and not args and not kwargs:
            args.append(stimulus)

        # 4. **kwargs
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            for k, v in values.items():
                if k not in kwargs and k not in [p.name for p in params]:
                    kwargs[k] = v

        try:
            sig.bind(*args, **kwargs)
        except TypeError as err:
            if len(params) == 0:
                return hook()
            raise TypeError("load_hook has incompatible signature") from err

        return hook(*args, **kwargs)

    def _process_callable_result(
        self,
        result: Any,
        source_func: str,
        stimulus: float,
        compliance: float,
        output_on: bool,
    ) -> None:
        if not output_on:
            self._effective_voltage = 0.0
            self._effective_current = 0.0
            self._compliance_tripped = False
            self.state['compliance_tripped'] = False
            return

        if isinstance(result, LoadResponse):
            self._effective_voltage = float(result.voltage)
            self._effective_current = float(result.current)
            self._compliance_tripped = bool(result.compliance_tripped)
            self.state['compliance_tripped'] = self._compliance_tripped
            return

        if isinstance(result, (tuple, list)) and len(result) == 2:
            v_val = float(result[0])
            i_val = float(result[1])
            if not math.isfinite(v_val) or not math.isfinite(i_val):
                raise ValueError("load_hook returned non-finite values")
            if source_func == 'VOLT':
                if abs(i_val) >= compliance:
                    i_val = math.copysign(compliance, i_val)
                    tripped = True
                else:
                    tripped = False
            else:
                if abs(v_val) >= compliance:
                    v_val = math.copysign(compliance, v_val)
                    tripped = True
                else:
                    tripped = False
            self._effective_voltage = v_val
            self._effective_current = i_val
            self._compliance_tripped = tripped
            self.state['compliance_tripped'] = tripped
            return

        if isinstance(result, Mapping):
            v_val = float(result.get('voltage', result.get('v', stimulus if source_func == 'VOLT' else self.state['source_voltage'])))
            i_val = float(result.get('current', result.get('i', stimulus if source_func == 'CURR' else self.state['source_current'])))
            if not math.isfinite(v_val) or not math.isfinite(i_val):
                raise ValueError("load_hook returned non-finite values")
            tripped = result.get('compliance_tripped', None)
            if tripped is None:
                if source_func == 'VOLT':
                    tripped = abs(i_val) >= compliance
                    if tripped:
                        i_val = math.copysign(compliance, i_val)
                else:
                    tripped = abs(v_val) >= compliance
                    if tripped:
                        v_val = math.copysign(compliance, v_val)
            self._effective_voltage = v_val
            self._effective_current = i_val
            self._compliance_tripped = bool(tripped)
            self.state['compliance_tripped'] = self._compliance_tripped
            return

        if isinstance(result, Real) and not isinstance(result, bool):
            val_f = float(result)
            if not math.isfinite(val_f):
                raise ValueError("load_hook returned non-finite value")
            if source_func == 'VOLT':
                v_val = stimulus
                i_val = val_f
                tripped = abs(i_val) >= compliance
                if tripped:
                    i_val = math.copysign(compliance, i_val)
            else:
                i_val = stimulus
                v_val = val_f
                tripped = abs(v_val) >= compliance
                if tripped:
                    v_val = math.copysign(compliance, v_val)
            self._effective_voltage = v_val
            self._effective_current = i_val
            self._compliance_tripped = tripped
            self.state['compliance_tripped'] = tripped
            return

        if result is None:
            if source_func == 'VOLT':
                self._effective_voltage = stimulus
                self._effective_current = self.state['source_current']
            else:
                self._effective_voltage = self.state['source_voltage']
                self._effective_current = stimulus
            self._compliance_tripped = False
            self.state['compliance_tripped'] = False
            return

        raise TypeError(f"Invalid return type from load_hook: {type(result).__name__}")

    def _notify_hook_shutdown(self) -> None:
        if self._load_hook is None:
            return
        if hasattr(self._load_hook, "evaluate") and not callable(self._load_hook):
            return
        if callable(self._load_hook):
            mode = LoadMode.VOLTAGE_SOURCE if self.state['source_func'] == 'VOLT' else LoadMode.CURRENT_SOURCE
            compliance = float(self.state['current_compliance'] if mode == LoadMode.VOLTAGE_SOURCE else self.state['voltage_compliance'])
            self._invoke_callable_hook(self._load_hook, mode, 0.0, compliance, output_on=False)

    # SCPI Command Handling

    def idn(self) -> str:
        return "PIEC,Virtual_Sourcemeter,s/n_virtual,ver1.0"

    def write(self, command: str) -> None:
        cmd = command.upper().strip()

        if ':OUTP' in cmd:
            self.output(channel=1, on='ON' in cmd)
        elif ':SOUR:FUNC' in cmd:
            if 'VOLT' in cmd:
                self.set_source_function(channel=1, source_func='VOLT')
            elif 'CURR' in cmd:
                self.set_source_function(channel=1, source_func='CURR')
        elif ':SOUR:VOLT:LEV' in cmd:
            try:
                val = self._extract_value(cmd)
                self.set_source_voltage(channel=1, voltage=val)
            except ValueError:
                pass
        elif ':SOUR:CURR:LEV' in cmd:
            try:
                val = self._extract_value(cmd)
                self.set_source_current(channel=1, current=val)
            except ValueError:
                pass
        elif ':SENS:FUNC' in cmd:
            if 'VOLT' in cmd:
                self.set_sense_function(channel=1, sense_func='VOLT')
            elif 'CURR' in cmd:
                self.set_sense_function(channel=1, sense_func='CURR')
            elif 'RES' in cmd:
                self.set_sense_function(channel=1, sense_func='RES')
        elif ':SENS:VOLT:PROT' in cmd:
            try:
                val = self._extract_value(cmd)
                self.set_voltage_compliance(channel=1, voltage_compliance=val)
            except ValueError:
                pass
        elif ':SENS:CURR:PROT' in cmd:
            try:
                val = self._extract_value(cmd)
                self.set_current_compliance(channel=1, current_compliance=val)
            except ValueError:
                pass
        elif ':SYST:RSEN' in cmd:
            self.set_sense_mode(channel=1, sense_mode='4W' if 'ON' in cmd else '2W')
        elif cmd == '*RST':
            self.reset()
        elif cmd == '*CLS':
            pass

    def query(self, command: str) -> str:
        cmd = command.upper().strip()

        if cmd == '*IDN?':
            return self.idn()
        elif cmd == '*ESR?':
            return '0'
        elif cmd == '*OPC?':
            return '1'
        elif ':READ?' in cmd:
            if self._load_hook is not None and self.state['output_on'] is True:
                self._notify_or_evaluate_hook(output_on=True)
                v = self._effective_voltage
                i = self._effective_current
            elif self._load_hook is not None and self.state['output_on'] is not True:
                v = 0.0
                i = 0.0
            else:
                v = self.state['source_voltage']
                i = self.state['source_current']
            r = v / i if i != 0 else float('inf')
            return f"{v:.6E},{i:.6E},{r:.6E},0.000000E+00,0"
        elif ':SOUR:VOLT:LEV?' in cmd:
            return str(self.state['source_voltage'])
        elif ':SOUR:CURR:LEV?' in cmd:
            return str(self.state['source_current'])
        elif ':SENS:VOLT:PROT?' in cmd:
            return str(self.state['voltage_compliance'])
        elif ':SENS:CURR:PROT?' in cmd:
            return str(self.state['current_compliance'])
        elif ':OUTP?' in cmd:
            if self.state['output_on'] is True:
                return '1'
            elif self.state['output_on'] is False:
                return '0'
            return 'UNKNOWN'
        return ''

    @staticmethod
    def _extract_value(command: str) -> float:
        parts = command.replace(':', ' ').replace(',', ' ').split()
        for part in reversed(parts):
            try:
                return float(part)
            except ValueError:
                continue
        raise ValueError(f"No numeric value found in command: {command}")

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    # Core Instrument State Control

    def output(self, channel: int = 1, on: bool = True) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if not isinstance(on, (bool, int)) or on not in (False, True, 0, 1):
            raise TypeError(f"on must be a boolean or 0/1, got {type(on).__name__}")
        on_bool = bool(on)
        self.state['output_on'] = on_bool
        self._output_enabled = on_bool

        if self._load_hook is not None:
            self._notify_or_evaluate_hook(output_on=on_bool)

    def set_source_function(self, channel: int = 1, source_func: Optional[str] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if source_func is None:
            raise ValueError("source_func must be provided")
        norm = str(source_func).upper()
        if norm not in self.source_func:
            raise ValueError(f"Invalid source_func {source_func}. Must be one of {self.source_func}")
        self.state['source_func'] = norm
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    def set_sense_function(self, channel: int = 1, sense_func: Optional[str] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if sense_func is None:
            raise ValueError("sense_func must be provided")
        norm = str(sense_func).upper()
        if norm not in self.sense_func:
            raise ValueError(f"Invalid sense_func {sense_func}. Must be one of {self.sense_func}")
        self.state['sense_func'] = norm

    def set_sense_mode(self, channel: int = 1, sense_mode: Optional[str] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if sense_mode is None:
            raise ValueError("sense_mode must be provided")
        norm = str(sense_mode).upper()
        if norm not in self.sense_mode:
            raise ValueError(f"Invalid sense_mode {sense_mode}. Must be one of {self.sense_mode}")
        self.state['sense_mode'] = norm

    # Source Configuration

    def set_source_voltage(self, channel: int = 1, voltage: Optional[float] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if voltage is None:
            raise ValueError("voltage must be provided")
        if isinstance(voltage, bool) or not isinstance(voltage, (int, float, Real)):
            raise TypeError(f"voltage must be numeric, got {type(voltage).__name__}")
        val_f = float(voltage)
        if not math.isfinite(val_f):
            raise ValueError(f"voltage must be finite, got {voltage!r}")
        self.state['source_voltage'] = self._clamp(val_f, *self.voltage)
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    def set_source_current(self, channel: int = 1, current: Optional[float] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if current is None:
            raise ValueError("current must be provided")
        if isinstance(current, bool) or not isinstance(current, (int, float, Real)):
            raise TypeError(f"current must be numeric, got {type(current).__name__}")
        val_f = float(current)
        if not math.isfinite(val_f):
            raise ValueError(f"current must be finite, got {current!r}")
        self.state['source_current'] = self._clamp(val_f, *self.current)
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    def set_voltage_compliance(self, channel: int = 1, voltage_compliance: Optional[float] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if voltage_compliance is None:
            raise ValueError("voltage_compliance must be provided")
        if isinstance(voltage_compliance, bool) or not isinstance(voltage_compliance, (int, float, Real)):
            raise TypeError(f"voltage_compliance must be numeric, got {type(voltage_compliance).__name__}")
        val_f = float(voltage_compliance)
        if not math.isfinite(val_f) or val_f <= 0.0:
            raise ValueError(f"voltage_compliance must be a positive finite number, got {voltage_compliance!r}")
        self.state['voltage_compliance'] = self._clamp(val_f, *self.voltage_compliance)
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    def set_current_compliance(self, channel: int = 1, current_compliance: Optional[float] = None) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if current_compliance is None:
            raise ValueError("current_compliance must be provided")
        if isinstance(current_compliance, bool) or not isinstance(current_compliance, (int, float, Real)):
            raise TypeError(f"current_compliance must be numeric, got {type(current_compliance).__name__}")
        val_f = float(current_compliance)
        if not math.isfinite(val_f) or val_f <= 0.0:
            raise ValueError(f"current_compliance must be a positive finite number, got {current_compliance!r}")
        self.state['current_compliance'] = self._clamp(val_f, *self.current_compliance)
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    # Convenience Configuration

    def configure_voltage_source(
        self,
        channel: int = 1,
        voltage: float = 0.0,
        current_compliance: float = 1.05,
    ) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if voltage is None:
            raise ValueError("voltage must be provided")
        if isinstance(voltage, bool) or not isinstance(voltage, (int, float, Real)):
            raise TypeError(f"voltage must be numeric, got {type(voltage).__name__}")
        v_val = float(voltage)
        if not math.isfinite(v_val):
            raise ValueError(f"voltage must be finite, got {voltage!r}")

        if current_compliance is None:
            raise ValueError("current_compliance must be provided")
        if isinstance(current_compliance, bool) or not isinstance(current_compliance, (int, float, Real)):
            raise TypeError(f"current_compliance must be numeric, got {type(current_compliance).__name__}")
        c_val = float(current_compliance)
        if not math.isfinite(c_val) or c_val <= 0.0:
            raise ValueError(f"current_compliance must be a positive finite number, got {current_compliance!r}")

        self.state['source_func'] = 'VOLT'
        self.state['source_voltage'] = self._clamp(v_val, *self.voltage)
        self.state['current_compliance'] = self._clamp(c_val, *self.current_compliance)
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    def configure_current_source(
        self,
        channel: int = 1,
        current: float = 0.0,
        voltage_compliance: float = 210.0,
    ) -> None:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if current is None:
            raise ValueError("current must be provided")
        if isinstance(current, bool) or not isinstance(current, (int, float, Real)):
            raise TypeError(f"current must be numeric, got {type(current).__name__}")
        i_val = float(current)
        if not math.isfinite(i_val):
            raise ValueError(f"current must be finite, got {current!r}")

        if voltage_compliance is None:
            raise ValueError("voltage_compliance must be provided")
        if isinstance(voltage_compliance, bool) or not isinstance(voltage_compliance, (int, float, Real)):
            raise TypeError(f"voltage_compliance must be numeric, got {type(voltage_compliance).__name__}")
        v_val = float(voltage_compliance)
        if not math.isfinite(v_val) or v_val <= 0.0:
            raise ValueError(f"voltage_compliance must be a positive finite number, got {voltage_compliance!r}")

        self.state['source_func'] = 'CURR'
        self.state['source_current'] = self._clamp(i_val, *self.current)
        self.state['voltage_compliance'] = self._clamp(v_val, *self.voltage_compliance)
        if self._load_hook is not None and self.state.get('output_on') is True:
            self._notify_or_evaluate_hook(output_on=True)

    # Measurement (Read) Methods

    def quick_read(self, channel: int = 1) -> float:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        sense = self.state['sense_func']
        if sense == 'VOLT':
            return self.get_voltage(channel=channel)
        elif sense == 'CURR':
            return self.get_current(channel=channel)
        elif sense == 'RES':
            return self.get_resistance(channel=channel)
        return self.get_voltage(channel=channel)

    def get_voltage(self, channel: int = 1) -> float:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['sense_func'] = 'VOLT'
        if self._load_hook is not None:
            if self.state.get('output_on') is True:
                self._notify_or_evaluate_hook(output_on=True)
                return self._effective_voltage
            return 0.0
        return self.state['source_voltage']

    def get_current(self, channel: int = 1) -> float:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['sense_func'] = 'CURR'
        if self._load_hook is not None:
            if self.state.get('output_on') is True:
                self._notify_or_evaluate_hook(output_on=True)
                return self._effective_current
            return 0.0
        return self.state['source_current']

    def get_resistance(self, channel: int = 1) -> float:
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['sense_func'] = 'RES'
        if self._load_hook is not None:
            if self.state.get('output_on') is True:
                self._notify_or_evaluate_hook(output_on=True)
                v = self._effective_voltage
                i = self._effective_current
                return v / i if i != 0 else float('inf')
            return float('inf')
        v, i = self.state['source_voltage'], self.state['source_current']
        return v / i if i != 0 else float('inf')

    # State & Reset

    def reset(self) -> None:
        """
        Reset virtual sourcemeter configuration to factory defaults with output disabled.

        Restores driver-owned state (output_on=False, source_func='VOLT', source_voltage=0.0,
        source_current=0.0, sense_func='VOLT', sense_mode='2W', voltage_compliance=210.0,
        current_compliance=1.05, compliance_tripped=False) while preserving the injected hook.

        Driver reset does NOT reset setup-owned state: closures, external load/material models,
        timebase clocks, and RNG seeds are owned by the test fixture or VirtualBench and must
        be reset there.
        """
        self.state = {
            'output_on': False,
            'source_func': 'VOLT',
            'source_voltage': 0.0,
            'source_current': 0.0,
            'sense_func': 'VOLT',
            'sense_mode': '2W',
            'voltage_compliance': 210.0,
            'current_compliance': 1.05,
            'compliance_tripped': False,
        }
        self._output_enabled = False
        self._effective_voltage = 0.0
        self._effective_current = 0.0
        self._compliance_tripped = False

        if self._load_hook is not None:
            try:
                self._notify_hook_shutdown()
            except BaseException:
                self.state['output_on'] = None
                self._output_enabled = None
                raise

    def clear(self) -> None:
        pass

    def get_state(self) -> dict[str, Any]:
        return self.state.copy()
