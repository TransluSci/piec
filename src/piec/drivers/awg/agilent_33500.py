"""
Driver for the Agilent 33500 Series Arbitrary Waveform Generators.
Covering models like 33511B, 33512B, 33521A, 33522A, etc.
Based on the Agilent 33500 Series User's Guide (Publication Number 33520-90001).
"""
import numpy as np

from ..scpi import Scpi
from .awg import Awg


class Agilent33500(Scpi, Awg):
    """
    Driver for the Agilent 33500 Series Arbitrary Waveform Generators.

    Implements the standard Category interface (Awg) and IEEE 488.2 / SCPI
    commands using the Agilent 33500 Series programming reference.
    """

    # Model identification
    AUTODETECT_ID = "335"

    # Channels: 33521A has 1 channel, 33522A has 2 channels
    channel = [1, 2]

    # Standard and Arbitrary Waveforms (Manual p. 80, 82, 256, 268)
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER', 'PRBS']

    # Frequency ranges (Manual p. 83, 95, 256, 268)
    frequency = {
        'waveform': {
            'SIN': (1e-6, 30e6),
            'SQU': (1e-6, 30e6),
            'RAMP': (1e-6, 200e3),
            'PULS': (1e-6, 30e6),
            'NOIS': (1e-3, 30e6),
            'DC': (None, None),
            'USER': (1e-6, 30e6),
            'PRBS': (1e-6, 50e6)
        }
    }

    # Amplitude: 1 mVpp to 10 Vpp into 50 ohms (Manual p. 84, 96, 257)
    amplitude = (0.001, 10.0)

    # Offset: +/- 5 V into 50 ohms (Manual p. 86, 98, 257)
    offset = (-5.0, 5.0)

    # Load Impedance: 1 ohm to 10 kohm, or infinite (Manual p. 89, 90, 101, 102)
    load_impedance = (1.0, 10000.0)
    source_impedance = [50]

    # Polarity: Normal or Inverted (Manual p. 94, 106)
    polarity = ['NORM', 'INV']

    # Duty Cycle (Square wave): 0.01% to 99.99% (Manual p. 91, 103)
    duty_cycle = (0.01, 99.99)

    # Symmetry (Ramp wave): 0.0% to 100.0% (Manual p. 92, 104)
    symmetry = (0.0, 100.0)

    # Pulse Width: 16 ns to 1,000,000 s (Manual p. 99, 111, 268)
    pulse_width = (16e-9, 1000000.0)

    # Pulse Period: 33.3 ns to 1,000,000 s (Manual p. 98, 110)
    pulse_period = (33.3e-9, 1000000.0)

    # Pulse Edge Times (Rise and Fall): 8.4 ns to 1 us (Manual p. 101, 113, 268)
    edge_time = (8.4e-9, 1e-6)
    rise_time = (8.4e-9, 1e-6)
    fall_time = (8.4e-9, 1e-6)

    # Triggering (Manual p. 138-139, 150-155, 260)
    trigger_source = ['INT', 'EXT', 'MAN', 'IMM', 'BUS', 'TIM']
    trigger_slope = ['POS', 'NEG']
    trigger_mode = ['EDGE', 'LEV']
    slew_rate = None

    # Arbitrary Waveform range: 8 to 1,000,000 points (Manual p. 240, 268)
    arb_data_range = (8, 1000000)

    # Burst Mode (Manual p. 141-149, 259)
    burst_mode = ['TRIG', 'GAT', 'INF']
    burst_count = (1, 100000000)

    # Phase: -360 to +360 degrees (Manual p. 147, 159, 184, 196)
    phase = (-360.0, 360.0)

    # Sweep Mode (Manual p. 132-140, 259)
    sweep_mode = ['LIN', 'LOG']

    # Modulation Types (Manual p. 102-131, 258-259)
    modulation_type = ['AM', 'FM', 'PM', 'FSK', 'PWM']

    # -------------------------------------------------------------------------
    # Output Control Functions
    # -------------------------------------------------------------------------

    def output(self, channel=1, on=True):
        """Enable or disable output on the selected channel (OUTPut[1|2] {OFF|ON})."""
        state = "ON" if on else "OFF"
        self.instrument.write(f"OUTP{channel} {state}")

    def set_load_impedance(self, channel=1, load_impedance=None, ohms=None):
        """
        Set the expected output load impedance (OUTPut[1|2]:LOAD {<ohms>|INFinity}).
        """
        if load_impedance is None and ohms is not None:
            load_impedance = ohms
        if load_impedance is None:
            raise ValueError("load_impedance must be provided")

        if load_impedance == float("inf") or str(load_impedance).upper() in ("INF", "INFINITY"):
            self.instrument.write(f"OUTP{channel}:LOAD INF")
        else:
            self.instrument.write(f"OUTP{channel}:LOAD {load_impedance}")

    def set_polarity(self, channel=1, polarity=None):
        """
        Set output waveform polarity (OUTPut[1|2]:POLarity {NORMal|INVerted}).
        """
        if polarity is None:
            raise ValueError("polarity must be provided")
        token = "NORM" if polarity.lower() in ("norm", "normal") else "INV"
        self.instrument.write(f"OUTP{channel}:POL {token}")

    # -------------------------------------------------------------------------
    # Waveform Configuration Functions
    # -------------------------------------------------------------------------

    def set_waveform(self, channel=1, waveform=None):
        """
        Select the waveform shape on the selected channel (SOURce[1|2]:FUNCtion <shape>).
        """
        if waveform is None:
            raise ValueError("waveform must be provided")
        token = "ARB" if waveform.lower() in ("user", "arb") else waveform.upper()
        self.instrument.write(f"SOUR{channel}:FUNC {token}")

    def set_frequency(self, channel=1, frequency=None):
        """Set waveform frequency in Hz (SOURce[1|2]:FREQuency <freq>)."""
        if frequency is None:
            raise ValueError("frequency must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ {frequency}")

    def set_amplitude(self, channel=1, amplitude=None):
        """Set peak-to-peak amplitude in Volts (SOURce[1|2]:VOLTage <ampl>)."""
        if amplitude is None:
            raise ValueError("amplitude must be provided")
        self.instrument.write(f"SOUR{channel}:VOLT {amplitude}")

    def set_offset(self, channel=1, offset=None):
        """Set DC offset voltage in Volts (SOURce[1|2]:VOLTage:OFFSet <offset>)."""
        if offset is None:
            raise ValueError("offset must be provided")
        self.instrument.write(f"SOUR{channel}:VOLT:OFFS {offset}")

    def set_phase(self, channel=1, phase=None):
        """Set waveform phase offset in degrees (SOURce[1|2]:PHASe <phase>)."""
        if phase is None:
            raise ValueError("phase must be provided")
        self.instrument.write(f"SOUR{channel}:PHAS {phase}")

    def set_square_duty_cycle(self, channel=1, duty_cycle=None):
        """Set square wave duty cycle in percent (SOURce[1|2]:FUNCtion:SQUare:DCYCle <percent>)."""
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:SQU:DCYC {duty_cycle}")

    def set_ramp_symmetry(self, channel=1, symmetry=None):
        """Set ramp wave symmetry in percent (SOURce[1|2]:FUNCtion:RAMP:SYMMetry <percent>)."""
        if symmetry is None:
            raise ValueError("symmetry must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:RAMP:SYMM {symmetry}")

    # -------------------------------------------------------------------------
    # Pulse Waveform Functions
    # -------------------------------------------------------------------------

    def set_pulse_period(self, channel=1, pulse_period=None, period=None):
        """Set pulse period in seconds (SOURce[1|2]:FUNCtion:PULSe:PERiod <seconds>)."""
        if pulse_period is None and period is not None:
            pulse_period = period
        if pulse_period is None:
            raise ValueError("pulse_period must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:PER {pulse_period}")

    def set_pulse_width(self, channel=1, pulse_width=None, width=None):
        """Set pulse width in seconds (SOURce[1|2]:FUNCtion:PULSe:WIDTh <seconds>)."""
        if pulse_width is None and width is not None:
            pulse_width = width
        if pulse_width is None:
            raise ValueError("pulse_width must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:WIDT {pulse_width}")

    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        """Set pulse duty cycle in percent (SOURce[1|2]:FUNCtion:PULSe:DCYCle <percent>)."""
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:DCYC {duty_cycle}")

    def set_pulse_edge_time(self, channel=1, edge_time=None):
        """Set both leading and trailing edge times in seconds (SOURce[1|2]:FUNCtion:PULSe:TRANsition <seconds>)."""
        if edge_time is None:
            raise ValueError("edge_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN {edge_time}")

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        """Set pulse leading edge time in seconds (SOURce[1|2]:FUNCtion:PULSe:TRANsition:LEADing <seconds>)."""
        if rise_time is None:
            raise ValueError("rise_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:LEAD {rise_time}")

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        """Set pulse trailing edge time in seconds (SOURce[1|2]:FUNCtion:PULSe:TRANsition:TRAiling <seconds>)."""
        if fall_time is None:
            raise ValueError("fall_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:TRA {fall_time}")

    def configure_pulse(self, channel=1, pulse_width=None,
                        rise_time=None, fall_time=None, duty_cycle=None):
        """Configures the pulse waveform on the selected channel."""
        self.set_waveform(channel, "PULS")
        if pulse_width is not None:
            self.set_pulse_width(channel, pulse_width)
        if rise_time is not None:
            self.set_pulse_rise_time(channel, rise_time)
        if fall_time is not None:
            self.set_pulse_fall_time(channel, fall_time)
        if duty_cycle is not None:
            self.set_pulse_duty_cycle(channel, duty_cycle)

    # -------------------------------------------------------------------------
    # Arbitrary Waveform Functions
    # -------------------------------------------------------------------------

    def create_arb_waveform(self, name, data, channel=1, sample_rate=None):
        """
        Download arbitrary waveform data points to instrument memory.

        Data points must be floating-point numbers between -1.0 and +1.0,
        with length between 8 and 1,000,000 points (Manual p. 224-225, 240, 268).

        Args:
            name (str): Identifier name for the arbitrary waveform.
            data (iterable): Sequence of normalized float data points (-1.0 to 1.0).
            channel (int): Target output channel (default 1).
            sample_rate (float, optional): Sample rate in Sa/s.
        """
        if not name or not isinstance(name, str):
            raise ValueError("Arbitrary waveform name must be a non-empty string")
        if not name.replace("_", "").isalnum():
            raise ValueError("Waveform name must contain only alphanumeric characters and underscores")

        data_array = np.asarray(data, dtype=float)
        num_points = len(data_array)
        if num_points < 8 or num_points > 1000000:
            raise ValueError(f"Arbitrary waveform point count {num_points} is outside range (8, 1000000)")

        if np.any(data_array < -1.0) or np.any(data_array > 1.0):
            raise ValueError("Data points must be between -1.0 and 1.0")

        # Download via SOURce{channel}:DATA:ARBitrary <name>, <data>
        csv_data = ",".join(f"{v:.6f}" for v in data_array)
        self.instrument.write(f"SOURce{channel}:DATA:ARBitrary {name},{csv_data}")

        if sample_rate is not None:
            self.instrument.write(f"SOURce{channel}:FUNCtion:ARB:SRATe {sample_rate}")

    def set_arb_waveform(self, name, channel=1):
        """
        Select an arbitrary waveform previously downloaded or built-in
        (SOURce[1|2]:FUNCtion:ARBitrary <name>).
        """
        if not name or not isinstance(name, str):
            raise ValueError("Arbitrary waveform name must be a non-empty string")
        self.instrument.write(f"SOURce{channel}:FUNCtion:ARBitrary {name}")
        self.instrument.write(f"SOURce{channel}:FUNCtion ARB")

    # -------------------------------------------------------------------------
    # Trigger Functions
    # -------------------------------------------------------------------------

    def set_trigger_source(self, channel=1, trigger_source=None):
        """
        Set trigger source (TRIGger[1|2]:SOURce {IMMediate|EXTernal|TIMer|BUS}).
        """
        if trigger_source is None:
            raise ValueError("trigger_source must be provided")
        src_map = {
            'imm': 'IMM', 'int': 'IMM', 'immediate': 'IMM', 'internal': 'IMM',
            'ext': 'EXT', 'external': 'EXT',
            'man': 'BUS', 'manual': 'BUS', 'bus': 'BUS',
            'tim': 'TIM', 'timer': 'TIM'
        }
        src = src_map.get(str(trigger_source).lower(), str(trigger_source).upper())
        self.instrument.write(f"TRIG{channel}:SOUR {src}")

    def set_trigger_slope(self, channel=1, trigger_slope=None):
        """
        Set external trigger slope (TRIGger[1|2]:SLOPe {POSitive|NEGative}).
        """
        if trigger_slope is None:
            raise ValueError("trigger_slope must be provided")
        token = "POS" if str(trigger_slope).lower().startswith("pos") else "NEG"
        self.instrument.write(f"TRIG{channel}:SLOP {token}")

    def set_trigger_mode(self, channel=1, trigger_mode=None):
        """
        Set burst trigger mode (SOURce[1|2]:BURSt:MODE {TRIGgered|GATed}).
        Maps 'EDGE' -> 'TRIG' and 'LEV' -> 'GAT'.
        """
        if trigger_mode is None:
            raise ValueError("trigger_mode must be provided")
        token = "TRIG" if str(trigger_mode).lower() in ("edge", "trig", "triggered") else "GAT"
        self.instrument.write(f"SOUR{channel}:BURS:MODE {token}")

    def set_trigger_level(self, channel=1, trigger_level=None):
        """
        Set the trigger level / input threshold in Volts (TRIGger[1|2]:LEVel <volts>).
        """
        if trigger_level is None:
            raise ValueError("trigger_level must be provided")
        self.instrument.write(f"TRIG{channel}:LEV {trigger_level}")

    def output_trigger(self):
        """
        Issue a manual/software bus trigger to all armed channels (*TRG).
        """
        self.instrument.write("*TRG")

    def configure_trigger(self, channel=1, trigger_source=None, trigger_level=None,
                          trigger_slope=None, trigger_mode=None):
        """
        Convenience method to configure trigger parameters on the selected channel.
        """
        if trigger_source is not None:
            self.set_trigger_source(channel, trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(channel, trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(channel, trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(channel, trigger_mode)

    # -------------------------------------------------------------------------
    # Burst Functions
    # -------------------------------------------------------------------------

    def set_burst_mode(self, channel=1, burst_mode=None):
        """Set burst mode: 'TRIG' (triggered), 'GAT' (gated), or 'INF' (infinite)."""
        if burst_mode is None:
            raise ValueError("burst_mode must be provided")
        token = burst_mode.upper()
        if token == "INF":
            self.instrument.write(f"SOUR{channel}:BURS:MODE TRIG")
            self.instrument.write(f"SOUR{channel}:BURS:NCYC INF")
        elif token in ("TRIG", "TRIGGERED"):
            self.instrument.write(f"SOUR{channel}:BURS:MODE TRIG")
        elif token in ("GAT", "GATED"):
            self.instrument.write(f"SOUR{channel}:BURS:MODE GAT")
        else:
            self.instrument.write(f"SOUR{channel}:BURS:MODE {token}")

    def set_burst_count(self, channel=1, burst_count=None):
        """Set number of cycles per burst (SOURce[1|2]:BURSt:NCYCles {<count>|INFinity})."""
        if burst_count is None:
            raise ValueError("burst_count must be provided")
        val = "INF" if (burst_count == float("inf") or str(burst_count).upper() in ("INF", "INFINITY")) else burst_count
        self.instrument.write(f"SOUR{channel}:BURS:NCYC {val}")

    def configure_burst(self, channel=1, burst_mode=None, burst_count=None, phase=None, period=None):
        """Configure burst mode and parameters, enabling burst state."""
        if burst_mode is not None:
            self.set_burst_mode(channel, burst_mode)
        if burst_count is not None:
            self.set_burst_count(channel, burst_count)
        if phase is not None:
            self.instrument.write(f"SOUR{channel}:BURS:PHAS {phase}")
        if period is not None:
            self.instrument.write(f"SOUR{channel}:BURS:INT:PER {period}")
        self.instrument.write(f"SOUR{channel}:BURS:STAT ON")

    # -------------------------------------------------------------------------
    # Sweep Functions
    # -------------------------------------------------------------------------

    def set_sweep_mode(self, channel=1, sweep_mode=None):
        """Set sweep mode (SOURce[1|2]:SWEep:SPACing {LINear|LOGarithmic})."""
        if sweep_mode is None:
            raise ValueError("sweep_mode must be provided")
        token = "LOG" if sweep_mode.upper().startswith("LOG") else "LIN"
        self.instrument.write(f"SOUR{channel}:SWE:SPAC {token}")

    def set_sweep_start_freq(self, channel=1, start_freq=None):
        """Set sweep start frequency in Hz (SOURce[1|2]:FREQuency:STARt <freq>)."""
        if start_freq is None:
            raise ValueError("start_freq must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ:STAR {start_freq}")

    def set_sweep_stop_freq(self, channel=1, stop_freq=None):
        """Set sweep stop frequency in Hz (SOURce[1|2]:FREQuency:STOP <freq>)."""
        if stop_freq is None:
            raise ValueError("stop_freq must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ:STOP {stop_freq}")

    def set_sweep_time(self, channel=1, sweep_time=None):
        """Set sweep time in seconds (SOURce[1|2]:SWEep:TIME <seconds>)."""
        if sweep_time is None:
            raise ValueError("sweep_time must be provided")
        self.instrument.write(f"SOUR{channel}:SWE:TIME {sweep_time}")

    def configure_sweep(self, channel=1, start_freq=None, stop_freq=None, sweep_time=None, mode=None):
        """Configure sweep parameters and enable sweep state."""
        if start_freq is not None:
            self.set_sweep_start_freq(channel, start_freq)
        if stop_freq is not None:
            self.set_sweep_stop_freq(channel, stop_freq)
        if sweep_time is not None:
            self.set_sweep_time(channel, sweep_time)
        if mode is not None:
            self.set_sweep_mode(channel, mode)
        self.instrument.write(f"SOUR{channel}:SWE:STAT ON")

    # -------------------------------------------------------------------------
    # Modulation Functions
    # -------------------------------------------------------------------------

    def set_modulation_type(self, channel=1, mod_type=None):
        """Set modulation type: 'AM', 'FM', 'PM', 'FSK', 'PWM'."""
        if mod_type is None:
            raise ValueError("mod_type must be provided")
        token = mod_type.upper()
        # Disable others, enable selected
        for t in ['AM', 'FM', 'PM', 'FSK', 'PWM']:
            cmd_name = 'FSKey' if t == 'FSK' else t
            if t == token:
                self.instrument.write(f"SOUR{channel}:{cmd_name}:STAT ON")
            else:
                self.instrument.write(f"SOUR{channel}:{cmd_name}:STAT OFF")

    def set_modulation_depth(self, channel=1, depth=None):
        """Set AM modulation depth in percent (SOURce[1|2]:AM:DEPTh <percent>)."""
        if depth is None:
            raise ValueError("depth must be provided")
        self.instrument.write(f"SOUR{channel}:AM:DEPT {depth}")

    def set_modulation_frequency(self, channel=1, frequency=None):
        """Set internal modulating frequency in Hz."""
        if frequency is None:
            raise ValueError("frequency must be provided")
        self.instrument.write(f"SOUR{channel}:AM:INT:FREQ {frequency}")

    def set_modulation_source(self, channel=1, source=None):
        """Set modulation source: 'INT' or 'EXT'."""
        if source is None:
            raise ValueError("source must be provided")
        token = "EXT" if source.lower().startswith("ext") else "INT"
        self.instrument.write(f"SOUR{channel}:AM:SOUR {token}")

    def configure_modulation(self, channel=1, mod_type=None, depth=None, frequency=None, source=None):
        """Configure modulation type, depth, frequency, and source."""
        if mod_type is not None:
            self.set_modulation_type(channel, mod_type)
        if depth is not None:
            self.set_modulation_depth(channel, depth)
        if frequency is not None:
            self.set_modulation_frequency(channel, frequency)
        if source is not None:
            self.set_modulation_source(channel, source)
