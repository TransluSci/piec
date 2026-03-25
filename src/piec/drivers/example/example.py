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
    Template for Level 2 base classes.
    Only includes a minimal set of example methods for each function type.
    """

    # --- 1. Set Methods (Single Action) ---

    def set_voltage(self, channel, voltage):
        """
        Sets the output voltage for the selected channel.
        Rule: Performs a SINGLE hardware write/action.
        """

    def set_mode(self, channel, mode):
        """
        Sets the operating mode (e.g., 'CONSTANT', 'SWEEP').
        """

    # --- 2. Configure Methods (Multiple Actions) ---

    def configure_instrument(self, channel, voltage=None, mode=None):
        """
        Wraps multiple set_ methods for convenience.
        """
        if mode is not None:
            self.set_mode(channel, mode)
        if voltage is not None:
            self.set_voltage(channel, voltage)

    # --- 3. Retrieval Methods (Get vs Read) ---

    def get_voltage(self, channel):
        """
        Retrieves a SINGLE, unformatted numeric value.
        """
    
    # --- 4. Convenience Methods ---
    def quick_read(self, channel):
        """
        A specific convenience function.
        Returns whatever data is fastest to retrieve or currently displayed 
        on the hardware (e.g., the value of a hardware cursor or average).
        """

    # --- 5. Optional Methods ---
    @optional
    def read_waveform(self, channel):
        """
        Retrieves complex or formatted data (e.g., pandas.DataFrame).
        The return format MUST be detailed in this docstring.
        """

    @optional
    def set_optional(self, optional_param):
        """
        Example of an @optional stub.
        """
