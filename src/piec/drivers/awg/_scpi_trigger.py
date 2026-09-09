"""Validated trigger commands shared by the Agilent and Rigol AWGs.

Command sources and model restrictions: docs/awg_trigger_support.md.
This mixin does not enable outputs, select waveforms, or enable burst/sweep.
"""

import math
from numbers import Integral, Real

from ..instrument import AutoCheckMeta


class ScpiTriggerMixin(metaclass=AutoCheckMeta):
    """Trigger configuration with validation before the first configuration write."""

    trigger_source = ['IMM', 'INT', 'EXT', 'MAN', 'BUS']
    trigger_slope = ['POS', 'NEG']
    trigger_mode = ['EDGE', 'LEV']
    _trigger_level_range = None
    _trigger_source_map = {'imm': 'IMM', 'int': 'IMM', 'ext': 'EXT', 'man': 'BUS', 'bus': 'BUS'}

    def _validate_trigger_channel(self, channel):
        if isinstance(channel, bool) or not isinstance(channel, Integral) or channel not in self.channel:
            raise ValueError(f"channel must be one of {self.channel}")

    @staticmethod
    def _trigger_function(value):
        if not isinstance(value, str) or value.lower() not in ('burst', 'sweep'):
            raise ValueError("trigger_function must be 'burst' or 'sweep'")
        return value.lower()

    @staticmethod
    def _trigger_choice(value, choices, name):
        if not isinstance(value, str) or value.lower() not in choices:
            raise ValueError(f"{name} must be one of {tuple(choices)}")
        return choices[value.lower()]

    def _trigger_prefix(self, channel, trigger_function):
        return f'TRIG{channel}'

    def _burst_prefix(self, channel):
        return f'SOUR{channel}:BURS'

    def _trigger_command(self, channel, name, value, trigger_function):
        self._validate_trigger_channel(channel)
        function = self._trigger_function(trigger_function)
        prefix = self._trigger_prefix(channel, function)
        if name == 'source':
            token = self._trigger_choice(value, self._trigger_source_map, 'trigger_source')
            return f'{prefix}:SOUR {token}'
        if name == 'slope':
            token = self._trigger_choice(value, {'pos': 'POS', 'neg': 'NEG'}, 'trigger_slope')
            return f'{prefix}:SLOP {token}'
        if name == 'mode':
            if function != 'burst':
                raise ValueError('trigger_mode selects a burst mode; omit it for sweep triggering')
            token = self._trigger_choice(value, {'edge': 'TRIG', 'lev': 'GAT'}, 'trigger_mode')
            return f'{self._burst_prefix(channel)}:MODE {token}'
        if self._trigger_level_range is None:
            raise NotImplementedError(f'{type(self).__name__} has no implemented adjustable trigger level')
        low, high = self._trigger_level_range
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'trigger_level must be finite and between {low} and {high} V')
        return f'{prefix}:LEV {value}'

    def configure_trigger(self, channel, trigger_source=None, trigger_level=None,
                          trigger_slope=None, trigger_mode=None, *, trigger_function='burst'):
        """Configure an already selected burst/sweep; do not enable it or the output.

        MAN/BUS select software triggering. EDGE/LEV select triggered/gated burst.
        None leaves the corresponding setting alone. All arguments are validated
        before any writes; transport errors still propagate and may leave partial
        hardware configuration. DG4000 needs an explicit trigger_function='sweep'
        for sweep configuration (the other models share a trigger subsystem).
        """
        self._validate_trigger_channel(channel)
        self._trigger_function(trigger_function)
        commands = [self._trigger_command(channel, name, value, trigger_function)
                    for name, value in [('source', trigger_source), ('level', trigger_level),
                                        ('slope', trigger_slope), ('mode', trigger_mode)]
                    if value is not None]
        for command in commands:
            self.instrument.write(command)

    def set_trigger_source(self, channel, trigger_source, *, trigger_function='burst'):
        """Select immediate/internal, external, or manual/software (MAN/BUS) source."""
        self.instrument.write(self._trigger_command(channel, 'source', trigger_source, trigger_function))

    def set_trigger_slope(self, channel, trigger_slope, *, trigger_function='burst'):
        """Select the rising/falling external trigger edge; not gate polarity."""
        self.instrument.write(self._trigger_command(channel, 'slope', trigger_slope, trigger_function))

    def set_trigger_mode(self, channel, trigger_mode):
        """Select triggered (EDGE) or externally gated (LEV) burst without enabling it."""
        self.instrument.write(self._trigger_command(channel, 'mode', trigger_mode, 'burst'))

    def set_trigger_level(self, channel, trigger_level):
        """Set the instrument's trigger level in volts, where implemented.

        On 33500, this is the output trigger level (0.9--3.8 V); the external
        input threshold is half that value, as specified by the manufacturer.
        """
        self.instrument.write(self._trigger_command(channel, 'level', trigger_level, 'burst'))

    def output_trigger(self):
        """Send one bus trigger to all channels armed for software triggering.

        Burst/sweep and the desired output channels must already be enabled.
        This neither changes the source nor enables a physical trigger connector.
        """
        self.instrument.write('*TRG')
