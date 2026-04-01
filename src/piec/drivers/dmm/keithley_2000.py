# This driver has not been tested yet
from .dmm import DMM
from ..scpi import Scpi

class Keithley2000(DMM, Scpi):
    """
    Driver for the Keithley 2000 Digital Multimeter.
    """
    
    AUTODETECT_ID = "MODEL 2000"
    
    channel = [1]
    
    sense_func = ['VOLT', 'CURR', 'RES', 'FRES', 'FREQ', 'PER', 'TEMP']
    
    coupling = ['DC', 'AC']
    
    sense_mode = ['2W', '4W']
    
    sense_range = (None, None)
    




    def set_sense_function(self, sense_func, coupling="DC", sense_mode="2W"):
        """
        Sets the measurement function.
        Mappings:
        VOLT + DC -> VOLT:DC
        VOLT + AC -> VOLT:AC
        CURR + DC -> CURR:DC
        CURR + AC -> CURR:AC
        RES + 2W -> RES
        RES + 4W -> FRES
        FREQ -> FREQ
        PER -> PER
        TEMP -> TEMP
        """
        cmd = ""
        sense_func = sense_func.upper()
        coupling = coupling.upper()
        sense_mode = sense_mode.upper()
        
        if sense_func == "VOLT":
            cmd = f"VOLT:{coupling}"
        elif sense_func == "CURR":
             cmd = f"CURR:{coupling}"
        elif sense_func == "RES":
            if sense_mode == "4W":
                cmd = "FRES"
            else:
                cmd = "RES"
        else:
            cmd = sense_func
            
        # Keithley 2000: :SENS:FUNC 'VOLT:DC' (string with quotes)
        self.instrument.write(f":SENS:FUNC '{cmd}'")
        self._current_sense_func = cmd

    def set_measurement_coupling(self, coupling):
        pass # Handle via function

    def set_sense_mode(self, sense_mode):
        pass # Handle via function

    def set_sense_range(self, range_val=None, auto=True):
        # :VOLT:DC:RANG <n> or :AUTO ON
        # Need current function
        func = self._current_sense_func if hasattr(self, '_current_sense_func') else "VOLT:DC"
             
        if auto:
            self.instrument.write(f":SENS:{func}:RANG:AUTO ON")
        else:
            if range_val is not None:
                self.instrument.write(f":SENS:{func}:RANG {range_val}")

    def set_integration_time(self, nplc=1):
        # :VOLT:DC:NPLC <n>
        # Valid for DCV, DCI, RES, FRES, TEMP
        func = self._current_sense_func if hasattr(self, '_current_sense_func') else "VOLT:DC"
        if "DC" in func or "RES" in func or "FRES" in func or "TEMP" in func:
             self.instrument.write(f":SENS:{func}:NPLC {nplc}")

    def quick_read(self):
        return float(self.instrument.query(":READ?"))

    def get_voltage(self, ac=False):
        mode = "AC" if ac else "DC"
        func = f"VOLT:{mode}"
        self.instrument.write(f":SENS:FUNC '{func}'")
        # Ensure we read immediately? Or just set func and read?
        # Keithley 2000 READ? triggers and returns.
        return float(self.instrument.query(":READ?"))

    def get_current(self, ac=False):
        mode = "AC" if ac else "DC"
        func = f"CURR:{mode}"
        self.instrument.write(f":SENS:FUNC '{func}'")
        return float(self.instrument.query(":READ?"))

    def get_resistance(self, four_wire=False):
        func = "FRES" if four_wire else "RES"
        self.instrument.write(f":SENS:FUNC '{func}'")
        return float(self.instrument.query(":READ?"))
