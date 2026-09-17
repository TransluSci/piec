import math
from numbers import Real
import numpy as np

from ..scpi import Scpi
from .awg import Awg


class Agilent33220A(Scpi, Awg):
    """
    Driver for the Agilent 33220A 20 MHz Function / Arbitrary Waveform Generator.
    Based on the Agilent 33220A User's Guide (Publication Number 33220-90002).
    """

    # --- Autodetect Identifier ---
    AUTODETECT_ID = "33220A"

    # --- Class Attributes from Awg ---
    channel = [1]
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']

    # Frequency ranges depend on the function (Manual p. 57, 181, 346)
    # Sine/Square: 1 uHz to 20 MHz
    # Ramp: 1 uHz to 200 kHz
    # Pulse: 500 uHz to 5 MHz
    # Noise: 10 MHz bandwidth (fixed, not tunable)
    # DC: Not applicable
    # User (Arb): 1 uHz to 6 MHz
    frequency = {
        'waveform': {
            'SIN': (1e-6, 20e6),
            'SQU': (1e-6, 20e6),
            'RAMP': (1e-6, 200e3),
            'PULS': (500e-6, 5e6),
            'NOIS': None,
            'DC': None,
            'USER': (1e-6, 6e6),
        }
    }

    # Amplitude: 10 mVpp to 10 Vpp into 50 ohms (Manual p. 58, 182, 347)
    amplitude = (0.01, 10.0)

    # Offset: +/- 5 V into 50 ohms (Manual p. 60, 184, 347)
    offset = (-5.0, 5.0)

    # Load Impedance: 1 ohm to 10 k ohms, or Infinite (Manual p. 63, 189)
    load_impedance = (1.0, 10000.0)

    # Source Impedance: Fixed 50 ohms (Manual p. 35, 63, 347)
    source_impedance = [50]

    # Polarity: Normal or Inverted (Manual p. 67, 190)
    polarity = ['NORM', 'INV']

    # Duty Cycle (Square): 20% to 80% up to 10 MHz (Manual p. 57, 64, 187, 346)
    duty_cycle = (20.0, 80.0)

    # Symmetry (Ramp): 0.0% to 100.0% (Manual p. 65, 188, 346)
    symmetry = (0.0, 100.0)

    # Pulse Width: 20 ns to 2000 s (Manual p. 71, 194, 346)
    pulse_width = (20e-9, 2000.0)

    # Pulse Period: 200 ns to 2000 s (Manual p. 70, 192)
    pulse_period = (200e-9, 2000.0)

    # Pulse Delay: Not supported in 33220A hardware
    pulse_delay = (None, None)

    # Edge Time (Rise / Fall): 5 ns to 100 ns (Manual p. 73, 196, 346)
    edge_time = (5e-9, 100e-9)
    rise_time = (5e-9, 100e-9)
    fall_time = (5e-9, 100e-9)

    # Triggering (Manual p. 104, 113, 116, 220, 228, 231)
    trigger_source = ['INT', 'EXT', 'MAN', 'IMM', 'BUS']
    trigger_slope = ['POS', 'NEG']
    trigger_mode = ['EDGE', 'LEV']
    slew_rate = None

    # Arbitrary Waveform Range: 1 to 65,536 (64K) points (Manual p. 120, 234)
    arb_data_range = (1, 65536)

    # Burst Mode (Manual p. 107-111, 225-226, 348)
    burst_mode = ['TRIG', 'GAT', 'INF']
    burst_count = (1, 50000)

    # Phase: -360 to +360 degrees (Manual p. 112, 145, 227, 258)
    phase = (-360.0, 360.0)

    # Frequency Sweep (Manual p. 102, 219)
    sweep_mode = ['LIN', 'LOG']

    # Modulation (Manual p. 55, 347)
    modulation_type = ['AM', 'FM', 'PM', 'FSK', 'PWM']

    # --- Output Channel Control ---

    def output(self, channel=1, on=True):
        """Turn the output on or off (OUTPut {OFF|ON})."""
        state = "ON" if on else "OFF"
        self.instrument.write(f"OUTP {state}")

    # --- Standard Waveform Configuration ---

    def set_waveform(self, channel=1, waveform=None):
        """Set the waveform shape ('SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER')."""
        if waveform is None:
            raise ValueError("waveform must be provided")
        token = str(waveform).strip().upper()
        if token == "ARB":
            token = "USER"
        self.instrument.write(f"FUNC {token}")

    def set_frequency(self, channel=1, frequency=None):
        """Set the frequency in Hz (FREQuency <frequency>)."""
        if frequency is None:
            raise ValueError("frequency must be provided")
        self.instrument.write(f"FREQ {frequency}")

    def set_amplitude(self, channel=1, amplitude=None):
        """Set the amplitude in Vpp (VOLTage <amplitude>)."""
        if amplitude is None:
            raise ValueError("amplitude must be provided")
        self.instrument.write(f"VOLT {amplitude}")

    def set_offset(self, channel=1, offset=None):
        """Set the DC offset in Volts (VOLTage:OFFSet <offset>)."""
        if offset is None:
            raise ValueError("offset must be provided")
        self.instrument.write(f"VOLT:OFFS {offset}")

    def set_load_impedance(self, channel=1, load_impedance=50.0):
        """
        Set the output load impedance (termination) in ohms or 'INF' for high impedance.
        Command: OUTPut:LOAD {<ohms>|INFinity|MINimum|MAXimum} (Manual p. 63, 189).
        """
        if load_impedance is None:
            raise ValueError("load_impedance must be provided")
        if isinstance(load_impedance, str):
            token = load_impedance.strip().upper()
            if token in ("INF", "INFINITY", "HIGHZ", "HIGH-Z", "HIGH Z"):
                self.instrument.write("OUTP:LOAD INF")
                return
            elif token in ("MIN", "MINIMUM"):
                self.instrument.write("OUTP:LOAD MIN")
                return
            elif token in ("MAX", "MAXIMUM"):
                self.instrument.write("OUTP:LOAD MAX")
                return
            try:
                val = float(token)
            except ValueError:
                raise ValueError(f"Invalid load impedance: '{load_impedance}'")
            if math.isinf(val):
                self.instrument.write("OUTP:LOAD INF")
            else:
                self.instrument.write(f"OUTP:LOAD {val}")
        elif isinstance(load_impedance, Real):
            if math.isinf(load_impedance):
                self.instrument.write("OUTP:LOAD INF")
            else:
                self.instrument.write(f"OUTP:LOAD {load_impedance}")
        else:
            raise ValueError(f"Invalid load impedance: '{load_impedance}'")

    def set_polarity(self, channel=1, polarity=None):
        """
        Set the waveform output polarity ('NORM' or 'INV').
        Command: OUTPut:POLarity {NORMal|INVerted} (Manual p. 67, 190).
        """
        if polarity is None:
            raise ValueError("polarity must be provided")
        token = str(polarity).strip().upper()
        if token in ("NORM", "NORMAL"):
            self.instrument.write("OUTP:POL NORM")
        elif token in ("INV", "INVERTED", "INVERT"):
            self.instrument.write("OUTP:POL INV")
        else:
            raise ValueError(f"Invalid polarity '{polarity}'. Must be 'NORM' or 'INV'")

    def configure_waveform(self, channel=1, waveform=None, frequency=None, amplitude=None,
                           offset=None, load_impedance=None, polarity=None):
        """Configures the waveform to be generated on the selected channel."""
        if waveform is not None:
            self.set_waveform(channel, waveform)
        if frequency is not None:
            self.set_frequency(channel, frequency)
        if amplitude is not None:
            self.set_amplitude(channel, amplitude)
        if offset is not None:
            self.set_offset(channel, offset)
        if load_impedance is not None:
            self.set_load_impedance(channel, load_impedance)
        if polarity is not None:
            self.set_polarity(channel, polarity)

    # --- Waveform Type Specific Methods ---

    def set_square_duty_cycle(self, channel=1, duty_cycle=None):
        """Set the duty cycle for square waves in percent (FUNCtion:SQUare:DCYCle <percent>)."""
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"FUNC:SQU:DCYC {duty_cycle}")

    def set_ramp_symmetry(self, channel=1, symmetry=None):
        """Set the symmetry for ramp waves in percent (FUNCtion:RAMP:SYMMetry <percent>)."""
        if symmetry is None:
            raise ValueError("symmetry must be provided")
        self.instrument.write(f"FUNC:RAMP:SYMM {symmetry}")

    def set_pulse_width(self, channel=1, pulse_width=None, width=None):
        """Set the pulse width in seconds (FUNCtion:PULSe:WIDTh <seconds>)."""
        if pulse_width is None:
            pulse_width = width
        if pulse_width is None:
            raise ValueError("pulse_width must be provided")
        self.instrument.write(f"FUNC:PULS:WIDT {pulse_width}")

    def set_pulse_edge_time(self, channel=1, edge_time=None):
        """
        Set the edge time (both rise and fall) in seconds.
        The 33220A has a single command for edge transition time (FUNCtion:PULSe:TRANsition).
        """
        if edge_time is None:
            raise ValueError("edge_time must be provided")
        self.instrument.write(f"FUNC:PULS:TRAN {edge_time}")

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        """Set the pulse rise time (maps to edge transition time on 33220A)."""
        if rise_time is None:
            raise ValueError("rise_time must be provided")
        self.set_pulse_edge_time(channel, rise_time)

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        """Set the pulse fall time (maps to edge transition time on 33220A)."""
        if fall_time is None:
            raise ValueError("fall_time must be provided")
        self.set_pulse_edge_time(channel, fall_time)

    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        """Set the pulse duty cycle in percent (FUNCtion:PULSe:DCYCle <percent>)."""
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"FUNC:PULS:DCYC {duty_cycle}")

    def set_pulse_delay(self, channel=1, pulse_delay=None):
        """
        Set the pulse delay. The Agilent 33220A hardware does not support pulse delay.
        """
        raise NotImplementedError("The Agilent 33220A does not support pulse delay.")

    def configure_pulse(self, channel=1, pulse_width=None, pulse_delay=None,
                        rise_time=None, fall_time=None, duty_cycle=None):
        """Configures the pulse waveform on the selected channel."""
        self.set_waveform(channel, "PULS")
        if pulse_delay is not None:
            self.set_pulse_delay(channel, pulse_delay)
        if pulse_width is not None:
            self.set_pulse_width(channel, pulse_width)
        if rise_time is not None:
            self.set_pulse_rise_time(channel, rise_time)
        if fall_time is not None:
            self.set_pulse_fall_time(channel, fall_time)
        if duty_cycle is not None:
            self.set_pulse_duty_cycle(channel, duty_cycle)

    # --- Arbitrary Waveform Functions ---

    def create_arb_waveform(self, channel=1, name=None, data=None):
        """
        Creates an arbitrary waveform and downloads it to volatile memory.
        If a name is provided, copies it to non-volatile memory under that name.

        Args:
            channel (int): The channel to create the arbitrary waveform on (default 1).
            name (str, optional): Custom name in non-volatile memory (up to 12 chars).
            data (list or ndarray): Data points (1 to 65536 points).
        """
        if data is None:
            raise ValueError("data must be provided")

        data_array = np.asarray(data, dtype=float)
        n_pts = len(data_array)
        if n_pts < 1 or n_pts > 65536:
            raise ValueError(f"Waveform length must be between 1 and 65536 points, got {n_pts}")

        # Check if data consists of DAC integer codes (-8191 to 8191)
        is_integer_dac = (
            np.all(np.equal(np.mod(data_array, 1), 0))
            and np.max(np.abs(data_array)) <= 8191
            and np.max(np.abs(data_array)) > 1.0
        )

        if is_integer_dac:
            dac_data = np.clip(data_array, -8191, 8191).astype(np.int16)
            if hasattr(self.instrument, "write_binary_values"):
                self.instrument.write("FORM:BORD SWAP")
                self.instrument.write_binary_values("DATA:DAC VOLATILE, ", dac_data.tolist(), datatype='h', is_big_endian=False)
            else:
                data_str = ", ".join(str(int(x)) for x in dac_data)
                self.instrument.write(f"DATA:DAC VOLATILE, {data_str}")
        else:
            max_abs = np.max(np.abs(data_array))
            norm_data = data_array / max_abs if max_abs > 1.0 else data_array

            if hasattr(self.instrument, "write_binary_values") and n_pts > 256:
                dac_data = np.clip(np.round(norm_data * 8191), -8191, 8191).astype(np.int16)
                self.instrument.write("FORM:BORD SWAP")
                self.instrument.write_binary_values("DATA:DAC VOLATILE, ", dac_data.tolist(), datatype='h', is_big_endian=False)
            else:
                data_str = ", ".join(f"{float(x):.6g}" for x in norm_data)
                self.instrument.write(f"DATA VOLATILE, {data_str}")

        if name is not None:
            clean_name = str(name).strip().upper()
            if clean_name and clean_name != "VOLATILE":
                if not (1 <= len(clean_name) <= 12):
                    raise ValueError(f"Arbitrary waveform name must be 1 to 12 characters, got '{name}'")
                if not clean_name[0].isalpha():
                    raise ValueError(f"Arbitrary waveform name must start with a letter, got '{name}'")
                if not all(c.isalnum() or c == '_' for c in clean_name):
                    raise ValueError(f"Arbitrary waveform name can only contain letters, numbers, and underscores, got '{name}'")
                if clean_name in ("EXP_RISE", "EXP_FALL", "NEG_RAMP", "SINC", "CARDIAC"):
                    raise ValueError(f"Cannot overwrite built-in waveform '{clean_name}'")
                self.instrument.write(f"DATA:COPY {clean_name}, VOLATILE")

    def set_arb_waveform(self, channel=1, name="VOLATILE"):
        """
        Sets the arbitrary waveform to be generated on the selected channel.
        Selects one of the five built-in waveforms ('EXP_RISE', 'EXP_FALL', 'NEG_RAMP',
        'SINC', 'CARDIAC'), a user-defined waveform, or 'VOLATILE'.
        Command: FUNCtion:USER {<arb name>|VOLATILE} (Manual p. 240).
        """
        if name is None:
            name = "VOLATILE"
        token = str(name).strip().upper()
        self.instrument.write(f"FUNC:USER {token}")

    # --- Trigger and Sync Functions ---

    def set_trigger_source(self, channel=1, trigger_source=None):
        """
        Sets the trigger source for sweep and burst modes.
        Sources: 'INT'/'IMM' (internal/immediate), 'EXT' (external), 'MAN'/'BUS' (software/bus).
        Command: TRIGger:SOURce {IMMediate|EXTernal|BUS} (Manual p. 104, 116, 220, 228, 231).
        """
        if trigger_source is None:
            raise ValueError("trigger_source must be provided")
        token = str(trigger_source).strip().upper()
        if token in ("INT", "INTERNAL", "IMM", "IMMEDIATE"):
            cmd = "IMM"
        elif token in ("EXT", "EXTERNAL"):
            cmd = "EXT"
        elif token in ("MAN", "MANUAL", "BUS", "SOFTWARE"):
            cmd = "BUS"
        else:
            raise ValueError(f"Invalid trigger_source '{trigger_source}'. Must be 'INT', 'EXT', or 'MAN'")
        self.instrument.write(f"TRIG:SOUR {cmd}")

    def set_trigger_level(self, channel=1, trigger_level=None):
        """
        Set trigger level. The Agilent 33220A has a fixed TTL-compatible trigger input
        and does not support an adjustable trigger level.
        """
        raise NotImplementedError("The Agilent 33220A does not support adjustable trigger level (fixed TTL).")

    def set_trigger_slope(self, channel=1, trigger_slope=None):
        """
        Sets the trigger slope for the external trigger input (Trig In).
        Slope: 'POS'/'POSITIVE'/'RISING' or 'NEG'/'NEGATIVE'/'FALLING'.
        Command: TRIGger:SLOPe {POSitive|NEGative} (Manual p. 104, 114, 221, 229, 232).
        """
        if trigger_slope is None:
            raise ValueError("trigger_slope must be provided")
        token = str(trigger_slope).strip().upper()
        if token in ("POS", "POSITIVE", "RISING"):
            cmd = "POS"
        elif token in ("NEG", "NEGATIVE", "FALLING"):
            cmd = "NEG"
        else:
            raise ValueError(f"Invalid trigger_slope '{trigger_slope}'. Must be 'POS' or 'NEG'")
        self.instrument.write(f"TRIG:SLOP {cmd}")

    def set_trigger_mode(self, channel=1, trigger_mode=None):
        """
        Sets the trigger mode (burst mode): 'EDGE'/'TRIG' (triggered burst)
        or 'LEV'/'GAT' (externally gated burst).
        Command: BURSt:MODE {TRIGgered|GATed} (Manual p. 107, 225).
        """
        if trigger_mode is None:
            raise ValueError("trigger_mode must be provided")
        token = str(trigger_mode).strip().upper()
        if token in ("EDGE", "TRIG", "TRIGGERED"):
            cmd = "TRIG"
        elif token in ("LEV", "LEVEL", "GAT", "GATED"):
            cmd = "GAT"
        else:
            raise ValueError(f"Invalid trigger_mode '{trigger_mode}'. Must be 'EDGE' or 'LEV'")
        self.instrument.write(f"BURS:MODE {cmd}")

    def configure_trigger(self, channel=1, trigger_source=None, trigger_level=None,
                          trigger_slope=None, trigger_mode=None):
        """Configures trigger parameters."""
        if trigger_source is not None:
            self.set_trigger_source(channel, trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(channel, trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(channel, trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(channel, trigger_mode)

    def output_trigger(self):
        """
        Outputs the trigger signal for the AWG via remote bus trigger (*TRG).
        Manual p. 117, 229, 232.
        """
        self.instrument.write("*TRG")

    # --- Burst Mode Methods ---

    def set_burst_mode(self, channel=1, burst_mode='TRIG'):
        """
        Sets the burst mode type ('TRIG', 'GAT', or 'INF').
        Automatically enables burst mode (BURSt:STATe ON).
        Manual p. 107-111, 225-228.
        """
        if burst_mode is None:
            raise ValueError("burst_mode must be provided")
        token = str(burst_mode).strip().upper()
        if token in ("TRIG", "TRIGGERED"):
            self.instrument.write("BURS:MODE TRIG")
            self.instrument.write("BURS:STAT ON")
        elif token in ("GAT", "GATED"):
            self.instrument.write("BURS:MODE GAT")
            self.instrument.write("BURS:STAT ON")
        elif token in ("INF", "INFINITE"):
            self.instrument.write("BURS:MODE TRIG")
            self.instrument.write("BURS:NCYC INF")
            self.instrument.write("BURS:STAT ON")
        else:
            raise ValueError(f"Invalid burst_mode '{burst_mode}'. Must be 'TRIG', 'GAT', or 'INF'")

    def set_burst_count(self, channel=1, burst_count=1):
        """
        Sets the number of cycles per burst (1 to 50,000 or 'INF').
        Command: BURSt:NCYCles {<# cycles>|INFinity|MINimum|MAXimum} (Manual p. 110, 226).
        """
        if burst_count is None:
            raise ValueError("burst_count must be provided")
        if isinstance(burst_count, str) and burst_count.strip().upper() in ("INF", "INFINITY"):
            self.instrument.write("BURS:NCYC INF")
        elif isinstance(burst_count, Real) and math.isinf(burst_count):
            self.instrument.write("BURS:NCYC INF")
        else:
            self.instrument.write(f"BURS:NCYC {int(burst_count)}")

    def configure_burst(self, channel=1, burst_mode=None, burst_count=None):
        """Configures burst mode (calls set_burst_mode and set_burst_count)."""
        if burst_mode is not None:
            self.set_burst_mode(channel, burst_mode)
        if burst_count is not None:
            self.set_burst_count(channel, burst_count)

    # --- Phase ---

    def set_phase(self, channel=1, phase=None):
        """
        Sets the phase offset of the waveform in degrees (-360 to +360).
        Command: PHASe {<angle>|MINimum|MAXimum} (Manual p. 112, 145, 227, 258).
        """
        if phase is None:
            raise ValueError("phase must be provided")
        self.instrument.write(f"PHAS {phase}")

    # --- Frequency Sweep Methods ---

    def set_sweep_mode(self, channel=1, sweep_mode='LIN'):
        """
        Sets the sweep type ('LIN' or 'LOG').
        Automatically enables frequency sweep (SWEep:STATe ON).
        Command: SWEep:SPACing {LINear|LOGarithmic} (Manual p. 102, 219).
        """
        if sweep_mode is None:
            raise ValueError("sweep_mode must be provided")
        token = "LIN" if str(sweep_mode).strip().upper().startswith("LIN") else "LOG"
        self.instrument.write(f"SWE:SPAC {token}")
        self.instrument.write("SWE:STAT ON")

    def set_sweep_start_freq(self, channel=1, start_freq=None):
        """Set the sweep start frequency in Hz (FREQuency:STARt <frequency>, Manual p. 100, 217)."""
        if start_freq is None:
            raise ValueError("start_freq must be provided")
        self.instrument.write(f"FREQ:STAR {start_freq}")

    def set_sweep_stop_freq(self, channel=1, stop_freq=None):
        """Set the sweep stop frequency in Hz (FREQuency:STOP <frequency>, Manual p. 100, 217)."""
        if stop_freq is None:
            raise ValueError("stop_freq must be provided")
        self.instrument.write(f"FREQ:STOP {stop_freq}")

    def set_sweep_time(self, channel=1, sweep_time=None):
        """Set the sweep duration in seconds (SWEep:TIME <seconds>, Manual p. 102, 219)."""
        if sweep_time is None:
            raise ValueError("sweep_time must be provided")
        self.instrument.write(f"SWE:TIME {sweep_time}")

    def configure_sweep(self, channel=1, sweep_mode=None, start_freq=None, stop_freq=None, sweep_time=None):
        """Configures frequency sweep. Calls individual set_ methods."""
        if sweep_mode is not None:
            self.set_sweep_mode(channel, sweep_mode)
        if start_freq is not None:
            self.set_sweep_start_freq(channel, start_freq)
        if stop_freq is not None:
            self.set_sweep_stop_freq(channel, stop_freq)
        if sweep_time is not None:
            self.set_sweep_time(channel, sweep_time)

    # --- Modulation Methods ---

    def set_modulation_type(self, channel=1, mod_type='AM'):
        """
        Sets the modulation type ('AM', 'FM', 'PM', 'FSK', 'PWM') and enables it.
        Manual p. 74-98, 197-214.
        """
        if mod_type is None:
            raise ValueError("mod_type must be provided")
        token = str(mod_type).strip().upper()
        if token not in ("AM", "FM", "PM", "FSK", "PWM"):
            raise ValueError(f"Invalid mod_type '{mod_type}'. Must be 'AM', 'FM', 'PM', 'FSK', or 'PWM'")
        self._current_mod_type = token
        prefix = "FSK" if token == "FSK" else token
        self.instrument.write(f"{prefix}:STAT ON")

    def set_modulation_depth(self, channel=1, depth=None):
        """
        Sets modulation depth / deviation / hop frequency based on active modulation type.
        - AM: Modulation depth in percent (0 to 120%)
        - FM: Frequency deviation in Hz
        - PM: Phase deviation in degrees (0 to 360)
        - PWM: Width deviation in seconds
        - FSK: Hop frequency in Hz
        Manual p. 77, 83, 88, 91, 96, 199, 202, 206, 209, 212.
        """
        if depth is None:
            raise ValueError("depth must be provided")
        mtype = getattr(self, "_current_mod_type", "AM").upper()
        if mtype == "AM":
            self.instrument.write(f"AM:DEPT {depth}")
        elif mtype == "FM":
            self.instrument.write(f"FM:DEV {depth}")
        elif mtype == "PM":
            self.instrument.write(f"PM:DEV {depth}")
        elif mtype == "PWM":
            self.instrument.write(f"PWM:DEV {depth}")
        elif mtype == "FSK":
            self.instrument.write(f"FSK:FREQ {depth}")
        else:
            self.instrument.write(f"AM:DEPT {depth}")

    def set_modulation_frequency(self, channel=1, frequency=None):
        """
        Sets internal modulation frequency (or FSK rate) in Hz.
        Manual p. 76, 82, 87, 91, 95, 199, 202, 206, 209, 212.
        """
        if frequency is None:
            raise ValueError("frequency must be provided")
        mtype = getattr(self, "_current_mod_type", "AM").upper()
        if mtype == "FSK":
            self.instrument.write(f"FSK:INT:RATE {frequency}")
        else:
            self.instrument.write(f"{mtype}:INT:FREQ {frequency}")

    def set_modulation_source(self, channel=1, source='INT'):
        """
        Sets the modulation source ('INT' or 'EXT').
        Manual p. 78, 84, 88, 92, 98, 198, 201, 205, 208, 211.
        """
        if source is None:
            raise ValueError("source must be provided")
        token_src = "INT" if str(source).strip().upper().startswith("INT") else "EXT"
        mtype = getattr(self, "_current_mod_type", "AM").upper()
        prefix = "FSK" if mtype == "FSK" else mtype
        self.instrument.write(f"{prefix}:SOUR {token_src}")

    def configure_modulation(self, channel=1, mod_type=None, depth=None, frequency=None, source=None):
        """Configures modulation. Calls individual set_ methods."""
        if mod_type is not None:
            self.set_modulation_type(channel, mod_type)
        if depth is not None:
            self.set_modulation_depth(channel, depth)
        if frequency is not None:
            self.set_modulation_frequency(channel, frequency)
        if source is not None:
            self.set_modulation_source(channel, source)

