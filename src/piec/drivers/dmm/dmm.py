"""
This is an outline for a generic Digital Multimeter (DMM) driver class.

A DMM is defined as an instrument that performs measurements but does not
source power. It inherits from a base Instrument class.
"""

from ..instrument import Instrument, optional

class DMM(Instrument):
    """
    Parent class for Digital Multimeters.
    
    This class defines the minimum required methods and attributes for a DMM driver.
    It focuses solely on measurement functions.
    """
    # --- Class Attributes ---    
    channel = [1]
    sense_func = ['VOLT', 'CURR', 'RES']
    coupling = ['DC', 'AC']
    sense_mode = ['2W', '4W']
    sense_range = (None, None)
    
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

        After reset the DMM should be in a safe, idle measurement state
        (typically DC Volts, autorange).

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

    # --- DMM-Specific Methods ---


    def set_sense_function(self, sense_func):
        """
        Sets the base measurement function of the DMM.
        Args:
            sense_func (str): The measurement function, e.g., 'VOLT', 'CURR', 'RES'.
        """
        raise NotImplementedError

    def set_measurement_coupling(self, coupling):
        """
        Sets the signal coupling for the current function (e.g., AC or DC).
        This is typically applicable only for VOLT and CURR functions.
        Args:
            coupling (str): The signal coupling, e.g., 'AC' or 'DC'.
        """
        raise NotImplementedError

    def set_sense_mode(self, sense_mode):
        """
        Sets the wiring configuration for sensing.
        Args:
            sense_mode (str): The wire mode, '2W' (2-wire) or '4W' (4-wire).
        """
        raise NotImplementedError

    def set_sense_range(self, range_val=None, auto=True):
        """
        Sets the measurement range for the current sense function.
        Args:
            range_val (float, optional): The fixed range value. Defaults to None.
            auto (bool): If True, enables autorange. If False, a fixed range is used.
        """
        raise NotImplementedError

    def set_integration_time(self, nplc=1):
        """
        Sets the measurement integration time in Number of Power Line Cycles (NPLC).
        A higher NPLC value increases accuracy and noise rejection but slows down
        the measurement speed.
        Args:
            nplc (float): The number of power line cycles (e.g., 0.1, 1, 10, 100).
        """
        raise NotImplementedError

    # --- Measurement (Read) Methods ---

    def quick_read(self):
        """
        Triggers and returns a single measurement for the currently configured function.
        Returns:
            (float): The measured value.
        """
        raise NotImplementedError

    def get_voltage(self, ac=False):
        """
        Convenience function to measure and return a voltage reading.
        Args:
            ac (bool): If True, configures for an AC voltage measurement. 
                         If False (default), configures for DC voltage.
        Returns:
            (float): The measured voltage in Volts.
        """
        raise NotImplementedError

    def get_current(self, ac=False):
        """
        Convenience function to measure and return a current reading.
        Args:
            ac (bool): If True, configures for an AC current measurement. 
                         If False (default), configures for DC current.
        Returns:
            (float): The measured current in Amps.
        """
        raise NotImplementedError

    def get_resistance(self, four_wire=False):
        """
        Convenience function to measure and return a resistance reading.
        Args:
            four_wire (bool): If True, performs a 4-wire measurement. 
                              If False (default), performs a 2-wire measurement.
        Returns:
            (float): The measured resistance in Ohms.
        """
        raise NotImplementedError

    # --- Optional Features ---
    # These are features that not all DMMs support.
    # If a driver does not override these, they will gracefully skip.

    @optional
    def get_frequency(self):
        """
        Returns the measured frequency in Hz.
        returns:
            (float): The measured frequency in Hz.
        """

    @optional
    def get_temperature(self, probe_type='TC'):
        """
        Returns the measured temperature.
        Some DMMs support multiple temperature sensor types (thermocouple, RTD,
        thermistor) — the probe_type tells the instrument which conversion to use.
        args:
            probe_type (str): 'TC' (thermocouple), 'RTD', 'THER' (thermistor)
        returns:
            (float): Temperature in configured unit (typically °C)
        """

    @optional
    def get_capacitance(self):
        """
        Returns the measured capacitance in Farads.
        returns:
            (float): The measured capacitance in Farads.
        """

