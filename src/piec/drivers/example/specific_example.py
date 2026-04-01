"""
This is an example template for creating a new instrument driver.
It explains the purpose of each key component required for the autodetect system to work.
"""

# --- 1. IMPORT STATEMENTS ---
# Import the base classes that your driver will inherit from.
# - The first import should be the generic instrument type (e.g., Awg, Oscilloscope).
# - The second import should be (if applicable) convenience classes (e.g., Scpi).
# Using relative imports (like . and ..) is standard practice within a package.
from .example import Example
from ..scpi import Scpi #in the case that the instrument is SCPI based, includes all base SCPI commands

# --- 2. CLASS DEFINITION ---
# The class name should be descriptive and unique (typically the model of the instrument).
# It must inherit from the appropriate base classes imported above.
class SpecificExample(Example, Scpi):
    """
    This is an example of a specific instrument driver that implements 
    the generic Example interface. 
    It represents a hypothetical "Generic Instrument Model X".
    """

    # --- 3. AUTODETECT IDENTIFIER ---
    AUTODETECT_ID = "GENERIC_MODEL_X"


    # --- 4. INSTRUMENT CAPABILITIES & LIMITS ---
    # Define the specific boundaries for this model.
    channel = [1, 2]
    mode = ['CONSTANT', 'SWEEP']
    voltage = (0.0, 5.0) 
    
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
        super().__init__(*args, **kwargs)

        # 1. SYNC INITIAL STATE
        # Upon connection, all tracked attributes ('self._current_') are None by default.
        # Professional drivers can query the hardware now so that initial 
        # dependent parameter checks or model-specific logic don't fail.
        try:
            # Hypothetical query for the current mode
            initial_mode = self.instrument.query(":SOUR:MODE?")
            self._current_mode = initial_mode.strip().lower()
        except Exception:
            self._current_mode = 'CONSTANT'

        # 2. COMMAND MAPPING
        # If an instrument uses integer codes (0, 1, 2) instead of strings 
        # ('CONSTANT', 'SWEEP'), it is best practice to create a mapping 
        # dict here to avoid hard-coding numbers in your methods.
        self._mode_map = {'constant': 0, 'sweep': 1}


    # --- 6. IMPLEMENTED METHODS ---

    def set_voltage(self, channel, voltage):
        """
        Sets the voltage.
        """
        self.instrument.write(f":SOUR{channel}:VOLT {voltage}")

    def set_mode(self, channel, mode):
        """
        Sets the operating mode.
        """
        code = self._mode_map[mode.lower()]
        self.instrument.write(f":SOUR{channel}:MODE {code}")

    def configure_instrument(self, channel, voltage=None, mode=None):
        """
        Wrapper example. Calls parent logic or implements specific wrapping.
        """
        super().configure_instrument(channel, voltage=voltage, mode=mode)

    def get_voltage(self, channel):
        """
        Retrieves a single scalar measurement.
        """
        response = self.instrument.query(f":MEAS{channel}:VOLT?")
        return float(response)

    # --- 7. CHILD-SPECIFIC (AUTO-OPTIONAL) METHODS ---
    # Methods not in the parent class are automatically optional.

    def read_waveform(self, channel):
        """
        Retrieves formatted waveform data (pandas.DataFrame).
        """
        # Example: Query the hardware for a comma-separated list of points
        response = self.instrument.query(f":WAV:DATA? {channel}")
        data = [float(x) for x in response.split(',')]
        return pd.DataFrame({'Voltage': data})

    # Note: 'set_optional' from the Example interface is NOT implemented here 
    # to demonstrate that Level 3 drivers can choose to ignore @optional stubs.

    def quick_read(self, channel):
        """
        A specific convenience function.
        """
        # Example: Query the hardware cursor value
        return float(self.instrument.query(":MEAS:CURS?"))
