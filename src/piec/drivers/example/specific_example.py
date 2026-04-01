"""
This is an example template for creating a new instrument driver.
It explains the purpose of each key component required for the autodetect system to work.
"""

# --- 1. IMPORT STATEMENTS ---
# Import the base classes that your driver will inherit from.
# - The first import should be the generic instrument type (e.g., Awg, Oscilloscope).
# - The second import should be the communication protocol class (e.g., Scpi).
# Using relative imports (like . and ..) is standard practice within a package.
import numpy as np
from .example import Example
from ..scpi import Scpi #in the case that the instrument is SCPI based, includes all base SCPI commands

"""
below is shown an example of an awg, like the 81150a from Keysight
"""
# --- 2. CLASS DEFINITION ---
# The class name should be descriptive and unique.
# It must inherit from the appropriate base classes imported above.
class AnnotatedAwgDriver(Example, Scpi):
    """
    This is the main docstring for your driver.
    Explain what the instrument is and any key details about the driver's implementation.
    """

    # --- 3. AUTODETECT IDENTIFIER ---
    # This is the most important attribute for the autodetect system.
    # The `autodetect_instrument` function will look for this class attribute.
    # It must contain a unique string (or list of strings) that is present
    # in the instrument's response to the '*IDN?' query.

    # Option A: For a driver that controls a single instrument model.
    # AUTODETECT_ID = "81150A"

    # Option B: For a driver that can control multiple, similar models.
    # The autodetect system is smart enough to handle a list of strings.
    AUTODETECT_ID = ["81150A", "33522B", "33622A"]


    # --- 4. INSTRUMENT PARAMETERS (Optional but Recommended) ---
    # It is good practice to define the known limits and capabilities of the
    # instrument as class attributes. This provides a quick reference and can
    # be used for input validation.
    channel = [1, 2]
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
    frequency_range = (1e-6, 240e6) # in Hz
    amplitude_range = (0, 5)      # in Volts peak-to-peak


    # --- 5. INITIALIZATION METHOD ---
    # The __init__ method is what gets called when a connection is successful.
    # For SCPI instruments, it's standard to call the parent class's __init__
    # which handles the VISA connection setup.


    # --- 6. DRIVER-SPECIFIC METHODS ---
    # These are the methods that implement the instrument's specific commands.
    # They should use the `self.instrument` object (created by the parent class)
    # to send and receive data.
    #THESE ARE TAKEN FROM THE PARENT CLASS AND WE OVERRIED THEM HERE WITH ACTUAL IMPLEMENTATIONS

    def output(self, channel, on=True):
        """
        Turns the output of a specified channel on or off.
        """
        # Validate the channel input against the class attribute.
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        if on:
            self.instrument.write(f":OUTP{channel} ON")
        else:
            self.instrument.write(f":OUTP{channel} OFF")

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency for the specified channel.
        """
        # Validate the frequency input against the class attribute.
        if not (self.frequency_range[0] <= frequency <= self.frequency_range[1]):
            raise ValueError(f"Frequency out of range. Must be between {self.frequency_range}")

        self.instrument.write(f":FREQ{channel} {frequency}")

    # ... Add as many other methods as needed to control the instrument ...
