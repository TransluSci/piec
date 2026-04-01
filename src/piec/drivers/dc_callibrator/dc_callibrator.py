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

    def idn(self):
        """
        Queries the instrument for its identification string.
        """

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

    def reset(self):
        """
        Resets the instrument to a safe, known state (e.g., crowbar output).
        """

    def error(self):
        """
        Queries the instrument for the current error status.
        """
