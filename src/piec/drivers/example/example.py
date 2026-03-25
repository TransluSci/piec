"""
An example instrument to show how things should be layed out
"""
from ..instrument import Instrument, optional

class Example(Instrument):
    # --- Class Attributes (Parameter Restrictions) ---
    # These define the valid boundaries for function arguments. 
    # The name of the attribute MUST match the name of the argument it validates.

    # 1. DISCRETE LIST (Limited Sets)
    # Use a list for arguments that accept only a specific set of values.
    # Example: limited_func = [1, 2, 3]
    channel = [1, 2]
    mode = ['CONSTANT', 'SWEEP']

    # 2. CONTINUOUS TUPLE (Ranges)
    # Use a (min, max) tuple for arguments that accept any value within a range.
    # Example: continuous_func = (0, 10)
    voltage = (0.0, 10.0) # Volts

    # 3. DEPENDENT DICTIONARY (Conditional)
    # Use a dictionary when the valid range depends on the value of ANOTHER argument.
    # The key is the name of the dependency.
    # Example: dependant_func = {'mode': {'constant': (0, 1), 'sweep': (0, 0.5)}}
    current = {
        'mode': {
            'CONSTANT': (0.0, 1.0), # limit is 1A in constant mode
            'SWEEP': (0.0, 0.5)     # limit is 0.5A in sweep mode
        }
    }

    # 4. OPTIONAL / NO-LIMIT ATTRIBUTES
    # If a parameter (like 'optional_param') belongs to an @optional function 
    # but has no generic boundaries, set it to None. This marks it as "known" 
    # to PIEC but skips automatic range validation.
    optional_param = None

    """
    Here we define the MINIMUM supported methods for a generic instrument.
    This serves as a template for Level 2 base classes.
    """

    # --- Core Control Methods ---

    @optional
    def reset(self):
        """
        Resets the instrument to a factory/default state.
        For SCPI instruments, this is typically handled by the Scpi convenience class (*RST).
        """

    @optional
    def clear(self):
        """
        Clears the instrument's status registers and error queue.
        For SCPI instruments, this is typically handled by the Scpi convenience class (*CLS).
        """

    def output(self, channel, on=True):
        """
        Sets the output state (on or off) for the selected channel.
        Args:
            channel (int): The channel number.
            on (bool): Whether to turn the output on (True) or off (False).
        """

    def set_mode(self, channel, mode):
        """
        Sets the operating mode of the instrument.
        Args:
            channel (int): The channel number.
            mode (str): The mode (e.g., 'CONSTANT', 'SWEEP').
        """

    def set_voltage(self, channel, voltage):
        """
        Sets the output voltage for the selected channel.
        Args:
            channel (int): The channel number.
            voltage (float): The voltage in Volts.
        """

    def set_current(self, channel, current):
        """
        Sets the output current limit for the selected channel.
        Args:
            channel (int): The channel number.
            current (float): The current in Amps.
        """

    def configure_instrument(self, channel, voltage=None, current=None, mode=None, on=True):
        """
        Configures multiple parameters of the instrument in one call.
        Wraps individual set_ methods.
        Args:
            channel (int): The channel number.
            voltage (float, optional): The voltage to set.
            current (float, optional): The current to set.
            mode (str, optional): The mode to set.
            on (bool, optional): The output state to set.
        """
        if mode is not None:
            self.set_mode(channel, mode)
        if voltage is not None:
            self.set_voltage(channel, voltage)
        if current is not None:
            self.set_current(channel, current)
        if on is not None:
            self.output(channel, on=on)

    # --- Measurement Methods ---

    def quick_read(self, channel):
        """
        Performs a quick reading from the specified channel.
        Args:
            channel (int): The channel number.
        Returns:
            float: The measured value (simulated or real).
        """

    @optional
    def set_optional(self, optional_param):
        """
        Example of an optional function. 
        Only instruments that explicitly override this will execute it.
        """
