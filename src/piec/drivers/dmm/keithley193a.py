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
        Queries the instrument identity using the ``U0X`` Machine Status Word
        command.  The 193A does not support ``*IDN?``; instead the status
        word returned by ``U0X`` contains the model prefix ``193``.

        Returns:
            str: Identification string, or an error message on failure.
        """
        try:
            self.instrument.write("U0X")
            raw = self.instrument.read()
            if "193" in raw:
                return f"Keithley,193A,{self.instrument.resource_name},{raw.strip()}"
            else:
                return f"Keithley,Unknown ({raw.strip()}),{self.instrument.resource_name}"
        except pyvisa.errors.VisaIOError:
            return "Not connected (VisaIOError)"

    def get_voltage(self, ac=False):
        """
        Reads a voltage measurement from the DMM.

        Sends the appropriate function command (F0 = DCV, F1 = ACV) and
        reads back the measurement result.  The 193A does **not** support
        SCPI queries like ``MEAS:VOLT:DC?`` — sending them triggers an
        IDDC (Illegal Device-Dependent Command) error.

        Args:
            ac (bool): If True, measures AC voltage (F1). Otherwise DC (F0).
        Returns:
            float: The measured voltage in Volts.
        """
        cmd = "F1X" if ac else "F0X"
        self.instrument.write(cmd)
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

    # --- DMM-Specific Methods ---
    # Function codes per manual (193A_901_01A):
    #   F0 = DCV, F1 = ACV, F2 = Ohms, F3 = DCA, F4 = ACA
    #   F5 = Temp °F (RTD), F6 = Temp °C (RTD)

    def set_sense_function(self, sense_func):
        func_map = {
            'VOLT': 'F0X',   # DC Volts
            'CURR': 'F3X',   # DC Current
            'RES':  'F2X',   # 2-Wire Ohms
        }
        cmd = func_map.get(sense_func.upper())
        if cmd is None:
            raise ValueError(f"Function '{sense_func}' not supported by 193A. Use: {list(func_map.keys())}")
        self.instrument.write(cmd)

    def quick_read(self):
        return self.get_voltage()

    def set_measurement_coupling(self, coupling):
        """
        Switches between AC and DC coupling for the **voltage** function.

        .. warning::
            This sends ``F1X`` (ACV) or ``F0X`` (DCV), which will overwrite
            the current measurement function.  If the DMM was previously in
            a current or resistance mode, it will be switched to voltage.
            Use :meth:`set_sense_function` to select the function first,
            then call this to choose AC or DC coupling.
        """
        if coupling.upper() == 'AC':
            self.instrument.write("F1X")   # ACV
        else:
            self.instrument.write("F0X")   # DCV

    def get_current(self, ac=False):
        """
        Reads a current measurement from the DMM.
        Requires the optional current input module.

        Args:
            ac (bool): If True, measures AC current (F4). Otherwise DC current (F3).
        Returns:
            float: The measured current in Amps.
        """
        cmd = "F4X" if ac else "F3X"  # F3 = DCA, F4 = ACA
        self.instrument.write(cmd)
        try:
            raw_val = self.instrument.read()
            return float(self._extract_number(raw_val))
        except Exception:
            print("[Keithley193A] get_current() failed to read.")
            return None

    def get_resistance(self, four_wire=False):
        """
        Reads a resistance measurement from the DMM using ``F2X`` (Ohms).

        The 193A always sends the measurement command via ``F2X``.  If
        the physical 4-terminal sense leads are connected to the OHMS
        SENSE HI / LO terminals, the instrument performs 4-terminal
        sensing automatically — no separate DDC command is needed.

        Args:
            four_wire (bool): Informational only.  The 193A uses
                4-terminal sensing when the sense leads are connected.
        Returns:
            float: The measured resistance in Ohms.
        """
        self.instrument.write("F2X")  # F2 = Ohms
        try:
            raw_val = self.instrument.read()
            return float(self._extract_number(raw_val))
        except Exception:
            print("[Keithley193A] get_resistance() failed to read.")
            return None

    def get_temperature(self, probe_type='RTD'):
        """
        Reads a temperature measurement using the RTD input.

        Uses ``F6X`` for degrees Celsius (°C).  The 193A also supports
        ``F5X`` for degrees Fahrenheit (°F), but this method defaults to
        Celsius for scientific consistency.

        The 193A only supports RTD probes; thermocouple and thermistor
        probe types are not available.

        Args:
            probe_type (str): Ignored — the 193A only supports 'RTD'.
        Returns:
            float: Temperature in °C.
        """
        if probe_type.upper() != 'RTD':
            print(f"[Keithley193A] probe_type '{probe_type}' not supported — using RTD.")
        self.instrument.write("F6X")  # F6 = Temperature °C (RTD)
        try:
            raw_val = self.instrument.read()
            return float(self._extract_number(raw_val))
        except Exception:
            print("[Keithley193A] get_temperature() failed to read.")
            return None

    def set_sense_mode(self, sense_mode):
        """
        Not applicable — the 193A only supports 2-wire measurements.
        """
        if sense_mode.upper() == '4W':
            print("[Keithley193A] 4-wire mode is not supported — 2-wire only.")

    def set_sense_range(self, range_val=None, auto=True):
        if auto:
            self.instrument.write("R0X")
        else:
            # Nominal ranges would need mapping
            pass

    def set_integration_time(self, nplc=1):
        """
        Maps NPLC-like values to the 193A rate commands.
        The 193A uses S0–S3 for integration rate:
          S0 = 318µs / 3½-digit,  S1 = 2.59ms / 4½-digit,
          S2 = line-cycle / 5½-digit,  S3 = line-cycle / 6½-digit.

        Args:
            nplc (float): Approximate NPLC value.
                          <0.01 → S0,  <0.1 → S1,  <1 → S2,  ≥1 → S3.
        """
        if nplc < 0.01:
            self.instrument.write("S0X")   # fastest / lowest resolution
        elif nplc < 0.1:
            self.instrument.write("S1X")
        elif nplc < 1:
            self.instrument.write("S2X")
        else:
            self.instrument.write("S3X")   # slowest / highest resolution

    # --- SCPI-Equivalent Overrides ---
    # The 193A uses Device Dependent Commands (DDC), not SCPI.

    def reset(self):
        """
        Restores the 193A to factory / power-up defaults using ``L0X``.

        ``L0X`` is faster and more thorough than manually sending
        individual function and range commands.
        """
        self.instrument.write("L0X")  # L0 = restore factory defaults
        self._initialize_state()

    def clear(self):
        """
        Sends an IEEE-488 Device Clear (DCL/SDC) to the 193A.

        This returns the instrument to its power-up default state via
        the bus-level clear mechanism, which is supported by the 193A.
        """
        self.instrument.clear()  # PyVISA sends SDC (Selected Device Clear)

    def error(self):
        """
        Not supported — the 193A does not have an error query command.

        Returns:
            str: Always returns 'No error query available'.
        """
        print("[Keithley193A] error() is not supported by this instrument.")
        return "No error query available"

    def wait(self):
        """
        Not supported — the 193A does not have a pending-operation queue.
        """
        print("[Keithley193A] wait() is not supported by this instrument — no-op.")

    def self_test(self):
        """
        Not supported — the 193A does not have a built-in self-test routine.

        Returns:
            str: Always returns ``'1'`` (not supported).
        """
        print("[Keithley193A] self_test() is not supported by this instrument.")
        return "1"

    def operation_complete(self):
        """
        Not supported — the 193A responds immediately to commands.

        Returns:
            str: Always returns ``'1'`` (complete).
        """
        return "1"

    def initialize(self):
        """
        Initialises the 193A by resetting to DCV autorange.
        """
        self.reset()
