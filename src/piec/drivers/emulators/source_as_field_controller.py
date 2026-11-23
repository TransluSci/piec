"""Adapt the setpoint of an already configured voltage or current source."""
import math

from ..field_controller import FieldController


class SourceAsFieldController(FieldController):
    """Apply a linear gain in Oe/A or Oe/V to a single-value source setter."""

    AI_STATUS = 'generated'
    HARDWARE_TESTED = False

    def __init__(self, source, set_output, gain, output_limits, offset=0.0):
        self._initialize_common_state(check_params=False, verbose=False)
        low, high = output_limits
        if not all(map(math.isfinite, (gain, offset, low, high))) or gain == 0 or low >= high:
            raise ValueError('Require finite increasing output limits, nonzero gain and finite offset')
        self.source, self._write_output = source, set_output
        self.gain, self.offset = gain, offset
        self.field = tuple(sorted((gain * low + offset, gain * high + offset)))
        if not all(map(math.isfinite, self.field)):
            raise ValueError('Calibrated field limits must be finite')
        if not self.field[0] <= 0 <= self.field[1]:
            raise ValueError('Configured source output limits must include calibrated zero field')

    def idn(self):
        return f'Calibrated field source ({self.source.idn()})'

    def set_field(self, field):
        if not self.field[0] <= field <= self.field[1]:
            raise ValueError('Requested field exceeds configured source output limits')
        self._write_output((field - self.offset) / self.gain)
