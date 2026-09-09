# This driver has not been tested yet
from .dmm import DMM
from ..scpi import Scpi

class Agilent34410A(Scpi, DMM):
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
    
    # SCPI standard overload response is ±9.90000000E+37 (Keysight 34410A User's Guide)
    SCPI_OVERLOAD_THRESHOLD = 9.9e37

    def _initialize_state(self):
        super()._initialize_state()
        self._scpi_sense_func = "VOLT:DC"

    def reset(self):
        """
        Resets the instrument to factory defaults via ``*RST`` and restores the
        internal SCPI function cache to ``'VOLT:DC'``.
        """
        super().reset()
        self._scpi_sense_func = "VOLT:DC"

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
        CAP -> CAP
        DIOD -> DIOD
        """
        cmd = ""
        sense_func = sense_func.upper()
        coupling = (coupling or "DC").upper()
        sense_mode = (sense_mode or "2W").upper()
        
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
        self._scpi_sense_func = cmd # Store specific SCPI func for other methods

        
    def set_measurement_coupling(self, coupling):
        coupling = (coupling or "DC").upper()
        func = (getattr(self, "_scpi_sense_func", None) or getattr(self, "_current_sense_func", "") or "VOLT:DC").upper()
        base = "CURR" if "CURR" in func else "VOLT"
        cmd = f"{base}:{coupling}"
        self.instrument.write(f"CONF:{cmd}")
        self._scpi_sense_func = cmd

    def set_sense_mode(self, sense_mode):
        sense_mode = (sense_mode or "2W").upper()
        func = (getattr(self, "_scpi_sense_func", None) or getattr(self, "_current_sense_func", "") or "").upper()
        if "RES" in func or "FRES" in func or not func:
            cmd = "FRES" if sense_mode == "4W" else "RES"
            self.instrument.write(f"CONF:{cmd}")
            self._scpi_sense_func = cmd

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

    def _parse_reading(self, raw):
        val = float(raw)
        if abs(val) >= self.SCPI_OVERLOAD_THRESHOLD:
            return float("inf") if val > 0 else float("-inf")
        return val

    def set_integration_time(self, nplc=1):
        # [SENSe:]<Function>:NPLC <nplc>
        # Valid for DCV, DCI, RES, FRES
        func = self.instrument.query("FUNC?").strip().strip('"')
        
        # Check if function supports NPLC (AC usually doesn't, FREQ uses APER)
        if not ("DC" in func or "RES" in func or "FRES" in func):
            raise NotImplementedError(
                f"Agilent 34410A does not support NPLC integration time for function '{func}'; "
                "NPLC is valid only for DCV, DCI, RES, and FRES."
            )
        self.instrument.write(f"{func}:NPLC {nplc}")

    def quick_read(self):
        return self._parse_reading(self.instrument.query("READ?"))

    def get_voltage(self, ac=False):
        mode = "AC" if ac else "DC"
        func = f"VOLT:{mode}"
        self.instrument.write(f"CONF:{func}")
        self._scpi_sense_func = func
        return self._parse_reading(self.instrument.query("READ?"))

    def get_current(self, ac=False):
        mode = "AC" if ac else "DC"
        func = f"CURR:{mode}"
        self.instrument.write(f"CONF:{func}")
        self._scpi_sense_func = func
        return self._parse_reading(self.instrument.query("READ?"))

    def get_resistance(self, four_wire=False):
        func = "FRES" if four_wire else "RES"
        self.instrument.write(f"CONF:{func}")
        self._scpi_sense_func = func
        return self._parse_reading(self.instrument.query("READ?"))

    def get_frequency(self):
        """Returns the measured frequency in Hz."""
        self.instrument.write("CONF:FREQ")
        self._scpi_sense_func = "FREQ"
        return self._parse_reading(self.instrument.query("READ?"))

    def get_capacitance(self):
        """Returns the measured capacitance in Farads."""
        self.instrument.write("CONF:CAP")
        self._scpi_sense_func = "CAP"
        return self._parse_reading(self.instrument.query("READ?"))
