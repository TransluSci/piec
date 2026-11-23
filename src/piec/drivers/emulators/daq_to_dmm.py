"""Expose one DAQ input as a voltage-only PIEC DMM."""
from ..dmm.dmm import DMM


class DaqAsDMM(DMM):
    sense_func = ['VOLT']
    coupling = ['DC']

    def __init__(self, daq_instance, ai_channel):
        self._initialize_common_state(check_params=False, verbose=False)
        if ai_channel not in daq_instance.ai_channel:
            raise ValueError(f'Unavailable analog input: {ai_channel}')
        self.daq = daq_instance
        self.ai_channel = ai_channel

    def idn(self):
        return f'DAQ voltage reader AI{self.ai_channel} ({self.daq.idn()})'

    def get_voltage(self, ac=False):
        if ac:
            raise NotImplementedError('DAQ adapter supports DC voltage only')
        return self.daq.read_AI(ai_channel=self.ai_channel)

    def quick_read(self):
        return self.get_voltage()

    def initialize(self):
        """No reset: other adapters may share the same DAQ."""

    def close(self):
        """The owner, not a channel adapter, closes the DAQ."""

