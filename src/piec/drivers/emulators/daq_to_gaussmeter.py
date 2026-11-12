"""Use a DAQ analog input to read a calibrated field monitor."""
import math

from ..gaussmeter.gaussmeter import Gaussmeter


class DaqAsGaussmeter(Gaussmeter):
    AI_STATUS = 'generated'
    HARDWARE_TESTED = False

    def __init__(self, daq_instance, ai_channel, gain=100.0, offset=0.0):
        self._initialize_common_state(check_params=False, verbose=False)
        if ai_channel not in daq_instance.ai_channel:
            raise ValueError(f'Unavailable analog input: {ai_channel}')
        if not math.isfinite(gain) or gain == 0 or not math.isfinite(offset):
            raise ValueError('Require finite nonzero gain and finite offset')
        self.daq, self.ai_channel = daq_instance, ai_channel
        self.gain, self.offset = gain, offset

    def idn(self):
        return f'DAQ gaussmeter AI{self.ai_channel} ({self.daq.idn()})'

    def field_from_voltage(self, voltage):
        """Convert a scalar or array of monitor voltages to field in Oe."""
        return self.gain * voltage + self.offset

    def get_field(self, channel=1):
        """Return the signed field in Oe on logical channel 1."""
        if channel not in self.channel:
            raise ValueError(f'Unavailable gaussmeter channel: {channel}')
        return float(self.field_from_voltage(self.daq.read_AI(ai_channel=self.ai_channel)))
