"""
This is an outline for what the puler.py file should be like.

A pulser is defined as an instrument that has the typical features one expects a pulser to have
"""
from ..instrument import Instrument
class Pulser(Instrument):
    # Initializer / Instance attributes
    """
    All Pulsers must be able to generate a pulse. Assumes 50Ohm output impedance unless otherwise specified.
    """
    channel = [1]
    period = (None, None)
    frequency = (None, None)
    width = (None, None)
    delay = (None, None)
    rise_time = (None, None)
    fall_time = (None, None)
    high_level = (None, None)
    low_level = (None, None)
    offset = (None, None)
    trigger_source = ['INT', 'EXT', 'MAN']
    trigger_mode = ['CONT', 'BURS']
    burst_count = (None, None)
    polarity = ['NORM', 'INV']

    #Core Pulse timing parameters
    def set_period(self, channel, period):
        """
        Sets the period of the pulse
        """
    def set_frequency(self, channel, frequency):
        """
        Sets the frequency of the pulse, This can simply call set_pulse_period with conversion or vice versa
        """
    def set_width(self, channel, width):
        """
        Sets the width of the pulse
        """
    def set_delay(self, channel, delay):
        """
        Sets the delay before the pulse starts
        """
    def set_rise_time(self, channel, rise_time):
        """
        Sets the rise time of the pulse
        """
    def set_fall_time(self, channel, fall_time):
        """
        Sets the fall time of the pulse
        """
    #Core Pulse level parameters
    def set_high_level(self, channel, high_level):
        """
        Sets the high level of the pulse
        """
    def set_low_level(self, channel, low_level):
        """
        Sets the low level of the pulse
        """
    def set_offset(self, channel, offset):
        """
        Sets the offset of the pulse
        """
    #Core Pulse output parameters
    def output(self, channel, on=True):
        """
        Turns the pulse output on or off for the specified channel
        """
    #triggering and mode
    def set_trigger_source(self, source):
        """
        Sets the trigger source for the pulse (e.g., internal, external, manual)
        """
    def set_trigger_mode(self, mode):
        """
        Sets the trigger mode for the pulse (e.g., single, continuous, burst)
        """
    #if the pulser has a burst mode
    def set_burst_count(self, channel, count):
        """
        Sets the number of pulses in a burst
        """
    #basic pulse output functions
    def set_polarity(self, channel, polarity):
        """
        Sets the polarity of the pulse output (e.g., normal, inverted)
        """
    