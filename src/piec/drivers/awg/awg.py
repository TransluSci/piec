"""
An awg (arbitrary waveform generator) is defined as an instrument that has the typical features on expects an awg to have
"""
from ..instrument import Instrument, optional

class Awg(Instrument):
    # Class attributes for parameter restrictions
    channel = [1]
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
    frequency = {'func': {'SIN': (None, None), 'SQU': (None, None), 'RAMP': (None, None), 'PULS': (None, None), 'NOIS': None, 'DC': None, 'USER': (None, None)}}
    amplitude = (None, None)
    offset = amplitude #typically same as amplitude
    load_impedance = None #substandard
    source_impedance = None #substandard
    polarity = ['NORM', 'INV']
    duty_cycle = (0.0, 100.0)
    symmetry = (0.0, 100.0)
    pulse_width = (None, None)
    pulse_delay = pulse_width #typically the same
    rise_time = None
    fall_time = rise_time #typically the same
    trigger_source = ['IMM', "INT", "EXT", "MAN"] #[IMM (immediate), INT2 (internal), EXT (external), MAN (software trigger)]
    trigger_slope = ['POS', 'NEG', 'EITH'] #[POS (positive), NEG (negative), EITH (either)]
    trigger_mode = ["EDGE", "LEV"] #[EDGE (edge), LEV (level)]
    slew_rate = None #useful information about the instrument, but need not be implemented
    arb_data_range = (None, None) #range of data points for arbitrary waveform generation

    # --- Optional feature class attributes ---
    burst_mode = ['TRIG', 'GAT', 'INF']
    burst_count = (None, None)
    phase = (0, 360)
    sweep_mode = ['LIN', 'LOG']
    modulation_type = ['AM', 'FM', 'PM', 'FSK', 'PWM']


    """
    All awgs must be able to generate an arbitrary waveform and output it to the selected channel
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
        Resets the instrument to its default / factory state with all
        outputs **OFF**.

        After reset the instrument should be in a safe, idle state with no
        signal being generated.

        For SCPI instruments this sends the ``*RST`` command and re-initialises
        the internal state tracker.  Non-SCPI drivers should override this to
        perform an equivalent reset via their native protocol, ensuring all
        outputs are disabled if the native reset does not do so.
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

    # --- AWG-Specific Methods ---

    def output(self, channel, on=True):
        """
        All awgs must be able to output something, so therefore we need a method to turn the output on for the selected channel.
        args:
            channel (int): The channel to output on
            on (bool): Whether to turn the output on or off
        """

    #Standard waveform configuration functions
    def set_waveform(self, channel, waveform):
        """
        Sets the built_in waveform to be generated on the selected channel.
        args:
            channel (int): The channel to set the waveform on
            waveform (str): The waveform to be generated
        """

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency of the waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the frequency on
            frequency (float): The frequency of the waveform in Hz
        """

    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude of the waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the amplitude on
            amplitude (float): The amplitude of the waveform in volts (usually Vpp but use instrument default)
        """

    def set_offset(self, channel, offset):
        """
        Sets the offset of the waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the offset on
            offset (float): The offset of the waveform in volts
        """

    def set_load_impedance(self, channel, load_impedance):
        """
        Sets the load impedance of the waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the load impedance on
            load_impedance (float): The load impedance of the waveform in ohms
        """

    def set_polarity(self, channel, polarity):
        """
        Sets the polarity of the waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the polarity on
            polarity (str): The polarity of the waveform
        """

    def configure_waveform(self, channel, waveform, frequency=None, amplitude=None, offset=None, load_impedance=None, polarity=None):
        """
        Configures the waveform to be generated on the selected channel. Calls the set_waveform, set_frequency, set_amplitude, set_offset, set_load_impedance, and set_polarity functions to configure the waveform
        args:
            channel (int): The channel to configure the waveform on
            waveform (str): The waveform to be generated
            frequency (float): The frequency of the waveform in Hz
            amplitude (float): The amplitude of the waveform in volts
            offset (float): The offset of the waveform in volts
            load_impedance (float): The load impedance of the waveform in ohms
            polarity (str): The polarity of the waveform
        """
        self.set_waveform(channel, waveform)
        if frequency is not None:
            self.set_frequency(channel, frequency)
        if amplitude is not None:
            self.set_amplitude(channel, amplitude)
        if offset is not None:
            self.set_offset(channel, offset)
        if load_impedance is not None:
            self.set_load_impedance(channel, load_impedance)
        if polarity is not None:
            self.set_polarity(channel, polarity)

    #functions that are specific to waveform types

    #First for square waves
    def set_square_duty_cycle(self, channel, duty_cycle):
        """
        Sets the duty cycle of the square wave to be generated on the selected channel
        args:
            channel (int): The channel to set the duty cycle on
            duty_cycle (float): The duty cycle of the waveform as a percentage (0-100)
        """

    #Now for triangular/ramp waves
    def set_ramp_symmetry(self, channel, symmetry):
        """
        Sets the symmetry of the ramp waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the symmetry on
            symmetry (float): The symmetry of the waveform as a percentage (0-100)
        """

    #Now for pulses
    def set_pulse_width(self, channel, pulse_width):
        """
        Sets the pulse width of the waveform to be generated on the selected channel
        Useful for pulses
        args:
            channel (int): The channel to set the pulse width on
            pulse_width (float): The pulse width of the waveform in seconds
        """

    def set_pulse_rise_time(self, channel, rise_time):
        """
        Sets the rise time of the waveform to be generated on the selected channel
        Useful for pulses
        args:
            channel (int): The channel to set the rise time on
            rise_time (float): The rise time of the waveform in seconds
        """

    def set_pulse_fall_time(self, channel, fall_time):
        """
        Sets the fall time of the waveform to be generated on the selected channel
        Useful for pulses
        args:
            channel (int): The channel to set the fall time on
            fall_time (float): The fall time of the waveform in seconds
        """

    def set_pulse_duty_cycle(self, channel, duty_cycle):
        """
        Sets the duty cycle of the pulse to be generated on the selected channel
        args:
            channel (int): The channel to set the duty cycle on
            duty_cycle (float): The duty cycle of the pulse as a percentage (0-100)
        """

    def set_pulse_delay(self, channel, pulse_delay):
        """
        Set the pulse delay on the configured channel in units of seconds. Delay is the time between the start of the 
        pulse period and the start of the leading edge of the pulse.
        args:
            channel (int): The channel to set the delay on
            pulse_delay (float): The delay of the waveform in seconds
        """

    def configure_pulse(self, channel, pulse_width=None, pulse_delay=None, rise_time=None, fall_time=None, duty_cycle=None):
        """
        Configures the pulse waveform on the selected channel. Calls the set_pulse_width, set_pulse_delay, set_pulse_rise_time, set_pulse_duty_cycle and set_pulse_fall_time functions to configure the pulse waveform
        args:
            channel (int): The channel to configure the pulse waveform on
            pulse_width (float): The pulse width of the waveform in seconds
            pulse_delay (float): The delay of the pulse waveform in seconds
            rise_time (float): The rise time of the waveform in seconds
            fall_time (float): The fall time of the waveform in seconds
            duty_cycle (float): The duty cycle of the pulse as a percentage (0-100)
        """
        self.set_waveform(channel, "PULS") # Ensure waveform is pulse
        if pulse_delay is not None:
            self.set_pulse_delay(channel, pulse_delay)
        if pulse_width is not None:
            self.set_pulse_width(channel, pulse_width)
        if rise_time is not None:
            self.set_pulse_rise_time(channel, rise_time)
        if fall_time is not None:
            self.set_pulse_fall_time(channel, fall_time)
        if duty_cycle is not None:
            self.set_pulse_duty_cycle(channel, duty_cycle)

    #Now we move to the arb functions
    def create_arb_waveform(self, channel, name, data):
        """
        Creates an arbitrary waveform to be generated on the selected channel and saves to instrument memory if applicable. If no name is given, it will be generated with a default name. Typically
        corresponding to the volatile memory of the instrument. In the case where the given name already exists, it will prompt the user to overwrite or not.
        For implementing the data transfer, use the most documented version from the manual.
        args:
            channel (int): The channel to create the arbitrary waveform on
            name (str): The name of the arbitrary waveform
            data (list or ndarray): The data points of the arbitrary waveform
        """

    def set_arb_waveform(self, channel, name):
        """
        Sets the arbitrary waveform to be generated on the selected channel
        args:
            channel (int): The channel to set the arbitrary waveform on
            name (str): The name of the arbitrary waveform to be set
        """

    #trigger and sync functions
    def set_trigger_source(self, channel, trigger_source):
        """
        Sets the trigger source for the selected channel
        args:
            channel (int): The channel to set the trigger source on
            trigger_source (str): The trigger source, e.g., 'internal', 'external', 'manual'
        """

    def set_trigger_level(self, channel, trigger_level):
        """
        Sets the trigger level for the selected channel
        args:
            channel (int): The channel to set the trigger level on
            trigger_level (float): The trigger level in volts
        """

    def set_trigger_slope(self, channel, trigger_slope):
        """
        Sets the trigger slope for the selected channel
        args:
            channel (int): The channel to set the trigger slope on
            trigger_slope (str): The trigger slope, e.g., 'rising', 'falling'
        """

    def set_trigger_mode(self, channel, trigger_mode):
        """
        Sets the trigger mode for the selected channel (aka trigger type)
        args:
            channel (int): The channel to set the trigger mode on
            trigger_mode (str): The trigger mode, e.g., 'EDGE' 
        """
        
    def configure_trigger(self, channel, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None):
        """
        Configures the trigger for the selected channel. Calls the set_trigger_source, set_trigger_level, set_trigger_slope, and set_trigger_mode functions to configure the trigger
        args:
            channel (int): The channel to configure the trigger on
            trigger_source (str): The trigger source
            trigger_level (float): The trigger level in volts
            trigger_slope (str): The trigger slope
            trigger_mode (str): The trigger mode
        """
        if trigger_source is None:
            self.set_trigger_source(channel, trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(channel, trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(channel, trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(channel, trigger_mode) 

        def output_trigger(self):
            """
            Outputs the trigger signal for the awg. This is typically used to synchronize the output of the awg with other instruments or systems. Typically the same as manually triggering the awg from the front panel.
            """

    # --- Optional Features ---
    # These are features that not all AWGs support.
    # If a driver does not override these, they will gracefully skip.

    @optional
    def set_burst_mode(self, channel, burst_mode):
        """
        Sets the burst mode type.
        args:
            channel (int): The channel
            burst_mode (str): 'TRIG' (N-cycle on trigger), 'GAT' (gated), 'INF' (infinite)
        """

    @optional
    def set_burst_count(self, channel, burst_count):
        """
        Sets the number of waveform cycles per burst trigger.
        args:
            channel (int): The channel
            burst_count (int): Number of cycles per burst
        """

    @optional
    def configure_burst(self, channel, burst_mode=None, burst_count=None):
        """
        Configures burst mode. Calls set_burst_mode and set_burst_count.
        args:
            channel (int): The channel
            burst_mode (str): 'TRIG', 'GAT', or 'INF'
            burst_count (int): Number of cycles per burst
        """
        if burst_mode is not None:
            self.set_burst_mode(channel, burst_mode)
        if burst_count is not None:
            self.set_burst_count(channel, burst_count)

    @optional
    def set_phase(self, channel, phase):
        """
        Sets the phase offset of the waveform on the selected channel.
        args:
            channel (int): The channel
            phase (float): Phase offset in degrees (0-360)
        """

    @optional
    def set_sweep_mode(self, channel, sweep_mode):
        """
        Sets the sweep type (linear or logarithmic).
        args:
            channel (int): The channel
            sweep_mode (str): 'LIN' or 'LOG'
        """

    @optional
    def set_sweep_start_freq(self, channel, start_freq):
        """
        Sets the sweep start frequency.
        args:
            channel (int): The channel
            start_freq (float): Start frequency in Hz
        """

    @optional
    def set_sweep_stop_freq(self, channel, stop_freq):
        """
        Sets the sweep stop frequency.
        args:
            channel (int): The channel
            stop_freq (float): Stop frequency in Hz
        """

    @optional
    def set_sweep_time(self, channel, sweep_time):
        """
        Sets the sweep duration.
        args:
            channel (int): The channel
            sweep_time (float): Sweep time in seconds
        """

    @optional
    def configure_sweep(self, channel, sweep_mode=None, start_freq=None, stop_freq=None, sweep_time=None):
        """
        Configures frequency sweep. Calls individual set_ methods.
        args:
            channel (int): The channel
            sweep_mode (str): 'LIN' or 'LOG'
            start_freq (float): Start frequency in Hz
            stop_freq (float): Stop frequency in Hz
            sweep_time (float): Sweep time in seconds
        """
        if sweep_mode is not None:
            self.set_sweep_mode(channel, sweep_mode)
        if start_freq is not None:
            self.set_sweep_start_freq(channel, start_freq)
        if stop_freq is not None:
            self.set_sweep_stop_freq(channel, stop_freq)
        if sweep_time is not None:
            self.set_sweep_time(channel, sweep_time)

    @optional
    def set_modulation_type(self, channel, mod_type):
        """
        Sets the modulation type.
        args:
            channel (int): The channel
            mod_type (str): 'AM', 'FM', 'PM', 'FSK', 'PWM'
        """

    @optional
    def set_modulation_depth(self, channel, depth):
        """
        Sets the modulation depth/deviation.
        args:
            channel (int): The channel
            depth (float): Modulation depth (AM: 0-100%, FM: deviation in Hz)
        """

    @optional
    def set_modulation_frequency(self, channel, frequency):
        """
        Sets the modulating signal frequency.
        args:
            channel (int): The channel
            frequency (float): Internal modulation frequency in Hz
        """

    @optional
    def set_modulation_source(self, channel, source):
        """
        Sets the modulation source.
        args:
            channel (int): The channel
            source (str): 'INT' or 'EXT'
        """

    @optional
    def configure_modulation(self, channel, mod_type=None, depth=None, frequency=None, source=None):
        """
        Configures modulation. Calls individual set_ methods.
        args:
            channel (int): The channel
            mod_type (str): 'AM', 'FM', 'PM', 'FSK', 'PWM'
            depth (float): Modulation depth/deviation
            frequency (float): Modulation frequency in Hz
            source (str): 'INT' or 'EXT'
        """
        if mod_type is not None:
            self.set_modulation_type(channel, mod_type)
        if depth is not None:
            self.set_modulation_depth(channel, depth)
        if frequency is not None:
            self.set_modulation_frequency(channel, frequency)
        if source is not None:
            self.set_modulation_source(channel, source)
