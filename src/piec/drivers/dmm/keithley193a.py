"""
This file contains the driver for the Keithley 193A Digital Multimeter.
Integrated from z_old/keithley193a/core.py.
"""
import re
import time
import pyvisa
from .dmm import DMM

class Keithley193a(DMM):
    """
    Driver for the Keithley 193A Digital Multimeter.
    
    This instrument uses a non-SCPI command set (Device Dependent Commands).
    """
    AUTODETECT_ID = ["Keithley 193A", "NDCV"]
    
    def __init__(self, address, **kwargs):
        """
        Initializes the Keithley 193A driver.
        """
        super().__init__(address, **kwargs)

    def idn(self):
        """
        Queries the instrument identity. Since 193A doesn't support *IDN?,
        we attempt a measurement to verify connectivity.
        """
        start_time = time.time()
        try:
            # Attempt to read a value to confirm it's responsive
            self.instrument.write("F0X") # Set to DCV to be sure
            time.sleep(0.1)
            # The old logic used a loop and read_voltage. 
            # We'll use get_voltage() here.
            while time.time() - start_time < 5:
                try:
                    val = self.get_voltage()
                    if val is not None:
                        return f"Keithley 193A Digital Multimeter at {self.instrument.resource_name}"
                except:
                    time.sleep(0.5)
            
            return "Not connected (Timeout)"
        except pyvisa.errors.VisaIOError:
            return "Not connected (VisaIOError)"

    def get_voltage(self, ac=False):
        """
        Reads the voltage from the DMM.
        Args:
            ac (bool): If True, measures AC voltage. Otherwise DC.
        """
        # F0 = DCV, F1 = ACV. 193A commands usually end with 'X' to execute.
        cmd = "F1X" if ac else "F0X"
        self.instrument.write(cmd)
        
        # In the old code, it used query('MEAS:VOLT:DC?')
        # If that worked for the user, I'll keep it as a fallback or primary
        # but 193A usually responds to just 'X' or even nothing if in talk-only.
        # Let's try to match the old core.py logic which used query('MEAS:VOLT:DC?')
        try:
            raw_val = self.instrument.query('MEAS:VOLT:DC?')
            return float(self._extract_number(raw_val))
        except:
            # Fallback to direct read if query fails
            raw_val = self.instrument.read()
            return float(self._extract_number(raw_val))

    def _extract_number(self, input_string):
        """Helper to extract numbers from instrument response strings."""
        match = re.search(r'[+-]?\d+\.\d+E[+-]?\d+', input_string)
        if match:
            return match.group(0)
        # Try a simpler float match if scientific notation fails
        match = re.search(r'[+-]?\d+\.?\d*', input_string)
        if match:
            return match.group(0)
        return None

    # Implement other DMM required methods with placeholders if not supported
    def set_sense_function(self, sense_func):
        if sense_func.upper() == 'VOLT':
            self.instrument.write("F0X")
        elif sense_func.upper() == 'CURR':
            self.instrument.write("F2X") # 193A: F2 is DCA
        elif sense_func.upper() == 'RES':
            self.instrument.write("F3X") # 193A: F3 is OHMS
        else:
            raise ValueError(f"Function {sense_func} not supported by 193A")

    def quick_read(self):
        return self.get_voltage()

    def set_measurement_coupling(self, coupling):
        if coupling.upper() == 'AC':
            self.instrument.write("F1X")
        else:
            self.instrument.write("F0X")

    def set_sense_mode(self, sense_mode):
        # 193A has specific commands for 2W/4W ohms etc.
        pass

    def set_sense_range(self, range_val=None, auto=True):
        if auto:
            self.instrument.write("R0X")
        else:
            # Nominal ranges would need mapping
            pass
