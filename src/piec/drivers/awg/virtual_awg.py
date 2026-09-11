"""
Virtual Arbitrary Waveform Generator (AWG) Module

This module provides a virtual implementation of the Keysight 81150A AWG for simulation and testing purposes.
It mimics the behavior of a physical AWG by maintaining internal state and generating synthetic waveforms.
"""

from __future__ import annotations

import inspect
import re
from copy import deepcopy
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np

from ..virtual_instrument import (
    VirtualInstrument,
    warn_for_large_simulation_input,
    warn_for_large_simulation_points,
)
from .awg import Awg


class VirtualAwg(VirtualInstrument, Awg):
    """
    Virtual version of the Keysight81150a AWG for simulation/testing.
    Stores state internally and generates synthetic output.

    Attributes:
        channel (list): Available output channels [1, 2]
        waveform (list): Supported waveform types ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
        amplitude (tuple): Output amplitude range in volts (min, max)
        offset (tuple): DC offset range in volts (min, max)
        polarity (list): Output polarity modes ['NORM', 'INV']
        duty_cycle (tuple): Duty cycle range in percent (min, max)
        symmetry (tuple): Ramp symmetry range in percent (min, max)
        pulse_width (tuple): Pulse width range in seconds (min, max)
        pulse_delay (tuple): Pulse delay range in seconds (min, max)
        trigger_source (list): Available trigger sources ['IMM', 'INT', 'EXT', 'MAN']
        trigger_slope (list): Trigger slope options ['POS', 'NEG', 'EITH']
        trigger_mode (list): Trigger mode options ['EDGE', 'LEV']
        arb_dac_value (tuple): DAC value range for arbitrary waveforms (min, max)
        arb_data_length (tuple): Number of points range for arbitrary waveforms (min, max)
    """

    channel = [1, 2]
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
    amplitude = (0, 50)
    offset = (-50, 50)
    polarity = ['NORM', 'INV']
    duty_cycle = (0.0, 100.0)
    symmetry = (0.0, 100.0)
    pulse_width = (4.1e-9, 950000)
    pulse_delay = pulse_width
    trigger_source = ['IMM', 'INT', 'EXT', 'MAN']
    trigger_slope = ['POS', 'NEG', 'EITH']
    trigger_mode = ['EDGE', 'LEV']

    arb_dac_value = (0, 16383)  # Range for individual DAC points in arb_data_range data list
    arb_data_range = (2, 4000)  # Points, for arbitrary waveform data len

    _DECLARED_UNITS: Mapping[str, str] = MappingProxyType({
        "voltage": "V",
        "frequency": "Hz",
        "time": "s",
    })

    def __init__(
        self,
        address: str = 'VIRTUAL',
        simulation_points: Optional[int] = None,
        check_params: bool = False,
        verbose: bool = False,
        waveform_hook: Optional[Callable[..., Any]] = None,
        apply_hook: Optional[Callable[..., Any]] = None,
        trigger_hook: Optional[Callable[..., Any]] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the virtual AWG with default settings and optional hook injection.

        Args:
            address (str, optional): Virtual address for the instrument. Defaults to 'VIRTUAL'.
            simulation_points (int, optional): Number of samples used for
                synthetic waveform generation. This is independent of the
                hardware ``arb_data_range`` capability.
            check_params (bool, optional): Enable automatic parameter validation.
            verbose (bool, optional): Enable verbose virtual-driver output.
            waveform_hook (callable, optional): Per-instance hook invoked on waveform trigger.
                Receives generated waveform array v and time array t, or keyword arguments.
                When provided, takes strict precedence over global/shared sample simulation.
            apply_hook (callable, optional): Alias for waveform_hook.
            trigger_hook (callable, optional): Alias for waveform_hook.
            **kwargs: Additional arguments passed to parent classes.
        """
        self._rng = np.random.default_rng(seed)
        self._initial_rng_state = deepcopy(self._rng.bit_generator.state)
        super().__init__(
            address=address,
            simulation_points=simulation_points,
            check_params=check_params,
            verbose=verbose,
            **kwargs,
        )

        hooks = [
            ("waveform_hook", waveform_hook),
            ("apply_hook", apply_hook),
            ("trigger_hook", trigger_hook),
        ]
        provided = [(name, h) for name, h in hooks if h is not None]
        if len(provided) > 1:
            first = provided[0][1]
            if any(h is not first for _, h in provided[1:]):
                raise ValueError("Conflicting hooks provided: waveform_hook, apply_hook, and trigger_hook")
        hook = provided[0][1] if provided else None

        if hook is not None and not callable(hook):
            raise TypeError(f"waveform_hook must be callable or None, got {type(hook).__name__}")

        self._waveform_hook: Optional[Callable[..., Any]] = hook
        self._instance_sample: Any = None

        self.state: dict[str, Any] = {
            'output': {ch: False for ch in self.channel},
            'waveform': {ch: 'SIN' for ch in self.channel},
            'frequency': {ch: 1e3 for ch in self.channel},
            'amplitude': {ch: 1.0 for ch in self.channel},
            'offset': {ch: 0.0 for ch in self.channel},
            'source_impedance': {ch: 5 for ch in self.channel},
            'load_impedance': {ch: 50.0 for ch in self.channel},
            'polarity': {ch: 'NORM' for ch in self.channel},
            'duty_cycle': {ch: 50.0 for ch in self.channel},
            'symmetry': {ch: 50.0 for ch in self.channel},
            'pulse_width': {ch: 1e-6 for ch in self.channel},
            'pulse_delay': {ch: 0.0 for ch in self.channel},
            'trigger_source': {ch: 'IMM' for ch in self.channel},
            'trigger_level': {ch: 0.0 for ch in self.channel},
            'trigger_slope': {ch: 'POS' for ch in self.channel},
            'trigger_mode': {ch: 'EDGE' for ch in self.channel},
            'arb_waveform': {ch: None for ch in self.channel},
            'acquisition_channel': 1,  # Default acquisition channel
        }

    # ------------------------------------------------------------------------
    # Declared Units and Instance Isolation
    # ------------------------------------------------------------------------

    @property
    def declared_units(self) -> Mapping[str, str]:
        """Declared physical units for virtual AWG parameters."""
        return self._DECLARED_UNITS

    @property
    def sample(self) -> Any:
        """Instance-isolated sample property preserving fallback semantics without polluting class state."""
        if self._instance_sample is not None:
            return self._instance_sample
        return VirtualInstrument._shared_fe_sample

    @sample.setter
    def sample(self, sample: Any) -> None:
        self._instance_sample = sample

    @sample.deleter
    def sample(self) -> None:
        self._instance_sample = None

    # ------------------------------------------------------------------------
    # Hook Injection and Accessors
    # ------------------------------------------------------------------------

    def set_waveform_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        """
        Inject a per-instance waveform hook callable, or clear with None.

        When injected, the hook is invoked whenever the AWG is triggered.
        Explicit hook injection takes strict precedence over deprecated shared-sample simulation.
        """
        if hook is not None and not callable(hook):
            raise TypeError(f"waveform_hook must be callable or None, got {type(hook).__name__}")
        self._waveform_hook = hook

    def set_apply_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        """Alias for set_waveform_hook."""
        self.set_waveform_hook(hook)

    def set_trigger_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        """Alias for set_waveform_hook."""
        self.set_waveform_hook(hook)

    @property
    def waveform_hook(self) -> Optional[Callable[..., Any]]:
        """Active per-instance waveform hook callable, or None."""
        return self._waveform_hook

    @waveform_hook.setter
    def waveform_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_waveform_hook(hook)

    @property
    def apply_hook(self) -> Optional[Callable[..., Any]]:
        """Active per-instance waveform hook callable, or None."""
        return self._waveform_hook

    @apply_hook.setter
    def apply_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_waveform_hook(hook)

    @property
    def trigger_hook(self) -> Optional[Callable[..., Any]]:
        """Active per-instance waveform hook callable, or None."""
        return self._waveform_hook

    @trigger_hook.setter
    def trigger_hook(self, hook: Optional[Callable[..., Any]]) -> None:
        self.set_waveform_hook(hook)

    # ------------------------------------------------------------------------
    # Identification & State Queries
    # ------------------------------------------------------------------------

    def idn(self) -> str:
        """Get the identification string of the virtual AWG."""
        return "Virtual AWG"

    def get_state(self) -> dict[str, Any]:
        """Return a deep copy of the internal driver state."""
        return deepcopy(self.state)

    # ------------------------------------------------------------------------
    # Triggering and SCPI Command Dispatch
    # ------------------------------------------------------------------------

    def send_software_trigger(self) -> None:
        """Send a software trigger command to the AWG."""
        self.write('*TRG')

    def output_trigger(self) -> None:
        """
        Outputs the trigger signal for the AWG.
        Equivalent to sending a manual trigger.
        """
        self.write(':TRIG')

    def trigger(self) -> None:
        """Convenience method to trigger waveform generation."""
        self.write(':TRIG')

    def write(self, command: str) -> None:
        """
        Simulate writing a SCPI command to the instrument.

        Args:
            command (str): SCPI command string to process
        """
        cmd = command.upper().strip()
        if cmd in ('*TRG', ':TRIG', 'TRIG', ':TRIG:IMM', '*TRG;'):
            self._handle_trigger()
        elif cmd == '*RST':
            self.reset()
        elif cmd == '*CLS':
            pass
        elif cmd.startswith((':OUTP', 'OUTP')):
            match = re.fullmatch(r':?OUTP(?:UT)?([12])?\s+(ON|OFF|0|1)', cmd)
            if match is None:
                raise ValueError("unsupported output command")
            self.output(int(match[1] or 1), match[2] in ('ON', '1'))

    def query(self, command: str) -> str:
        """
        Simulate querying the instrument via SCPI.

        Args:
            command (str): SCPI query string

        Returns:
            str: Response string
        """
        cmd = command.upper().strip()
        if cmd == '*IDN?':
            return self.idn()
        elif cmd == '*OPC?':
            return '1'
        elif cmd == '*ESR?':
            return '0'
        match = re.fullmatch(r':?OUTP(?:UT)?([12])?\?', cmd)
        if match:
            return '1' if self.state['output'][int(match[1] or 1)] else '0'
        match = re.fullmatch(r':?(?:SOUR(?:CE)?([12])?:)?(FREQ|VOLT)\?', cmd)
        if match:
            channel = int(match[1] or 1)
            key = 'frequency' if match[2] == 'FREQ' else 'amplitude'
            return str(self.state[key][channel])
        return ''

    def _handle_trigger(self) -> None:
        """
        Execute waveform trigger.

        When waveform_hook is set:
        Dispatches generated waveform to hook with exact-once invocation and unchanged error propagation.
        self.sample is never accessed or mutated.

        When waveform_hook is None:
        Falls back to legacy sample simulation (prepending 20 zero-volt points).
        """
        ch = self.state['acquisition_channel']
        v = self.get_waveform(ch)
        freq = self.state['frequency'][ch]
        duration = 1.0 / freq if freq > 0 else 1.0

        if self._waveform_hook is not None:
            t = np.linspace(0, duration, len(v))
            self._invoke_hook(self._waveform_hook, v, t, ch, freq, duration)
        else:
            # Legacy fallback path
            prep_points = 20
            v_prep = np.concatenate([np.zeros(prep_points), v])
            t_prep = np.linspace(0, duration * len(v_prep) / (len(v_prep) - prep_points), len(v_prep))
            if hasattr(self, "sample") and self.sample is not None:
                try:
                    self.sample.prep_points = prep_points
                except Exception:
                    pass
            if hasattr(self.sample, "apply_waveform") and callable(self.sample.apply_waveform):
                self.sample.apply_waveform(v_prep, t_prep)

    def _invoke_hook(
        self,
        hook: Callable[..., Any],
        v: np.ndarray,
        t: np.ndarray,
        channel: int,
        freq: float,
        duration: float,
    ) -> Any:
        """Inspect signature, cleanly bind parameters, and invoke hook exactly once."""
        try:
            sig = inspect.signature(hook)
        except (ValueError, TypeError):
            return hook(v, t)

        values: dict[str, Any] = {
            "v": v,
            "voltages": v,
            "waveform": v,
            "v_applied": v,
            "data": v,
            "t": t,
            "times": t,
            "timestamps": t,
            "time": t,
            "channel": channel,
            "ch": channel,
            "freq": freq,
            "frequency": freq,
            "duration": duration,
            "amplitude": self.state["amplitude"][channel],
            "amp": self.state["amplitude"][channel],
            "offset": self.state["offset"][channel],
            "waveform_type": self.state["waveform"][channel],
            "wf": self.state["waveform"][channel],
            "output": self.state["output"][channel],
            "output_on": self.state["output"][channel],
            "output_enabled": self.state["output"][channel],
            "points": len(v),
            "num_points": len(v),
            "state": self.get_state(),
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
                    args.append(v)
                elif i == 1:
                    args.append(t)
                elif i == 2:
                    args.append(channel)
                else:
                    raise TypeError(f"waveform_hook has unsupported required positional parameter {p.name!r}")

        # 2. Positional or keyword parameters
        for i, p in enumerate(params):
            if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                if p.name in values:
                    kwargs[p.name] = values[p.name]
                elif p.default is not inspect.Parameter.empty:
                    continue
                elif not positional and i == 0:
                    kwargs[p.name] = v
                elif not positional and i == 1:
                    kwargs[p.name] = t
                elif not positional and i == 2:
                    kwargs[p.name] = channel
            elif p.kind == inspect.Parameter.KEYWORD_ONLY and p.name in values:
                kwargs[p.name] = values[p.name]

        # 3. Variadic *args and **kwargs
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params) and not args and not kwargs:
            args.extend([v, t])
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            kwargs.update({k: val for k, val in values.items() if k not in sig.parameters})

        try:
            sig.bind(*args, **kwargs)
        except TypeError as error:
            if len(params) == 0:
                return hook()
            raise TypeError("waveform_hook has incompatible signature") from error

        return hook(*args, **kwargs)

    # ------------------------------------------------------------------------
    # Channel and Output Configuration
    # ------------------------------------------------------------------------

    def _validate_channel(self, channel: int) -> int:
        if isinstance(channel, bool) or not isinstance(channel, (int, np.integer)):
            raise TypeError(f"channel must be an integer, got {type(channel).__name__}")
        ch = int(channel)
        if ch not in self.channel:
            raise ValueError(f"Invalid channel {ch}. Must be one of {self.channel}")
        return ch

    def output(self, channel: int, on: bool = True) -> None:
        """
        Enable or disable the output for a channel.

        Args:
            channel (int): Channel number (1-2)
            on (bool, optional): True to enable output, False to disable. Defaults to True.
        """
        ch = self._validate_channel(channel)
        if not isinstance(on, (bool, int, np.bool_)):
            raise TypeError(f"on must be a boolean, got {type(on).__name__}")
        self.state['output'][ch] = bool(on)

    def set_source_impedance(self, channel: int, source_impedance: float) -> None:
        """
        Set the source impedance for a channel.

        Args:
            channel (int): Channel number (1-2)
            source_impedance (float): Source impedance in ohms
        """
        ch = self._validate_channel(channel)
        if isinstance(source_impedance, bool) or not isinstance(source_impedance, Real):
            raise TypeError(f"source_impedance must be a numeric value, got {type(source_impedance).__name__}")
        val = float(source_impedance)
        if not math.isfinite(val) or val <= 0.0:
            raise ValueError(f"source_impedance must be positive finite, got {source_impedance}")
        self.state['source_impedance'][ch] = val

    def set_load_impedance(self, channel: int, load_impedance: float) -> None:
        """
        Set the load impedance for a channel.

        Args:
            channel (int): Channel number (1-2)
            load_impedance (float): Load impedance in ohms
        """
        ch = self._validate_channel(channel)
        if isinstance(load_impedance, bool) or not isinstance(load_impedance, Real):
            raise TypeError(f"load_impedance must be a numeric value, got {type(load_impedance).__name__}")
        val = float(load_impedance)
        if not math.isfinite(val) or val <= 0.0:
            raise ValueError(f"load_impedance must be positive finite, got {load_impedance}")
        self.state['load_impedance'][ch] = val

    def set_waveform(self, channel: int, waveform: str) -> None:
        """
        Set the waveform type for a channel.

        Args:
            channel (int): Channel number (1-2)
            waveform (str): Waveform type (e.g., 'SIN', 'SQU', etc.)
        """
        ch = self._validate_channel(channel)
        if not isinstance(waveform, str):
            raise TypeError(f"waveform must be a string, got {type(waveform).__name__}")
        wf_upper = waveform.strip().upper()
        if wf_upper not in self.waveform:
            raise ValueError(f"Invalid waveform {waveform!r}. Must be one of {self.waveform}")
        self.state['waveform'][ch] = wf_upper

    def set_frequency(self, channel: int, frequency: float) -> None:
        """
        Set the frequency for a channel.

        Args:
            channel (int): Channel number (1-2)
            frequency (float): Frequency in hertz
        """
        ch = self._validate_channel(channel)
        if isinstance(frequency, bool) or not isinstance(frequency, Real):
            raise TypeError(f"frequency must be a numeric value, got {type(frequency).__name__}")
        val = float(frequency)
        if not math.isfinite(val) or val <= 0.0:
            raise ValueError(f"frequency must be positive finite, got {frequency}")
        self.state['frequency'][ch] = val

    def set_amplitude(self, channel: int, amplitude: float) -> None:
        """
        Set the amplitude for a channel.

        Args:
            channel (int): Channel number (1-2)
            amplitude (float): Amplitude in volts
        """
        ch = self._validate_channel(channel)
        if isinstance(amplitude, bool) or not isinstance(amplitude, Real):
            raise TypeError(f"amplitude must be a numeric value, got {type(amplitude).__name__}")
        val = float(amplitude)
        if not math.isfinite(val) or val < 0.0:
            raise ValueError(f"amplitude must be a non-negative finite number, got {amplitude}")
        self.state['amplitude'][ch] = val

    def set_offset(self, channel: int, offset: float) -> None:
        """
        Set the DC offset for a channel.

        Args:
            channel (int): Channel number (1-2)
            offset (float): DC offset in volts
        """
        ch = self._validate_channel(channel)
        if isinstance(offset, bool) or not isinstance(offset, Real):
            raise TypeError(f"offset must be a numeric value, got {type(offset).__name__}")
        val = float(offset)
        if not math.isfinite(val):
            raise ValueError(f"offset must be a finite number, got {offset}")
        self.state['offset'][ch] = val

    def set_polarity(self, channel: int, polarity: str) -> None:
        """
        Set the output polarity for a channel.

        Args:
            channel (int): Channel number (1-2)
            polarity (str): Polarity mode ('NORM' or 'INV')
        """
        ch = self._validate_channel(channel)
        if not isinstance(polarity, str):
            raise TypeError(f"polarity must be a string, got {type(polarity).__name__}")
        pol_upper = polarity.strip().upper()
        if pol_upper not in self.polarity:
            raise ValueError(f"Invalid polarity {polarity!r}. Must be one of {self.polarity}")
        self.state['polarity'][ch] = pol_upper

    def configure_waveform(
        self,
        channel: int,
        waveform: str,
        frequency: Optional[float] = None,
        amplitude: Optional[float] = None,
        offset: Optional[float] = None,
        load_impedance: Optional[float] = None,
        polarity: Optional[str] = None,
        user_func: Optional[Any] = None,
    ) -> None:
        """
        Configure the waveform settings for a channel atomically.

        Args:
            channel (int): Channel number (1-2)
            waveform (str): Waveform type
            frequency (float, optional): Frequency in hertz
            amplitude (float, optional): Amplitude in volts
            offset (float, optional): DC offset in volts
            load_impedance (float, optional): Load impedance in ohms
            polarity (str, optional): Polarity mode ('NORM' or 'INV')
            user_func (callable, optional): User-defined function for 'USER' waveform
        """
        ch = self._validate_channel(channel)

        # Validate waveform
        if not isinstance(waveform, str):
            raise TypeError(f"waveform must be a string, got {type(waveform).__name__}")
        wf_upper = waveform.strip().upper()
        if wf_upper not in self.waveform:
            raise ValueError(f"Invalid waveform {waveform!r}. Must be one of {self.waveform}")

        freq_val: Optional[float] = None
        if frequency is not None:
            if isinstance(frequency, bool) or not isinstance(frequency, Real):
                raise TypeError(f"frequency must be a numeric value, got {type(frequency).__name__}")
            freq_val = float(frequency)
            if not math.isfinite(freq_val) or freq_val <= 0.0:
                raise ValueError(f"frequency must be positive finite, got {frequency}")

        amp_val: Optional[float] = None
        if amplitude is not None:
            if isinstance(amplitude, bool) or not isinstance(amplitude, Real):
                raise TypeError(f"amplitude must be a numeric value, got {type(amplitude).__name__}")
            amp_val = float(amplitude)
            if not math.isfinite(amp_val) or amp_val < 0.0:
                raise ValueError(f"amplitude must be a non-negative finite number, got {amplitude}")

        off_val: Optional[float] = None
        if offset is not None:
            if isinstance(offset, bool) or not isinstance(offset, Real):
                raise TypeError(f"offset must be a numeric value, got {type(offset).__name__}")
            off_val = float(offset)
            if not math.isfinite(off_val):
                raise ValueError(f"offset must be a finite number, got {offset}")

        load_val: Optional[float] = None
        if load_impedance is not None:
            if isinstance(load_impedance, bool) or not isinstance(load_impedance, Real):
                raise TypeError(f"load_impedance must be a numeric value, got {type(load_impedance).__name__}")
            load_val = float(load_impedance)
            if not math.isfinite(load_val) or load_val <= 0.0:
                raise ValueError(f"load_impedance must be positive finite, got {load_impedance}")

        pol_val: Optional[str] = None
        if polarity is not None:
            if not isinstance(polarity, str):
                raise TypeError(f"polarity must be a string, got {type(polarity).__name__}")
            pol_val = polarity.strip().upper()
            if pol_val not in self.polarity:
                raise ValueError(f"Invalid polarity {polarity!r}. Must be one of {self.polarity}")

        # All validated - mutate state
        self.state['waveform'][ch] = wf_upper
        if freq_val is not None:
            self.state['frequency'][ch] = freq_val
        if amp_val is not None:
            self.state['amplitude'][ch] = amp_val
        if off_val is not None:
            self.state['offset'][ch] = off_val
        if load_val is not None:
            self.state['load_impedance'][ch] = load_val
        if pol_val is not None:
            self.state['polarity'][ch] = pol_val
        if wf_upper == 'USER' and user_func is not None:
            warn_for_large_simulation_input(
                user_func,
                label="virtual AWG user waveform",
            )
            self.state['arb_waveform'][ch] = np.array(user_func)

    def set_square_duty_cycle(self, channel: int, duty_cycle: float) -> None:
        """
        Set the duty cycle for square waves.

        Args:
            channel (int): Channel number (1-2)
            duty_cycle (float): Duty cycle in percent
        """
        ch = self._validate_channel(channel)
        if isinstance(duty_cycle, bool) or not isinstance(duty_cycle, Real):
            raise TypeError(f"duty_cycle must be a numeric value, got {type(duty_cycle).__name__}")
        val = float(duty_cycle)
        if not math.isfinite(val) or val < 0.0 or val > 100.0:
            raise ValueError(f"duty_cycle must be in [0.0, 100.0], got {duty_cycle}")
        self.state['duty_cycle'][ch] = val

    def set_ramp_symmetry(self, channel: int, symmetry: float) -> None:
        """
        Set the symmetry for ramp waves.

        Args:
            channel (int): Channel number (1-2)
            symmetry (float): Symmetry in percent
        """
        ch = self._validate_channel(channel)
        if isinstance(symmetry, bool) or not isinstance(symmetry, Real):
            raise TypeError(f"symmetry must be a numeric value, got {type(symmetry).__name__}")
        val = float(symmetry)
        if not math.isfinite(val) or val < 0.0 or val > 100.0:
            raise ValueError(f"symmetry must be in [0.0, 100.0], got {symmetry}")
        self.state['symmetry'][ch] = val

    def set_pulse_width(self, channel: int, pulse_width: float) -> None:
        """
        Set the pulse width for pulse waves.

        Args:
            channel (int): Channel number (1-2)
            pulse_width (float): Pulse width in seconds
        """
        ch = self._validate_channel(channel)
        if isinstance(pulse_width, bool) or not isinstance(pulse_width, Real):
            raise TypeError(f"pulse_width must be a numeric value, got {type(pulse_width).__name__}")
        val = float(pulse_width)
        if not math.isfinite(val) or val <= 0.0:
            raise ValueError(f"pulse_width must be a positive finite number, got {pulse_width}")
        self.state['pulse_width'][ch] = val

    def set_pulse_rise_time(self, channel: int, rise_time: Any) -> None:
        """Set pulse rise time (not simulated)."""
        self._validate_channel(channel)

    def set_pulse_fall_time(self, channel: int, fall_time: Any) -> None:
        """Set pulse fall time (not simulated)."""
        self._validate_channel(channel)

    def set_pulse_duty_cycle(self, channel: int, duty_cycle: float) -> None:
        """
        Set the duty cycle for pulse waves.

        Args:
            channel (int): Channel number (1-2)
            duty_cycle (float): Duty cycle in percent
        """
        ch = self._validate_channel(channel)
        if isinstance(duty_cycle, bool) or not isinstance(duty_cycle, Real):
            raise TypeError(f"duty_cycle must be a numeric value, got {type(duty_cycle).__name__}")
        val = float(duty_cycle)
        if not math.isfinite(val) or val < 0.0 or val > 100.0:
            raise ValueError(f"duty_cycle must be in [0.0, 100.0], got {duty_cycle}")
        self.state['duty_cycle'][ch] = val

    def set_pulse_delay(self, channel: int, pulse_delay: float) -> None:
        """
        Set the pulse delay for pulse waves.

        Args:
            channel (int): Channel number (1-2)
            pulse_delay (float): Pulse delay in seconds
        """
        ch = self._validate_channel(channel)
        if isinstance(pulse_delay, bool) or not isinstance(pulse_delay, Real):
            raise TypeError(f"pulse_delay must be a numeric value, got {type(pulse_delay).__name__}")
        val = float(pulse_delay)
        if not math.isfinite(val) or val < 0.0:
            raise ValueError(f"pulse_delay must be a non-negative finite number, got {pulse_delay}")
        self.state['pulse_delay'][ch] = val

    def configure_pulse(
        self,
        channel: int,
        pulse_width: Optional[float] = None,
        pulse_delay: Optional[float] = None,
        rise_time: Optional[Any] = None,
        fall_time: Optional[Any] = None,
        duty_cycle: Optional[float] = None,
    ) -> None:
        """
        Configure the pulse settings for a channel atomically.

        Args:
            channel (int): Channel number (1-2)
            pulse_width (float, optional): Pulse width in seconds
            pulse_delay (float, optional): Pulse delay in seconds
            rise_time (float, optional): Rise time in seconds
            fall_time (float, optional): Fall time in seconds
            duty_cycle (float, optional): Duty cycle in percent
        """
        ch = self._validate_channel(channel)

        pw_val: Optional[float] = None
        if pulse_width is not None:
            if isinstance(pulse_width, bool) or not isinstance(pulse_width, Real):
                raise TypeError(f"pulse_width must be a numeric value, got {type(pulse_width).__name__}")
            pw_val = float(pulse_width)
            if not math.isfinite(pw_val) or pw_val <= 0.0:
                raise ValueError(f"pulse_width must be a positive finite number, got {pulse_width}")

        pd_val: Optional[float] = None
        if pulse_delay is not None:
            if isinstance(pulse_delay, bool) or not isinstance(pulse_delay, Real):
                raise TypeError(f"pulse_delay must be a numeric value, got {type(pulse_delay).__name__}")
            pd_val = float(pulse_delay)
            if not math.isfinite(pd_val) or pd_val < 0.0:
                raise ValueError(f"pulse_delay must be a non-negative finite number, got {pulse_delay}")

        dc_val: Optional[float] = None
        if duty_cycle is not None:
            if isinstance(duty_cycle, bool) or not isinstance(duty_cycle, Real):
                raise TypeError(f"duty_cycle must be a numeric value, got {type(duty_cycle).__name__}")
            dc_val = float(duty_cycle)
            if not math.isfinite(dc_val) or dc_val < 0.0 or dc_val > 100.0:
                raise ValueError(f"duty_cycle must be in [0.0, 100.0], got {duty_cycle}")

        # All validated - mutate state
        self.state['waveform'][ch] = 'PULS'
        if pw_val is not None:
            self.state['pulse_width'][ch] = pw_val
        if pd_val is not None:
            self.state['pulse_delay'][ch] = pd_val
        if dc_val is not None:
            self.state['duty_cycle'][ch] = dc_val

    def create_arb_waveform(self, channel: int, name: str, data: Sequence[float]) -> None:
        """
        Create and store an arbitrary waveform.

        Args:
            channel (int): Channel number (1-2)
            name (str): Name of the waveform
            data (list or np.array): Waveform data points
        """
        ch = self._validate_channel(channel)
        if data is None:
            raise ValueError("data must not be None")
        warn_for_large_simulation_input(data, label="virtual AWG arbitrary waveform")
        data_arr = np.asarray(data, dtype=float)
        if data_arr.size == 0:
            raise ValueError("data array must not be empty")
        if data_arr.ndim != 1 or data_arr.size < 2 or not np.isfinite(data_arr).all():
            raise ValueError("data must be a finite one-dimensional waveform with at least two points")
        max_abs = np.max(np.abs(data_arr))
        if max_abs > 0:
            voltage_data = data_arr / max_abs
        else:
            voltage_data = data_arr

        self.state['arb_waveform'][ch] = voltage_data

    def set_arb_waveform(self, channel: int, name: str) -> None:
        """
        Set the arbitrary waveform for a channel.

        Args:
            channel (int): Channel number (1-2)
            name (str): Name of the waveform
        """
        ch = self._validate_channel(channel)
        self.state['waveform'][ch] = 'USER'

    def set_trigger_source(self, channel: int, trigger_source: str) -> None:
        """
        Set the trigger source for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_source (str): Trigger source ('IMM', 'INT', 'EXT', 'MAN')
        """
        ch = self._validate_channel(channel)
        if not isinstance(trigger_source, str):
            raise TypeError(f"trigger_source must be a string, got {type(trigger_source).__name__}")
        ts_upper = trigger_source.strip().upper()
        if ts_upper not in self.trigger_source:
            raise ValueError(f"Invalid trigger_source {trigger_source!r}. Must be one of {self.trigger_source}")
        self.state['trigger_source'][ch] = ts_upper

    def set_trigger_level(self, channel: int, trigger_level: float) -> None:
        """
        Set the trigger level for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_level (float): Trigger level voltage
        """
        ch = self._validate_channel(channel)
        if isinstance(trigger_level, bool) or not isinstance(trigger_level, Real):
            raise TypeError(f"trigger_level must be a numeric value, got {type(trigger_level).__name__}")
        val = float(trigger_level)
        if not math.isfinite(val):
            raise ValueError(f"trigger_level must be finite, got {trigger_level}")
        self.state['trigger_level'][ch] = val

    def set_trigger_slope(self, channel: int, trigger_slope: str) -> None:
        """
        Set the trigger slope for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_slope (str): Trigger slope ('POS', 'NEG', 'EITH')
        """
        ch = self._validate_channel(channel)
        if not isinstance(trigger_slope, str):
            raise TypeError(f"trigger_slope must be a string, got {type(trigger_slope).__name__}")
        ts_upper = trigger_slope.strip().upper()
        if ts_upper not in self.trigger_slope:
            raise ValueError(f"Invalid trigger_slope {trigger_slope!r}. Must be one of {self.trigger_slope}")
        self.state['trigger_slope'][ch] = ts_upper

    def set_trigger_mode(self, channel: int, trigger_mode: str) -> None:
        """
        Set the trigger mode for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_mode (str): Trigger mode ('EDGE' or 'LEV')
        """
        ch = self._validate_channel(channel)
        if not isinstance(trigger_mode, str):
            raise TypeError(f"trigger_mode must be a string, got {type(trigger_mode).__name__}")
        tm_upper = trigger_mode.strip().upper()
        if tm_upper not in self.trigger_mode:
            raise ValueError(f"Invalid trigger_mode {trigger_mode!r}. Must be one of {self.trigger_mode}")
        self.state['trigger_mode'][ch] = tm_upper

    def set_acquisition_channel(self, channel: int) -> None:
        """
        Set the acquisition channel (1-2).

        Args:
            channel (int): Channel number (1-2)
        """
        ch = self._validate_channel(channel)
        self.state['acquisition_channel'] = ch

    def configure_trigger(
        self,
        channel: int,
        trigger_source: Optional[str] = None,
        trigger_level: Optional[float] = None,
        trigger_slope: Optional[str] = None,
        trigger_mode: Optional[str] = None,
    ) -> None:
        """
        Configure the trigger settings for a channel atomically.

        Args:
            channel (int): Channel number (1-2)
            trigger_source (str, optional): Trigger source
            trigger_level (float, optional): Trigger level voltage
            trigger_slope (str, optional): Trigger slope
            trigger_mode (str, optional): Trigger mode
        """
        ch = self._validate_channel(channel)

        src_val: Optional[str] = None
        if trigger_source is not None:
            if not isinstance(trigger_source, str):
                raise TypeError(f"trigger_source must be a string, got {type(trigger_source).__name__}")
            src_val = trigger_source.strip().upper()
            if src_val not in self.trigger_source:
                raise ValueError(f"Invalid trigger_source {trigger_source!r}. Must be one of {self.trigger_source}")

        lvl_val: Optional[float] = None
        if trigger_level is not None:
            if isinstance(trigger_level, bool) or not isinstance(trigger_level, Real):
                raise TypeError(f"trigger_level must be a numeric value, got {type(trigger_level).__name__}")
            lvl_val = float(trigger_level)
            if not math.isfinite(lvl_val):
                raise ValueError(f"trigger_level must be finite, got {trigger_level}")

        slp_val: Optional[str] = None
        if trigger_slope is not None:
            if not isinstance(trigger_slope, str):
                raise TypeError(f"trigger_slope must be a string, got {type(trigger_slope).__name__}")
            slp_val = trigger_slope.strip().upper()
            if slp_val not in self.trigger_slope:
                raise ValueError(f"Invalid trigger_slope {trigger_slope!r}. Must be one of {self.trigger_slope}")

        mod_val: Optional[str] = None
        if trigger_mode is not None:
            if not isinstance(trigger_mode, str):
                raise TypeError(f"trigger_mode must be a string, got {type(trigger_mode).__name__}")
            mod_val = trigger_mode.strip().upper()
            if mod_val not in self.trigger_mode:
                raise ValueError(f"Invalid trigger_mode {trigger_mode!r}. Must be one of {self.trigger_mode}")

        # All validated - mutate state
        if src_val is not None:
            self.state['trigger_source'][ch] = src_val
        if lvl_val is not None:
            self.state['trigger_level'][ch] = lvl_val
        if slp_val is not None:
            self.state['trigger_slope'][ch] = slp_val
        if mod_val is not None:
            self.state['trigger_mode'][ch] = mod_val

    # ------------------------------------------------------------------------
    # Waveform Generation
    # ------------------------------------------------------------------------

    def get_waveform(self, channel: int) -> np.ndarray:
        """
        Generate a synthetic waveform based on current settings.

        Args:
            channel (int): Channel number (1-2)

        Returns:
            np.ndarray: Array of waveform data points
        """
        ch = self._validate_channel(channel)
        wf = self.state['waveform'][ch]
        amp = self.state['amplitude'][ch]
        freq = self.state['frequency'][ch]
        offset = self.state['offset'][ch]
        points = self._simulation_points
        warn_for_large_simulation_points(points, label="virtual AWG waveform")
        t = np.linspace(0, 1, points)

        if wf.upper() == 'SIN':
            v = amp * np.sin(2 * np.pi * t) + offset
        elif wf.upper() == 'SQU':
            v = amp * np.sign(np.sin(2 * np.pi * t)) + offset
        elif wf.upper() == 'RAMP':
            v = amp * (2 * (t % 1) - 1) + offset
        elif wf.upper() == 'PULS':
            duty = self.state['duty_cycle'][ch] / 100.0
            v = amp * (np.mod(t, 1) < duty) + offset
        elif wf.upper() == 'NOIS':
            v = amp * self._rng.standard_normal(points) + offset
        elif wf.upper() == 'DC':
            v = np.ones(points) * offset
        elif wf.upper() == 'USER' and self.state['arb_waveform'][ch] is not None:
            data = self.state['arb_waveform'][ch]
            v = np.interp(np.linspace(0, len(data) - 1, points), np.arange(len(data)), data)
            v = v * amp + offset
        else:
            v = np.zeros(points)

        if self.state["polarity"][ch] == "INV":
            v = 2 * offset - v
        return v

    # ------------------------------------------------------------------------
    # Reset Ownership
    # ------------------------------------------------------------------------

    def reset(self) -> None:
        """
        Reset virtual AWG to default factory state with all outputs OFF.

        Preserves injected waveform hook. Setup-owned state (external material models,
        timebase, clocks, RNG) is owned by the test fixture / VirtualBench and not reset.
        """
        self._rng.bit_generator.state = deepcopy(self._initial_rng_state)
        self.state = {
            'output': {ch: False for ch in self.channel},
            'waveform': {ch: 'SIN' for ch in self.channel},
            'frequency': {ch: 1e3 for ch in self.channel},
            'amplitude': {ch: 1.0 for ch in self.channel},
            'offset': {ch: 0.0 for ch in self.channel},
            'source_impedance': {ch: 5 for ch in self.channel},
            'load_impedance': {ch: 50.0 for ch in self.channel},
            'polarity': {ch: 'NORM' for ch in self.channel},
            'duty_cycle': {ch: 50.0 for ch in self.channel},
            'symmetry': {ch: 50.0 for ch in self.channel},
            'pulse_width': {ch: 1e-6 for ch in self.channel},
            'pulse_delay': {ch: 0.0 for ch in self.channel},
            'trigger_source': {ch: 'IMM' for ch in self.channel},
            'trigger_level': {ch: 0.0 for ch in self.channel},
            'trigger_slope': {ch: 'POS' for ch in self.channel},
            'trigger_mode': {ch: 'EDGE' for ch in self.channel},
            'arb_waveform': {ch: None for ch in self.channel},
            'acquisition_channel': 1,
        }

    def clear(self) -> None:
        """Clear error queues and status registers (no-op in virtual driver)."""
        pass
