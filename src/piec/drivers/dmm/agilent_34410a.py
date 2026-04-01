# This driver has not been tested yet
from .dmm import DMM
from ..scpi import Scpi

class Agilent34410A(DMM, Scpi):
    """
    Driver for the Agilent 34410A Digital Multimeter.
    """
    
    AUTODETECT_ID = "34410A"
    
    channel = [1]
    
    sense_func = ['VOLT', 'CURR', 'RES', 'FRES', 'FREQ', 'PER', 'CAP', 'DIOD']
    
    # 34410A coupling is usually implicit in function (AC/DC)
    coupling = ['DC', 'AC']
    
    sense_mode = ['2W', '4W'] # Handled by RES vs FRES
    
    # Range depends on function (100mV to 1000V for DCV)
    sense_range = (None, None) 
    




    def set_sense_function(self, sense_func, coupling=None, sense_mode=None):
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
        CAP -> CAP
        DIOD -> DIOD
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
            cmd = sense_func # FREQ, PER, etc.
            
        self.instrument.write(f"CONF:{cmd}")
        self._current_sense_func = cmd # Store specific SCPI func for other methods

        
    def set_measurement_coupling(self, coupling):
        # Already handled in set_sense_function usually for 34410A, 
        # but if we are in VOLT mode, we might switch DC/AC.
        # This is tricky because 34410A uses CONF:VOLT:DC or CONF:VOLT:AC.
        # We need to know current primary function.
        # For now, let's rely on set_sense_function.
        pass

    def set_sense_mode(self, sense_mode):
        # 2W vs 4W
        # Only applicable if we are in Resistance mode.
        # If we are in RES, switch to FRES if 4W.
        # This requires tracking state which we might not have fully robustly here yet.
        pass

    def set_sense_range(self, range_val=None, auto=True):
        # Uses current function from memory or query?
        # Ideally we use the function we are in.
        # SCPI: [SENSe:]<Function>:RANGe <range> or :AUTO ON/OFF
        # We need to know the function string (e.g. VOLT:DC).
        # We can query it: FUNC?
        func = self.instrument.query("FUNC?") # returns "VOLT:DC" etc usually
        func = func.strip().strip('"')
        
        if auto:
            self.instrument.write(f"{func}:RANGe:AUTO ON")
        else:
            if range_val is not None:
                self.instrument.write(f"{func}:RANGe {range_val}")

    def set_integration_time(self, nplc=1):
        # [SENSe:]<Function>:NPLC <nplc>
        # Valid for DCV, DCI, RES, FRES
        func = self.instrument.query("FUNC?")
        func = func.strip().strip('"')
        
        # Check if function supports NPLC (AC usually doesn't, FREQ uses APER)
        if "DC" in func or "RES" in func or "FRES" in func:
             self.instrument.write(f"{func}:NPLC {nplc}")

    def quick_read(self):
        return float(self.instrument.query("READ?"))

    def get_voltage(self, ac=False):
        mode = "AC" if ac else "DC"
        self.instrument.write(f"CONF:VOLT:{mode}")
        return float(self.instrument.query("READ?"))

    def get_current(self, ac=False):
        mode = "AC" if ac else "DC"
        self.instrument.write(f"CONF:CURR:{mode}")
        return float(self.instrument.query("READ?"))

    def get_resistance(self, four_wire=False):
        func = "FRES" if four_wire else "RES"
        self.instrument.write(f"CONF:{func}")
        return float(self.instrument.query("READ?"))
