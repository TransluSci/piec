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
        """
        All awgs must be able to output something, so therefore we need a method to turn the output on for the selected channel.

        Args:
            channel (int): The channel to output on
            on (bool): Whether to turn the output on or off

        Notes:
            Writes OUTP<channel> ON or OFF. This switches the output without
            configuring the waveform.
            The channel defaults to 1; use a channel available on the connected model.
        """
        state = "ON" if on else "OFF"
        self.instrument.write(f"OUTP{channel} {state}")

    def set_load_impedance(self, channel=1, load_impedance=None):
        """
        Sets the load impedance of the waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the load impedance on
            load_impedance (float): The load impedance of the waveform in ohms

        Notes:
            Writes OUTP<channel>:LOAD. With automatic parameter checking disabled,
            float("inf"), "INF", and "INFINITY" select INF. With checking enabled,
            the declared numeric load_impedance limits apply.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If load_impedance is None.
        """
        if load_impedance is None:
            raise ValueError("load_impedance must be provided")

        if load_impedance == float("inf") or str(load_impedance).upper() in ("INF", "INFINITY"):
            self.instrument.write(f"OUTP{channel}:LOAD INF")
        else:
            self.instrument.write(f"OUTP{channel}:LOAD {load_impedance}")

    def set_polarity(self, channel=1, polarity=None):
        """
        Sets the polarity of the waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the polarity on
            polarity (str): The polarity of the waveform

        Notes:
            Writes OUTP<channel>:POL NORM for "NORM"/"NORMAL" and INV otherwise. Use
            the advertised NORM/INV values.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If polarity is None.
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
        Sets the built_in waveform to be generated on the selected channel.

        Args:
            channel (int): The channel to set the waveform on
            waveform (str): The waveform to be generated

        Notes:
            Maps the common USER waveform to the instrument ARB token and writes
            SOUR<channel>:FUNC. Other waveform names are uppercased.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If waveform is None.
        """
        if waveform is None:
            raise ValueError("waveform must be provided")
        token = "ARB" if waveform.lower() in ("user", "arb") else waveform.upper()
        self.instrument.write(f"SOUR{channel}:FUNC {token}")

    def set_frequency(self, channel=1, frequency=None):
        """
        Sets the frequency of the waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the frequency on
            frequency (float): The frequency of the waveform in Hz

        Notes:
            Writes SOUR<channel>:FREQ. Advertised frequency limits depend on the
            selected waveform.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If frequency is None.
        """
        if frequency is None:
            raise ValueError("frequency must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ {frequency}")

    def set_amplitude(self, channel=1, amplitude=None):
        """
        Sets the amplitude of the waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the amplitude on
            amplitude (float): The amplitude of the waveform in volts (usually Vpp but use instrument default)

        Notes:
            Writes SOUR<channel>:VOLT without changing the voltage-unit setting. Use
            the instrument's active amplitude units; the declared limits assume Vpp
            into 50 ohms.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If amplitude is None.
        """
        if amplitude is None:
            raise ValueError("amplitude must be provided")
        self.instrument.write(f"SOUR{channel}:VOLT {amplitude}")

    def set_offset(self, channel=1, offset=None):
        """
        Sets the offset of the waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the offset on
            offset (float): The offset of the waveform in volts

        Notes:
            Writes SOUR<channel>:VOLT:OFFS.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If offset is None.
        """
        if offset is None:
            raise ValueError("offset must be provided")
        self.instrument.write(f"SOUR{channel}:VOLT:OFFS {offset}")

    def set_phase(self, channel=1, phase=None):
        """
        Sets the phase offset of the waveform on the selected channel.

        Args:
            channel (int): The channel
            phase (float): Phase offset in degrees (-360 to +360)

        Notes:
            Writes SOUR<channel>:PHAS. This driver advertises -360 to +360 degrees.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If phase is None.
        """
        if phase is None:
            raise ValueError("phase must be provided")
        self.instrument.write(f"SOUR{channel}:PHAS {phase}")

    def set_square_duty_cycle(self, channel=1, duty_cycle=None):
        """
        Sets the duty cycle of the square wave to be generated on the selected channel

        Args:
            channel (int): The channel to set the duty cycle on
            duty_cycle (float): The duty cycle of the waveform as a percentage (0-100)

        Notes:
            Writes SOUR<channel>:FUNC:SQU:DCYC. This driver advertises 0.01 to 99.99
            percent.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If duty_cycle is None.
        """
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:SQU:DCYC {duty_cycle}")

    def set_ramp_symmetry(self, channel=1, symmetry=None):
        """
        Sets the symmetry of the ramp waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the symmetry on
            symmetry (float): The symmetry of the waveform as a percentage (0-100)

        Notes:
            Writes SOUR<channel>:FUNC:RAMP:SYMM.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If symmetry is None.
        """
        if symmetry is None:
            raise ValueError("symmetry must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:RAMP:SYMM {symmetry}")

    # -------------------------------------------------------------------------
    # Pulse Waveform Functions
    # -------------------------------------------------------------------------

    def set_pulse_period(self, channel=1, pulse_period=None):
        """
        Sets the pulse period on the selected channel.

        Args:
            channel (int): The channel to set the pulse period on. Defaults to 1.
            pulse_period (float): The pulse period in seconds; must be provided.

        Notes:
            Writes SOUR<channel>:FUNC:PULS:PER. This driver advertises
            33.3 ns to 1,000,000 s.

        Raises:
            ValueError: If pulse_period is None.
        """
        if pulse_period is None:
            raise ValueError("pulse_period must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:PER {pulse_period}")

    def set_pulse_width(self, channel=1, pulse_width=None):
        """
        Sets the pulse width of the waveform to be generated on the selected channel
        Useful for pulses

        Args:
            channel (int): The channel to set the pulse width on
            pulse_width (float): The pulse width of the waveform in seconds

        Notes:
            Writes SOUR<channel>:FUNC:PULS:WIDT. This driver advertises 16 ns to
            1,000,000 s; hardware may impose additional constraints based on period
            and edge times.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If pulse_width is None.
        """
        if pulse_width is None:
            raise ValueError("pulse_width must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:WIDT {pulse_width}")

    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        """
        Sets the duty cycle of the pulse to be generated on the selected channel

        Args:
            channel (int): The channel to set the duty cycle on
            duty_cycle (float): The duty cycle of the pulse as a percentage (0-100)

        Notes:
            Writes SOUR<channel>:FUNC:PULS:DCYC.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If duty_cycle is None.
        """
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:DCYC {duty_cycle}")

    def set_pulse_edge_time(self, channel=1, edge_time=None):
        """
        Sets the pulse transition time on the selected channel.

        Args:
            channel (int): The channel to set the transition time on. Defaults to 1.
            edge_time (float): The transition time in seconds; must be provided.

        Notes:
            Writes the unsuffixed SOUR<channel>:FUNC:PULS:TRAN command.
            Use set_pulse_rise_time and set_pulse_fall_time to address the
            leading and trailing transitions explicitly. This driver advertises
            8.4 ns to 1 microsecond.

        Raises:
            ValueError: If edge_time is None.
        """
        if edge_time is None:
            raise ValueError("edge_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN {edge_time}")

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        """
        Sets the rise time of the waveform to be generated on the selected channel
        Useful for pulses

        Args:
            channel (int): The channel to set the rise time on
            rise_time (float): The rise time of the waveform in seconds

        Notes:
            Writes SOUR<channel>:FUNC:PULS:TRAN:LEAD. This driver advertises 8.4 ns
            to 1 microsecond.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If rise_time is None.
        """
        if rise_time is None:
            raise ValueError("rise_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:LEAD {rise_time}")

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        """
        Sets the fall time of the waveform to be generated on the selected channel
        Useful for pulses

        Args:
            channel (int): The channel to set the fall time on
            fall_time (float): The fall time of the waveform in seconds

        Notes:
            Writes SOUR<channel>:FUNC:PULS:TRAN:TRA. This driver advertises 8.4 ns
            to 1 microsecond.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If fall_time is None.
        """
        if fall_time is None:
            raise ValueError("fall_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:TRA {fall_time}")

    def configure_pulse(self, channel=1, pulse_width=None,
                        rise_time=None, fall_time=None, duty_cycle=None):
        """
        Configures the pulse waveform on the selected channel. Calls the set_pulse_width, set_pulse_rise_time, set_pulse_duty_cycle and set_pulse_fall_time functions to configure the pulse waveform

        Args:
            channel (int): The channel to configure the pulse waveform on
            pulse_width (float): The pulse width of the waveform in seconds
            rise_time (float): The rise time of the waveform in seconds
            fall_time (float): The fall time of the waveform in seconds
            duty_cycle (float): The duty cycle of the pulse as a percentage (0-100)

        Notes:
            Selects PULS first, then applies non-None width, rise time, fall time,
            and duty cycle in that order. None leaves the corresponding setting
            unchanged.
            The channel defaults to 1; use a channel available on the connected model.
        """
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

    def create_arb_waveform(self, channel, name, data):
        """
        Creates an arbitrary waveform on the selected channel and downloads it to instrument memory.

        Args:
            channel (int): The channel to create the arbitrary waveform on
            name (str): The name of the arbitrary waveform
            data (list or ndarray): The data points of the arbitrary waveform

        Notes:
            Requires an explicit, nonempty name containing only alphanumeric
            characters and underscores. No default name is generated and no
            overwrite confirmation is requested. The method converts data to
            floating point, checks 8 to 1,000,000 points and values between -1.0 and
            +1.0, then sends SOURce<channel>:DATA:ARBitrary with comma-separated
            values formatted to six decimal places. Uploading does not select the
            waveform or enable output; call set_arb_waveform separately. String
            arguments, including name, are lowercased by the driver framework.

        Raises:
            ValueError: If the name is invalid, the point count is out of range,
                or data contains values outside [-1.0, 1.0].
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

    def set_arb_waveform(self, channel, name):
        """
        Sets the arbitrary waveform to be generated on the selected channel

        Args:
            channel (int): The channel to set the arbitrary waveform on
            name (str): The name of the arbitrary waveform to be set

        Notes:
            Requires a nonempty name. Writes SOURce<channel>:FUNCtion:ARBitrary
            <name>, then SOURce<channel>:FUNCtion ARB. Does not enable channel
            output. Names are lowercased by the driver framework.

        Raises:
            ValueError: If name is not a nonempty string.
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
        Sets the trigger source for the selected channel

        Args:
            channel (int): The channel to set the trigger source on
            trigger_source (str): The trigger source, e.g., 'internal', 'external', 'manual'

        Notes:
            Writes TRIG<channel>:SOUR. INT/IMM map to IMM, EXT to EXT, MAN/BUS to
            BUS, and TIM to TIM. With automatic checking disabled, long-form aliases
            are also mapped and unknown values are passed through uppercased.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If trigger_source is None.
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
        Sets the trigger slope for the selected channel

        Args:
            channel (int): The channel to set the trigger slope on
            trigger_slope (str): The trigger slope, 'POS' (rising) or 'NEG' (falling)

        Notes:
            Writes TRIG<channel>:SLOP. Use POS or NEG. With automatic checking
            disabled, strings starting with "pos" select POS and all other supplied
            values select NEG.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If trigger_slope is None.
        """
        if trigger_slope is None:
            raise ValueError("trigger_slope must be provided")
        token = "POS" if str(trigger_slope).lower().startswith("pos") else "NEG"
        self.instrument.write(f"TRIG{channel}:SLOP {token}")

    def set_trigger_mode(self, channel=1, trigger_mode=None):
        """
        Sets the trigger mode for the selected channel (aka trigger type)

        Args:
            channel (int): The channel to set the trigger mode on
            trigger_mode (str): The trigger mode, e.g., 'EDGE'

        Notes:
            Writes SOUR<channel>:BURS:MODE. EDGE maps to TRIG and LEV to GAT. With
            automatic checking disabled, "trig"/"triggered" also select TRIG; other
            supplied values select GAT. This setter does not enable burst mode.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If trigger_mode is None.
        """
        if trigger_mode is None:
            raise ValueError("trigger_mode must be provided")
        token = "TRIG" if str(trigger_mode).lower() in ("edge", "trig", "triggered") else "GAT"
        self.instrument.write(f"SOUR{channel}:BURS:MODE {token}")

    def set_trigger_level(self, channel=1, trigger_level=None):
        """
        Sets the trigger level for the selected channel

        Args:
            channel (int): The channel to set the trigger level on
            trigger_level (float): The trigger level in volts

        Notes:
            Writes TRIG<channel>:LEV with the supplied voltage. This implementation
            does not explicitly check finiteness or impose trigger-level bounds.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If trigger_level is None.
        """
        if trigger_level is None:
            raise ValueError("trigger_level must be provided")
        self.instrument.write(f"TRIG{channel}:LEV {trigger_level}")

    def output_trigger(self):
        """
        Outputs the trigger signal for the awg. This is typically used to synchronize the output of the awg with other instruments or systems. Typically the same as manually triggering the awg from the front panel.

        Notes:
            Writes one device-wide *TRG command for channels already armed for bus
            triggering. It does not configure or enable output and does not
            independently select a channel.
        """
        self.instrument.write("*TRG")

    def configure_trigger(self, channel=1, trigger_source=None, trigger_level=None,
                          trigger_slope=None, trigger_mode=None):
        """
        Configures the trigger for the selected channel. Calls the set_trigger_source, set_trigger_level, set_trigger_slope, and set_trigger_mode functions to configure the trigger

        Args:
            channel (int): The channel to configure the trigger on
            trigger_source (str): The trigger source
            trigger_level (float): The trigger level in volts
            trigger_slope (str): The trigger slope
            trigger_mode (str): The trigger mode

        Notes:
            Applies non-None source, level, slope, and mode in that order. None
            leaves a setting unchanged. The method does not enable burst or channel
            output. Earlier writes are not rolled back if a later setter fails.
            The channel defaults to 1; use a channel available on the connected model.
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
        """
        Sets the burst mode type.

        Args:
            channel (int): The channel
            burst_mode (str): 'TRIG' (N-cycle on trigger), 'GAT' (gated), 'INF' (infinite)

        Notes:
            Writes SOUR<channel>:BURS:MODE. INF selects TRIG and also writes
            SOUR<channel>:BURS:NCYC INF. This setter does not enable burst state;
            configure_burst does.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If burst_mode is None.
        """
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
        """
        Sets the number of waveform cycles per burst trigger.

        Args:
            channel (int): The channel
            burst_count (int): Number of cycles per burst

        Notes:
            Writes SOUR<channel>:BURS:NCYC. With automatic checking disabled,
            float("inf"), "INF", and "INFINITY" map to INF. With checking enabled,
            the declared numeric burst_count limits apply.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If burst_count is None.
        """
        if burst_count is None:
            raise ValueError("burst_count must be provided")
        val = "INF" if (burst_count == float("inf") or str(burst_count).upper() in ("INF", "INFINITY")) else burst_count
        self.instrument.write(f"SOUR{channel}:BURS:NCYC {val}")

    def configure_burst(self, channel=1, burst_mode=None, burst_count=None):
        """
        Configures burst mode. Calls set_burst_mode and set_burst_count.

        Args:
            channel (int): The channel
            burst_mode (str): 'TRIG', 'GAT', or 'INF'
            burst_count (int): Number of cycles per burst

        Notes:
            Applies each non-None setting, then writes SOUR<channel>:BURS:STAT ON
            even when neither setting is supplied. It does not enable channel
            output.
            The channel defaults to 1; use a channel available on the connected model.
        """
        if burst_mode is not None:
            self.set_burst_mode(channel, burst_mode)
        if burst_count is not None:
            self.set_burst_count(channel, burst_count)
        self.instrument.write(f"SOUR{channel}:BURS:STAT ON")

    # -------------------------------------------------------------------------
    # Sweep Functions
    # -------------------------------------------------------------------------

    def set_sweep_mode(self, channel=1, sweep_mode=None):
        """
        Sets the sweep type (linear or logarithmic).

        Args:
            channel (int): The channel
            sweep_mode (str): 'LIN' or 'LOG'

        Notes:
            Writes SOUR<channel>:SWE:SPAC. Use LIN or LOG. With automatic checking
            disabled, values starting with "LOG" select LOG and other supplied
            values select LIN.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If sweep_mode is None.
        """
        if sweep_mode is None:
            raise ValueError("sweep_mode must be provided")
        token = "LOG" if sweep_mode.upper().startswith("LOG") else "LIN"
        self.instrument.write(f"SOUR{channel}:SWE:SPAC {token}")

    def set_sweep_start_freq(self, channel=1, start_freq=None):
        """
        Sets the sweep start frequency.

        Args:
            channel (int): The channel
            start_freq (float): Start frequency in Hz

        Notes:
            Writes SOUR<channel>:FREQ:STAR.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If start_freq is None.
        """
        if start_freq is None:
            raise ValueError("start_freq must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ:STAR {start_freq}")

    def set_sweep_stop_freq(self, channel=1, stop_freq=None):
        """
        Sets the sweep stop frequency.

        Args:
            channel (int): The channel
            stop_freq (float): Stop frequency in Hz

        Notes:
            Writes SOUR<channel>:FREQ:STOP.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If stop_freq is None.
        """
        if stop_freq is None:
            raise ValueError("stop_freq must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ:STOP {stop_freq}")

    def set_sweep_time(self, channel=1, sweep_time=None):
        """
        Sets the sweep duration.

        Args:
            channel (int): The channel
            sweep_time (float): Sweep time in seconds

        Notes:
            Writes SOUR<channel>:SWE:TIME.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If sweep_time is None.
        """
        if sweep_time is None:
            raise ValueError("sweep_time must be provided")
        self.instrument.write(f"SOUR{channel}:SWE:TIME {sweep_time}")

    def configure_sweep(self, channel=1, sweep_mode=None, start_freq=None, stop_freq=None, sweep_time=None):
        """
        Configures frequency sweep. Calls individual set_ methods.

        Args:
            channel (int): The channel
            sweep_mode (str): 'LIN' or 'LOG'
            start_freq (float): Start frequency in Hz
            stop_freq (float): Stop frequency in Hz
            sweep_time (float): Sweep time in seconds

        Notes:
            Applies non-None start frequency, stop frequency, sweep time, and sweep
            mode in that order, then writes SOUR<channel>:SWE:STAT ON. None leaves
            the corresponding setting unchanged. Channel output is not enabled by
            this method.
            The channel defaults to 1; use a channel available on the connected model.
        """
        if start_freq is not None:
            self.set_sweep_start_freq(channel, start_freq)
        if stop_freq is not None:
            self.set_sweep_stop_freq(channel, stop_freq)
        if sweep_time is not None:
            self.set_sweep_time(channel, sweep_time)
        if sweep_mode is not None:
            self.set_sweep_mode(channel, sweep_mode)
        self.instrument.write(f"SOUR{channel}:SWE:STAT ON")

    # -------------------------------------------------------------------------
    # Modulation Functions
    # -------------------------------------------------------------------------

    def set_modulation_type(self, channel=1, mod_type=None):
        """
        Sets the modulation type.

        Args:
            channel (int): The channel
            mod_type (str): 'AM', 'FM', 'PM', 'FSK', 'PWM'

        Notes:
            Enables the selected AM/FM/PM/FSK/PWM mode and disables the others using
            SOUR<channel>:<type>:STAT. FSK uses the FSKey command token. The other
            modulation setters in this implementation configure AM parameters only.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If mod_type is None.
        """
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
        """
        Sets the AM modulation depth.

        Args:
            channel (int): The channel
            depth (float): AM modulation depth as a percentage

        Notes:
            Writes SOUR<channel>:AM:DEPT. This implementation sets AM depth only; it
            does not configure FM deviation or other modulation types.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If depth is None.
        """
        if depth is None:
            raise ValueError("depth must be provided")
        self.instrument.write(f"SOUR{channel}:AM:DEPT {depth}")

    def set_modulation_frequency(self, channel=1, frequency=None):
        """
        Sets the modulating signal frequency.

        Args:
            channel (int): The channel
            frequency (float): Internal modulation frequency in Hz

        Notes:
            Writes SOUR<channel>:AM:INT:FREQ. This implementation configures the
            internal AM modulation frequency only.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If frequency is None.
        """
        if frequency is None:
            raise ValueError("frequency must be provided")
        self.instrument.write(f"SOUR{channel}:AM:INT:FREQ {frequency}")

    def set_modulation_source(self, channel=1, source=None):
        """
        Sets the modulation source.

        Args:
            channel (int): The channel
            source (str): 'INT' or 'EXT'

        Notes:
            Writes SOUR<channel>:AM:SOUR. Use INT or EXT. Strings starting with
            "ext" select EXT; other supplied values select INT. This implementation
            configures AM only.
            The channel defaults to 1; use a channel available on the connected model.

        Raises:
            ValueError: If source is None.
        """
        if source is None:
            raise ValueError("source must be provided")
        token = "EXT" if source.lower().startswith("ext") else "INT"
        self.instrument.write(f"SOUR{channel}:AM:SOUR {token}")

    def configure_modulation(self, channel=1, mod_type=None, depth=None, frequency=None, source=None):
        """
        Configures modulation. Calls individual set_ methods.

        Args:
            channel (int): The channel
            mod_type (str): 'AM', 'FM', 'PM', 'FSK', 'PWM'
            depth (float): AM modulation depth as a percentage
            frequency (float): Modulation frequency in Hz
            source (str): 'INT' or 'EXT'

        Notes:
            Applies non-None type, depth, frequency, and source in that order.
            Selecting a type enables that modulation and disables the others. Depth,
            frequency, and source setters configure AM even if another mod_type is
            selected. None leaves the corresponding setting unchanged.
            The channel defaults to 1; use a channel available on the connected model.
        """
        if mod_type is not None:
            self.set_modulation_type(channel, mod_type)
        if depth is not None:
            self.set_modulation_depth(channel, depth)
        if frequency is not None:
            self.set_modulation_frequency(channel, frequency)
        if source is not None:
            self.set_modulation_source(channel, source)
