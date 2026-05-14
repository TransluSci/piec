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

    # --- Default SCPI Command Skeletons ---
    # These provide the standard IEEE 488.2 / SCPI-99 command interface.
    # SCPI-compliant instruments will inherit real implementations from Scpi.
    # Non-SCPI instruments should override these with their own protocol.

    def idn(self):
        """
        Returns the identification string of the instrument.

        For SCPI instruments this sends the ``*IDN?`` query.
        Non-SCPI drivers should override this to return an equivalent
        identification string from their native protocol.

        Returns:
            str: Instrument identification string.
        """

    def reset(self):
        """
        Resets the instrument to its default / factory state.

        After reset the pulser should be in a safe, idle state with the
        output off and default parameters.

        For SCPI instruments this sends the ``*RST`` command and re-initialises
        the internal state tracker.  Non-SCPI drivers should override this to
        perform an equivalent reset via their native protocol.
        """

    def clear(self):
        """
        Clears the instrument's status registers and error queue.

        For SCPI instruments this sends the ``*CLS`` command.
        Non-SCPI drivers should override this to perform an equivalent
        status-clear operation.
        """

    def error(self):
        """
        Queries the instrument's error / event status register.

        For SCPI instruments this sends the ``*ESR?`` query.
        Non-SCPI drivers should override this to return error information
        from their native protocol.

        Returns:
            str: The error status or message from the instrument.
        """

    def wait(self):
        """
        Blocks until all pending instrument operations have completed.

        For SCPI instruments this sends the ``*WAI`` command.
        Non-SCPI drivers should override this with an equivalent
        synchronisation mechanism.
        """

    def self_test(self):
        """
        Runs the instrument's built-in self-test routine.

        For SCPI instruments this sends the ``*TST?`` query.
        The call may take tens of seconds; implementations should handle
        extended timeouts appropriately.

        Returns:
            str: Self-test result (typically ``'0'`` for pass).
        """

    def operation_complete(self):
        """
        Queries whether the last operation has finished.

        For SCPI instruments this sends the ``*OPC?`` query.
        Non-SCPI drivers should override this with their native
        polling/synchronisation command.

        Returns:
            str: ``'1'`` when the operation is complete.
        """

    def initialize(self):
        """
        Convenience method that resets and clears the instrument to bring it
        to a known good starting state.

        The default implementation simply calls :meth:`reset` followed by
        :meth:`clear`.  Override if additional initialisation steps are needed.
        """
        self.reset()
        self.clear()

    # --- Pulser-Specific Methods ---

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
    