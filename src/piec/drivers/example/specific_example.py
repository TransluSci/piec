"""
This is an example template for creating a new instrument driver.
It explains the purpose of each key component required for the autodetect system to work.
"""

# --- 1. IMPORT STATEMENTS ---
# Import the base classes that your driver will inherit from.
# - The first import should be the generic instrument type (e.g., Awg, Oscilloscope).
# - The second import should be the communication protocol class (e.g., Scpi).
# Using relative imports (like . and ..) is standard practice within a package.
from .example import Example
from ..scpi import Scpi #in the case that the instrument is SCPI based, includes all base SCPI commands

# --- 2. CLASS DEFINITION ---
# The class name should be descriptive and unique.
# It must inherit from the appropriate base classes imported above.
class AnnotatedGenericDriver(Example, Scpi):
    """
    This is an example of a specific instrument driver that implements 
    the generic Example interface. 
    It represents a hypothetical "Generic Instrument Model X".
    """

    # --- 3. AUTODETECT IDENTIFIER ---
    # Substring expected in the *IDN? response.
    AUTODETECT_ID = "GENERIC_MODEL_X"


    # --- 4. INSTRUMENT CAPABILITIES & LIMITS ---
    # Define the specific boundaries for this model.
    channel = [1, 2]
    voltage = (0.0, 5.0)  # This model only goes up to 5V
    mode = ['CONSTANT', 'SWEEP']
    
    # Example of a dependent attribute:
    # The valid range of 'current' depends on the value of 'mode'.
    current = {
        'mode': {
            'CONSTANT': (0.0, 0.5), # 500mA limit in constant mode
            'SWEEP': (0.0, 0.2)     # 200mA limit in sweep mode
        }
    }


    # --- 5. INITIALIZATION ---
    # The __init__ method is where you perform any setup required immediately 
    # after the connection is established.
    def __init__(self, *args, **kwargs):
        # 1. ALWAYS call super().__init__ first to establish the VISA connection.
        super().__init__(*args, **kwargs)

        # 2. SYNC INITIAL STATE
        # Upon connection, all tracked attributes ('self._current_') are None by default.
        # Professional drivers can query the hardware now so that initial 
        # dependent parameter checks or model-specific logic don't fail.
        try:
            # Hypothetical query for the current mode
            initial_mode = self.instrument.query(":SOUR:MODE?")
            self._current_mode = initial_mode.strip().lower()
        except Exception:
            # Fallback if query fails (e.g. in virtual mode)
            self._current_mode = 'CONSTANT'

        # 3. COMMAND MAPPING
        # If an instrument uses integer codes (0, 1, 2) instead of strings 
        # ('CONSTANT', 'SWEEP'), it is best practice to create a mapping 
        # dict here to avoid hard-coding numbers in your methods.
        self._mode_map = {'constant': 0, 'sweep': 1}


    # --- 6. IMPLEMENTED METHODS ---
    # We override the parent methods with actual SCPI writes.

    def output(self, channel, on=True):
        """
        Turns the output on or off for the specified channel.
        """
        state = 'ON' if on else 'OFF'
        self.instrument.write(f":OUTP{channel} {state}")

    def set_mode(self, channel, mode):
        """
        Sets the operating mode using a mapping to integer codes.
        Note: The framework handles input validation against self.mode automatically.
        """
        code = self._mode_map[mode.lower()]
        self.instrument.write(f":SOUR{channel}:MODE {code}")

    def set_voltage(self, channel, voltage):
        """
        Sets the voltage.
        Note: The framework handles input validation against self.voltage automatically.
        """
        # --- EXAMPLE: USING STATE-TRACKING ---
        # The framework automatically maintains 'self._current_<property>' 
        # (e.g., self._current_mode) after any successful set_ call.
        # You can use these to decide which hardware command to send.
        if self._current_mode == 'sweep':
             # Maybe sweep mode requires a special "limit" command instead of "volt"
             self.instrument.write(f":SOUR{channel}:VOLT:LIM {voltage}")
        else:
             self.instrument.write(f":SOUR{channel}:VOLT {voltage}")

    def set_current(self, channel, current):
        """
        Sets the current limit.
        Note: The framework handles input validation against self.current automatically.
        """
        self.instrument.write(f":SOUR{channel}:CURR {current}")

    def quick_read(self, channel):
        """
        Queries the instrument for a measurement.
        """
        response = self.instrument.query(f":MEAS{channel}:VOLT?")
        return float(response)

    # --- 7. CHILD-SPECIFIC (AUTO-OPTIONAL) METHODS ---
    # Methods not in the parent class are automatically optional.

    def read_error_log(self):
        """
        Example of a model-specific method. 
        Other instruments without this method will skip it gracefully.
        """
        return self.instrument.query(":SYST:ERR?")

    # ... Add as many other methods as needed to control the instrument ...
