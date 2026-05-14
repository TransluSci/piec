"""
A dc_callibrator (DC Calibrator) is defined as an instrument that has the typical features one expects a DC Calibrator to have.
This is a template class meant to be inherited by specific DC Calibrator drivers.
"""
from ..instrument import Instrument

class DCCalibrator(Instrument):
    """
    Base class for DC Calibrators.
    """
    # Class attributes for parameter restrictions
    channel = [1]
    voltage_range = (None, None)
    current_range = (None, None)
    source_functions = ['VOLT', 'CURR']

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
        Resets the instrument to a safe, known state with the output
        **disabled** (e.g., crowbar / short-circuit engaged).

        For SCPI instruments this sends the ``*RST`` command and re-initialises
        the internal state tracker.  Non-SCPI drivers should override this to
        perform an equivalent reset via their native protocol, ensuring the
        output is disabled if the native reset does not do so.
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

    # --- DC Calibrator-Specific Methods ---

    def output(self, on=True):
        """
        Turns the main output of the calibrator on or off.
        Usually, 'off' engages a 'crowbar' or short circuit at the output.
        args:
            on (bool): True to enable the output, False to disable it.
        """

    def set_output(self, value, mode="voltage", **kwargs):
        """
        Formats and sends a command to set the instrument's output voltage or current.
        args:
            value (float or int): The desired output value.
            mode (str): "voltage" or "current".
            **kwargs: Additional parameters for the specific instrument.
        """

    def set_voltage(self, voltage):
        """
        Convenience method to specifically set the output voltage.
        args:
            voltage (float): The desired output voltage in Volts.
        """

    def set_current(self, current):
        """
        Convenience method to specifically set the output current.
        args:
            current (float): The desired output current in Amps.
        """
