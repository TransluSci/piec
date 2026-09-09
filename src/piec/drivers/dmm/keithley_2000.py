# This driver has not been tested yet
from .dmm import DMM
from ..scpi import Scpi

class Keithley2000(Scpi, DMM):
    """
    Driver for the Keithley 2000 Digital Multimeter.
    """
    
    AUTODETECT_ID = "MODEL 2000"
    
    channel = [1]
    
    sense_func = ['VOLT', 'CURR', 'RES', 'FRES', 'FREQ', 'PER', 'TEMP']
    
    coupling = ['DC', 'AC']
    
    sense_mode = ['2W', '4W']
    
    sense_range = (None, None)
    
    # SCPI standard overload response is ±9.99999900E+37 (Model 2000 User's Manual Section 3)
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
        self._scpi_sense_func = cmd

    def set_measurement_coupling(self, coupling):
        coupling = (coupling or "DC").upper()
        func = (getattr(self, "_scpi_sense_func", None) or getattr(self, "_current_sense_func", "") or "VOLT:DC").upper()
        base = "CURR" if "CURR" in func else "VOLT"
        cmd = f"{base}:{coupling}"
        self.instrument.write(f":SENS:FUNC '{cmd}'")
        self._scpi_sense_func = cmd

    def set_sense_mode(self, sense_mode):
        sense_mode = (sense_mode or "2W").upper()
        func = (getattr(self, "_scpi_sense_func", None) or getattr(self, "_current_sense_func", "") or "").upper()
        if "RES" in func or "FRES" in func or not func:
            cmd = "FRES" if sense_mode == "4W" else "RES"
            self.instrument.write(f":SENS:FUNC '{cmd}'")
            self._scpi_sense_func = cmd

    def _get_current_scpi_func(self):
        func = getattr(self, "_scpi_sense_func", None)
        if not func:
            curr_func = (getattr(self, "_current_sense_func", None) or "VOLT").upper()
            curr_coup = (getattr(self, "_current_coupling", None) or "DC").upper()
            curr_mode = (getattr(self, "_current_sense_mode", None) or "2W").upper()
            if curr_func == "VOLT":
                func = f"VOLT:{curr_coup}"
            elif curr_func == "CURR":
                func = f"CURR:{curr_coup}"
            elif curr_func in ("RES", "FRES"):
                func = "FRES" if curr_mode == "4W" or curr_func == "FRES" else "RES"
            else:
                func = curr_func
        return func

    def set_sense_range(self, range_val=None, auto=True):
        # :VOLT:DC:RANG <n> or :AUTO ON
        func = self._get_current_scpi_func()
             
        if auto:
            self.instrument.write(f":SENS:{func}:RANG:AUTO ON")
        else:
            if range_val is not None:
                self.instrument.write(f":SENS:{func}:RANG {range_val}")

    def _parse_reading(self, raw):
        val = float(raw)
        if abs(val) >= self.SCPI_OVERLOAD_THRESHOLD:
            return float("inf") if val > 0 else float("-inf")
        return val

    def set_integration_time(self, nplc=1):
        # :VOLT:DC:NPLC <n>
        # Valid for DCV, DCI, RES, FRES, TEMP
        func = self._get_current_scpi_func()
        func_upper = func.upper()
        if not ("DC" in func_upper or "RES" in func_upper or "FRES" in func_upper or "TEMP" in func_upper):
            raise NotImplementedError(
                f"Keithley 2000 does not support NPLC integration time for function '{func}'; "
                "NPLC is valid only for DCV, DCI, RES, FRES, and TEMP."
            )
        self.instrument.write(f":SENS:{func}:NPLC {nplc}")

    def quick_read(self):
        return self._parse_reading(self.instrument.query(":READ?"))

    def get_voltage(self, ac=False):
        mode = "AC" if ac else "DC"
        func = f"VOLT:{mode}"
        self.instrument.write(f":SENS:FUNC '{func}'")
        self._scpi_sense_func = func
        return self._parse_reading(self.instrument.query(":READ?"))

    def get_current(self, ac=False):
        mode = "AC" if ac else "DC"
        func = f"CURR:{mode}"
        self.instrument.write(f":SENS:FUNC '{func}'")
        self._scpi_sense_func = func
        return self._parse_reading(self.instrument.query(":READ?"))

    def get_resistance(self, four_wire=False):
        func = "FRES" if four_wire else "RES"
        self.instrument.write(f":SENS:FUNC '{func}'")
        self._scpi_sense_func = func
        return self._parse_reading(self.instrument.query(":READ?"))

    def get_frequency(self):
        """Returns the measured frequency in Hz."""
        self.instrument.write(":SENS:FUNC 'FREQ'")
        self._scpi_sense_func = "FREQ"
        return self._parse_reading(self.instrument.query(":READ?"))

    def get_temperature(self, probe_type='TC'):
        """
        Returns the measured temperature.
        args:
            probe_type (str): 'TC' (thermocouple), 'RTD', 'THER' (thermistor)
        """
        self.instrument.write(":SENS:FUNC 'TEMP'")
        self._scpi_sense_func = "TEMP"
        # Set probe type if supported
        PROBE_MAP = {'TC': 'TC', 'RTD': 'RTD', 'THER': 'THER'}
        pt = PROBE_MAP.get(probe_type.upper(), probe_type)
        self.instrument.write(f":SENS:TEMP:TRAN {pt}")
        return self._parse_reading(self.instrument.query(":READ?"))
