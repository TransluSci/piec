"""
Virtual Pulser class for testing and simulation.
This module provides a software simulation of a Pulser device for development
and testing without physical hardware.
"""
from .pulser import Pulser
from ..virtual_instrument import VirtualInstrument


class VirtualPulser(VirtualInstrument, Pulser):
    """
    Virtual version of a Pulser device for simulation/testing.
    Stores state internally but produces no physical output.
    """

    # --- Class Attributes ---
    channel = [1, 2]
    period = (1e-9, 1000.0)
    frequency = (1e-3, 1e9)
    width = (1e-9, 1000.0)
    delay = (0.0, 1000.0)
    rise_time = (1e-9, 1.0)
    fall_time = (1e-9, 1.0)
    high_level = (-5.0, 5.0)
    low_level = (-5.0, 5.0)
    offset = (-5.0, 5.0)
    trigger_source = ['INT', 'EXT', 'MAN']
    trigger_mode = ['CONT', 'BURS']
    burst_count = (1, 1000000)
    polarity = ['NORM', 'INV']

    def __init__(self, address='VIRTUAL', **kwargs):
        """
        Initialize virtual pulser with default settings.

        Args:
            address (str): Virtual address (default: 'VIRTUAL').
            **kwargs: Additional arguments passed to parent classes.
        """
        VirtualInstrument.__init__(self, address=address)
        Pulser.__init__(self, address=address, **kwargs)

        # State tracked per channel
        self.state = {
            'output_on': {ch: False for ch in self.channel},
            'period': {ch: 1e-3 for ch in self.channel},
            'width': {ch: 1e-4 for ch in self.channel},
            'delay': {ch: 0.0 for ch in self.channel},
            'rise_time': {ch: 1e-9 for ch in self.channel},
            'fall_time': {ch: 1e-9 for ch in self.channel},
            'high_level': {ch: 1.0 for ch in self.channel},
            'low_level': {ch: 0.0 for ch in self.channel},
            'offset': {ch: 0.5 for ch in self.channel},
            'trigger_source': 'INT',
            'trigger_mode': 'CONT',
            'burst_count': {ch: 1 for ch in self.channel},
            'polarity': {ch: 'NORM' for ch in self.channel}
        }

    # --- SCPI-Equivalent Commands ---

    def idn(self):
        return "PIEC,Virtual_Pulser,s/n_virtual,ver1.0"

    def reset(self):
        self.__init__()

    def clear(self):
        pass

    def error(self):
        return "No errors."

    def wait(self):
        pass

    def self_test(self):
        return "0"

    def operation_complete(self):
        return "1"

    def initialize(self):
        self.reset()

    # --- Pulser-Specific Methods ---

    def set_period(self, channel, period):
        self.state['period'][channel] = period

    def set_frequency(self, channel, frequency):
        if frequency > 0:
            self.state['period'][channel] = 1.0 / frequency

    def set_width(self, channel, width):
        self.state['width'][channel] = width

    def set_delay(self, channel, delay):
        self.state['delay'][channel] = delay

    def set_rise_time(self, channel, rise_time):
        self.state['rise_time'][channel] = rise_time

    def set_fall_time(self, channel, fall_time):
        self.state['fall_time'][channel] = fall_time

    def set_high_level(self, channel, high_level):
        self.state['high_level'][channel] = high_level

    def set_low_level(self, channel, low_level):
        self.state['low_level'][channel] = low_level

    def set_offset(self, channel, offset):
        self.state['offset'][channel] = offset

    def output(self, channel, on=True):
        self.state['output_on'][channel] = on

    def set_trigger_source(self, source):
        self.state['trigger_source'] = source

    def set_trigger_mode(self, mode):
        self.state['trigger_mode'] = mode

    def set_burst_count(self, channel, count):
        self.state['burst_count'][channel] = count

    def set_polarity(self, channel, polarity):
        self.state['polarity'][channel] = polarity
