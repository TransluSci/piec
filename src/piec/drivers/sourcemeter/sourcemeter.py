"""
This is an outline for what the sourcemeter.py file should be like.

A sourcemeter is defined as an instrument that has the typical features one expects a sourcemeter to have
"""
from ..instrument import Instrument

class Sourcemeter(Instrument):
    # Class attributes defining the "contract" for any implementing class.
    # All sourcemeters must support these basic functions and modes.
    channel = [1]
    source_func = ['VOLT', 'CURR']
    sense_func = ['VOLT', 'CURR', 'RES']
    sense_mode = ['2W', '4W']
    voltage = (None, None)
    current = (None, None)
    voltage_compliance = (None, None)
    current_compliance = (None, None)
    
    """
    Here we define the MINIMUM required methods for a sourcemeter.
    """

    # --- Core Instrument State Control ---

    def output(self, channel=1, on=True):
        """
        Turns the main output of the sourcemeter on or off.
        args:
            channel (int): The channel to output. Default is 1.
            on (bool): True to enable the output, False to disable it.
        """

    def set_source_function(self, channel=1, source_func=None):
        """
        Sets the primary function of the source.
        args:
            channel (int): The channel to source. Default is 1.
            source_func (str): The source function, e.g., 'VOLT' or 'CURR'.
        """

    def set_sense_function(self, channel=1, sense_func=None):
        """
        Sets the measurement (sense) function.
        args:
            channel (int): The channel to sense. Default is 1.
            sense_func (str): The measurement function, e.g., 'VOLT', 'CURR', or 'RES'.
        """
        
    def set_sense_mode(self, channel=1, sense_mode=None):
        """
        Sets the wiring configuration for sensing.
        args:
            channel (int): The channel to sense. Default is 1.
            sens_mode (str): The sense mode, '2W' (2-wire) or '4W' (4-wire).
        """

    # --- Source Configuration Methods ---
    
    def set_source_voltage(self, channel=1, voltage=None):
        """
        Sets the output level when in voltage source mode.
        args:
            channel (int): The channel to source. Default is 1.
            voltage (float): The desired output voltage in Volts.
        """
    
    def set_source_current(self, channel=1, current=None):
        """
        Sets the output level when in current source mode.
        args:
            channel (int): The channel to source. Default is 1.
            current (float): The desired output current in Amps.
        """

    def set_voltage_compliance(self, channel=1, voltage_compliance=None):
        """
        Sets the voltage limit (compliance) when in current source mode.
        args:
            channel (int): The channel to source limit. Default is 1.
            voltage_compliance (float): The maximum voltage allowed in Volts.
        """
    
    def set_current_compliance(self, channel=1, current_compliance=None):
        """
        Sets the current limit (compliance) when in voltage source mode.
        args:
            channel (int): The channel to source limit. Default is 1.
            current_compliance (float): The maximum current allowed in Amps.
        """
    
    # --- Convenience Configuration Methods ---

    def configure_voltage_source(self, channel=1, voltage=0.0, current_compliance=1.05):
        """
        Configures the sourcemeter to source voltage with a specified compliance current.
        args:
            channel (int): The channel to configure. Default is 1.
            voltage (float): The voltage to source in Volts.
            current_compliance (float): The current compliance limit in Amps.
        """
        self.set_source_function(channel=channel, source_func='VOLT')
        self.set_source_voltage(channel=channel, voltage=voltage)
        self.set_current_compliance(channel=channel, current_compliance=current_compliance)

    def configure_current_source(self, channel=1, current=0.0, voltage_compliance=210):
        """
        Configures the sourcemeter to source current with a specified compliance voltage.
        args:
            channel (int): The channel to configure. Default is 1.
            current (float): The current to source in Amps.
            voltage_compliance (float): The voltage compliance limit in Volts.
        """
        self.set_source_function(channel=channel, source_func='CURR')
        self.set_source_current(channel=channel, current=current)
        self.set_voltage_compliance(channel=channel, voltage_compliance=voltage_compliance)

    # --- Measurement (Read) Methods ---

    def quick_read(self, channel=1):
        """
        Quickly returns the value for the currently configured sense function or whatever is on the screen.
        args:
            channel (int): The channel to read from. Default is 1.
        returns:
            (float): The measured value (Volts, Amps, or Ohms).
        """

    def get_voltage(self, channel=1):
        """
        Convenience function to specifically measure and return the voltage.
        args:
            channel (int): The channel to read from. Default is 1.
        returns:
            (float): The measured voltage in Volts.
        """

    def get_current(self, channel=1):
        """
        Convenience function to specifically measure and return the current.
        args:
            channel (int): The channel to read from. Default is 1.
        returns:
            (float): The measured current in Amps.
        """

