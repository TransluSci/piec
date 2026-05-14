"""
This is an outline for what the lockin.py file should be like.

A lockin is defined as an instrument that has the typical features one expects a lockin to have
"""
from ..instrument import Instrument
class Lockin(Instrument):
    # Initializer / Instance attributes
    channel = [1] 
    reference_source = None
    frequency = (None, None) 
    harmonic = None
    phase = (None, None) 
    input_configuration = None
    input_coupling = ["AC", "DC"]
    sensitivity = (None, None) 
    notch_filter = (None, None)
    time_constant = (None, None)
    filter_slope = (None, None)

    """
    All lockins must be able to lockin to a signal and measure it
    """

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

        After reset the lock-in should be in a safe, idle state with the
        internal oscillator at a safe default (typically low amplitude,
        low frequency) and all filters at factory settings.

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

    # --- Lock-In Specific Methods ---

    #configure the reference signal
    def set_amplitude(self, amplitude):
        """
        Sets the reference amplitude (oscillator voltage).

        args:
            amplitude (float): The amplitude of the internal oscillator in Volts.
        """

    def set_reference_source(self, reference_source):
        """
        Sets the reference source for the lockin. Typically this could be internal, external, or a specific channel

        args:
            reference_source (str): the source of the reference signal (e.g., "internal", "external", etc.)
        """
    
    #this is only if the lockin has a reference frequency, some lockins only have a reference source

    def set_reference_frequency(self, frequency):
        """
        Sets the reference frequency for the lockin if applicable (if internal reference)

        args:
            frequency (float): where unit is typically in Hz
        """
    def set_harmonic(self, harmonic):
        """
        Sets the harmonic for the lockin

        args:
            harmonic (int): the harmonic number to lock onto (e.g., 1, 2, 3, etc.)
        """
    def set_phase(self, phase):
        """
        Sets the phase for the lockin

        args:
            phase (float): the phase offset in degrees or radians
        """
    #signal input channel setup
    def set_input_configuration(self, configuration):
        """
        Sets the input configuration for the lockin (single ended, differential, etc.)

        args:
            configuration (str): the input configuration type
        """
    def set_input_coupling(self, coupling):
        """
        Sets the input coupling for the lockin (AC, DC, etc.)

        args:
            coupling (str): the input coupling type (e.g., "AC", "DC")
        """
    def set_sensitivity(self, sensitivity):
        """
        Sets the sensitivity for the lockin

        args:
            sensitivity (float): the sensitivity level for the lockin
        """
    def set_notch_filter(self, notch_filter):
        """
        Sets the notch filter for the lockin (if available)

        args:
            notch_filter (float): the frequency of the notch filter to be set
        """
    #demodulation and low-pass filter setup
    def set_time_constant(self, time_constant):
        """
        Sets the time constant for the lockin defines the cutoff frequency of the low-pass filter

        args:
            time_constant (float): the time constant value in seconds
        """
    def set_filter_slope(self, filter_slope):
        """
        Sets the filter slope for the lockin. Usually in dB/octave or dB/decade

        args:
            filter_slope (float): the slope of the filter in dB/octave or dB/decade
        """
    # --- Legacy Configuration Methods (Backward Compatibility) ---

    def configure_reference(self, voltage=None, frequency=None, source=None, trig=None, phase=None, harmonic=None):
        """
        Legacy method to configure the reference part of lockin.
        """
        if voltage is not None: self.set_amplitude(voltage)
        if frequency is not None: self.set_reference_frequency(frequency)
        if source is not None: self.set_reference_source(source)
        if phase is not None: self.set_phase(phase)
        if harmonic is not None: self.set_harmonic(harmonic)

    def configure_input(self, input_configuration=None, input_shield_ground=None, input_coupling=None, input_line_notch=None):
        """
        Legacy method to configure the input part of lockin.
        """
        if input_configuration is not None: self.set_input_configuration(input_configuration)
        if input_coupling is not None: self.set_input_coupling(input_coupling)
        if input_line_notch is not None: self.set_notch_filter(input_line_notch)

    def configure_gain_filters(self, sensitivity=None, reserve_mode=None, time_constant=None, lp_filter_slope=None, sync=None):
        """
        Legacy method to configure gain and filters.
        """
        if sensitivity is not None: self.set_sensitivity(sensitivity)
        if time_constant is not None: self.set_time_constant(time_constant)
        if lp_filter_slope is not None: self.set_filter_slope(lp_filter_slope)

    def get_X_Y(self):
        """Legacy alias for quick_read."""
        return self.quick_read()

    #data acquisition and output
    def quick_read(self):
        """
        Quick read function that returns the default data (X and Y typically)

        Returns:
            tuple: (X, Y) data from the lockin
        """

    def read_data(self):
        """
        Reads the data from the lockin, For a lockin this is typically X, Y, R and Theta

        Returns:
            dict: A dictionary containing the lockin data with keys 'X', 'Y', 'R', and 'Theta'
        """
    def get_X(self):
        """
        Reads the X data

        Returns:
            float: The X data from the lockin
        """
    def get_Y(self):
        """
        Reads the Y data
        Returns:
            float: The Y data from the lockin
        """
    def get_R(self):
        """
        Reads the R data
        Returns:
            float: The R (magnitude) data from the lockin
        """
    def get_theta(self):
        """
        Reads the Theta (phase)
        Returns:
            float: The Theta (phase) data from the lockin
        """
    #auto commands
    def auto_gain(self):
        """
        Automatically sets the gain (sensitivity) based on the input signal
        """
    def auto_phase(self):
        """
        Automatically sets the phase based on the input signal
        """
    
    
