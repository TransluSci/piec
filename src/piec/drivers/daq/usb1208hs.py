"""Driver family for the USB-1208HS, USB-1208HS-2AO, and -4AO."""

import time
import math
import threading
from ctypes import c_double

from ..digilent import Digilent
from .daq import Daq

try:
    from mcculw.enums import (
        AnalogInputMode,
        DigitalIODirection,
        DigitalPortType,
        FunctionType,
        ScanOptions,
        Status,
        TimerIdleState,
        ULRange,
    )
except ImportError:
    # Digilent raises a contextual ImportError when physical hardware is opened.
    AnalogInputMode = None
    DigitalIODirection = None
    DigitalPortType = None
    FunctionType = None
    ScanOptions = None
    Status = None
    TimerIdleState = None
    ULRange = None


class USB1208HS(Digilent, Daq):
    """One driver for all three USB-1208HS family models.

    The device provides eight single-ended or four differential analog inputs,
    model-specific fixed-range analog outputs, and 16 individually configurable
    digital I/O lines. Analog scan data is requested from Universal Library in scaled
    engineering units so the driver does not make assumptions about the
    converter's 12-bit single-ended or 13-bit differential data encoding.
    """

    AUTODETECT_ID = [
        "USB-1208HS",
        "USB-1208HS-2AO",
        "USB-1208HS-4AO",
    ]

    ai_channel = list(range(8))
    ai_range = [
        (-20.0, 20.0),
        (-10.0, 10.0),
        (-5.0, 5.0),
        (-2.5, 2.5),
        (0.0, 10.0),
    ]
    ai_mode = ["SE", "DIFF"]
    ai_sample_rate = (1, 1_000_000)

    # The class advertises the family maximum for validation and virtual use.
    # A physical instance replaces this with its exact model capability after
    # reading IDN in __init__.
    ao_channel = [0, 1, 2, 3]
    ao_range = [(-10.0, 10.0)]
    ao_sample_rate = (1, 1_000_000)

    dio_channel = list(range(16))
    dio_direction = ["I", "O"]

    def get_trigger_pulse_capabilities(self):
        capabilities = super().get_trigger_pulse_capabilities()
        # 50% duty: 25 ns--50 s high/low widths stay within the documented
        # 0.0094 Hz--20 MHz timer frequency range for all USB-1208HS variants.
        capabilities['timer'] = {'channels': [0], 'timing': 'hardware',
                                  'min_width': 25e-9, 'max_width': 50.0}
        return capabilities

    def send_trigger_pulse(self, channel, pulse_width, active_high=True, *,
                           resource='digital', require_hardware_timing=False, cancel_event=None):
        """Use TMR timer 0 for hardware pulses, or the base DIO software fallback.

        Universal Library pulse_out_start returns quantized frequency/duty/delay.
        Exactly one pulse is requested. Software controls launch latency; hardware
        controls the pulse width. This does not arm or synchronize an AO/AI scan.
        The TMR terminal must be reserved by the caller for the duration of this call.
        See docs/daq_trigger_output.md for the manufacturer references.
        """
        if resource == 'digital':
            return super().send_trigger_pulse(channel, pulse_width, active_high,
                resource=resource, require_hardware_timing=require_hardware_timing,
                cancel_event=cancel_event)
        self.validate_trigger_pulse(channel, pulse_width, active_high,
            resource=resource, require_hardware_timing=require_hardware_timing)
        lock = self.__dict__.setdefault('_trigger_pulse_lock', threading.Lock())
        with lock:
            self._wait_trigger_pulse(0, cancel_event)
            idle = TimerIdleState.LOW if active_high else TimerIdleState.HIGH
            try:
                frequency, duty, delay = self.ul.pulse_out_start(
                    self.board_num, channel, 0.5 / pulse_width, 0.5,
                    pulse_count=1, initial_delay=0, idle_state=idle)
                if (not all(math.isfinite(v) for v in (frequency, duty, delay))
                        or not 0.0094 <= frequency <= 20_000_000
                        or not 0 < duty < 1 or not 0 <= delay <= 107.37):
                    raise ValueError('Invalid timer settings returned by Universal Library')
                # Wait a complete actual period, rather than stopping halfway
                # through the programmed pulse. Cancellation still stops early.
                self._wait_trigger_pulse(delay + 1.0 / frequency, cancel_event)
            finally:
                self.ul.pulse_out_stop(self.board_num, channel)
        return {'resource': resource, 'channel': int(channel), 'timing': 'hardware',
                'requested_pulse_width': float(pulse_width),
                'programmed_pulse_width': duty / frequency, 'active_high': active_high}

    _AO_CHANNEL_COUNT_BY_MODEL = {
        "USB-1208HS": 0,
        "USB-1208HS-2AO": 2,
        "USB-1208HS-4AO": 4,
    }

    _AI_RANGES_BY_MODE = {
        "se": {
            (-10.0, 10.0): "BIP10VOLTS",
            (-5.0, 5.0): "BIP5VOLTS",
            (-2.5, 2.5): "BIP2PT5VOLTS",
            (0.0, 10.0): "UNI10VOLTS",
        },
        "diff": {
            (-20.0, 20.0): "BIP20VOLTS",
            (-10.0, 10.0): "BIP10VOLTS",
            (-5.0, 5.0): "BIP5VOLTS",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_model_capabilities(self.idn())
        self._ai_ranges = {}
        self._ai_sample_rates = {}
        self._ao_sample_rates = {}
        self._selected_ai_channel = 0
        self._selected_ao_channel = self.ao_channel[0] if self.ao_channel else None
        self._selected_dio_channel = 0
        self._active_memhandle = None
        self.set_input_mode("SE")

    def _configure_model_capabilities(self, identity):
        """Set instance capabilities from the most-specific model in IDN."""
        matches = [
            model for model in self._AO_CHANNEL_COUNT_BY_MODEL if model in identity
        ]
        if not matches:
            raise ValueError(
                f"Unsupported USB-1208HS identity {identity!r}; expected one of "
                f"{list(self._AO_CHANNEL_COUNT_BY_MODEL)}"
            )

        self.model = max(matches, key=len)
        count = self._AO_CHANNEL_COUNT_BY_MODEL[self.model]
        self.ao_channel = list(range(count))
        if count:
            self.ao_range = [(-10.0, 10.0)]
            self.ao_sample_rate = (1, 1_000_000)
        else:
            self.ao_range = []
            self.ao_sample_rate = (None, None)

    @staticmethod
    def _normalize_range(voltage_range):
        try:
            low, high = voltage_range
        except (TypeError, ValueError) as error:
            raise ValueError("range must be a two-value (minimum, maximum) pair") from error
        return float(low), float(high)

    def _validate_ai_channel(self, channel):
        valid_channels = range(8) if self._ai_mode == "se" else range(4)
        if channel not in valid_channels:
            raise ValueError(
                f"AI channel {channel} is invalid in {self._ai_mode.upper()} mode; "
                f"valid channels are {list(valid_channels)}"
            )

    @staticmethod
    def _validate_channel(channel, valid_channels, channel_type):
        if channel not in valid_channels:
            raise ValueError(
                f"{channel_type} channel {channel} is invalid; "
                f"valid channels are {valid_channels}"
            )

    def _ai_ul_range(self, channel):
        voltage_range = self._ai_ranges.get(channel, (-10.0, 10.0))
        enum_name = self._AI_RANGES_BY_MODE[self._ai_mode][voltage_range]
        return getattr(ULRange, enum_name)

    @staticmethod
    def _digital_port(channel):
        if channel < 8:
            return DigitalPortType.FIRSTPORTA, channel
        return DigitalPortType.FIRSTPORTB, channel - 8

    def set_input_mode(self, ai_mode):
        """Set the global analog-input wiring mode to ``SE`` or ``DIFF``."""
        mode = str(ai_mode).lower()
        modes = {
            "se": AnalogInputMode.SINGLE_ENDED,
            "diff": AnalogInputMode.DIFFERENTIAL,
        }
        if mode not in modes:
            raise ValueError("ai_mode must be 'SE' or 'DIFF'")

        self.ul.a_input_mode(self.board_num, modes[mode])
        self._ai_mode = mode
        valid_channels = set(range(8) if mode == "se" else range(4))
        valid_ranges = self._AI_RANGES_BY_MODE[mode]
        self.ai_channel = sorted(valid_channels)
        self.ai_range = list(valid_ranges)
        self._ai_ranges = {
            channel: voltage_range
            for channel, voltage_range in getattr(self, "_ai_ranges", {}).items()
            if channel in valid_channels and voltage_range in valid_ranges
        }

    def set_ai_range(self, ai_channel, ai_range):
        """Select a supported input range for one analog-input channel."""
        self._validate_ai_channel(ai_channel)
        voltage_range = self._normalize_range(ai_range)
        valid_ranges = self._AI_RANGES_BY_MODE[self._ai_mode]
        if voltage_range not in valid_ranges:
            raise ValueError(
                f"AI range {voltage_range} is invalid in {self._ai_mode.upper()} "
                f"mode; valid ranges are {list(valid_ranges)}"
            )
        self._ai_ranges[ai_channel] = voltage_range

    def set_ao_range(self, ao_channel, ao_range):
        """Validate the USB-1208HS AO model's fixed output range."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        voltage_range = self._normalize_range(ao_range)
        if voltage_range != (-10.0, 10.0):
            raise ValueError(f"{self.model} analog outputs have a fixed +/-10 V range")

    def read_AI(self, channel):
        """Read one analog-input sample and return volts."""
        self._validate_ai_channel(channel)
        return float(self.ul.v_in(self.board_num, channel, self._ai_ul_range(channel)))

    def read_AI_scan(self, channel, points, rate):
        """Acquire a finite, hardware-paced single-channel scan in volts."""
        self._validate_ai_channel(channel)
        if not isinstance(points, int) or isinstance(points, bool) or points <= 0:
            raise ValueError("points must be a positive integer")
        if not 1 <= rate <= 1_000_000:
            raise ValueError("rate must be between 1 S/s and 1,000,000 S/s")

        memhandle = self.ul.scaled_win_buf_alloc(points)
        if not memhandle:
            raise MemoryError("Universal Library could not allocate the AI scan buffer")

        try:
            options = ScanOptions.BACKGROUND | ScanOptions.SCALEDATA
            actual_rate = self.ul.a_in_scan(
                self.board_num,
                channel,
                channel,
                points,
                int(rate),
                self._ai_ul_range(channel),
                memhandle,
                options,
            )
            self._last_ai_scan_rate = actual_rate

            timeout_at = time.monotonic() + points / float(rate) + 5.0
            while True:
                status, _, _ = self.ul.get_status(
                    self.board_num, FunctionType.AIFUNCTION
                )
                if status == Status.IDLE:
                    break
                if time.monotonic() >= timeout_at:
                    raise TimeoutError(f"{self.model} analog-input scan timed out")
                time.sleep(0.01)

            values = (c_double * points)()
            self.ul.scaled_win_buf_to_array(memhandle, values, 0, points)
            return list(values)
        finally:
            try:
                self.ul.stop_background(self.board_num, FunctionType.AIFUNCTION)
            except Exception:
                # Still release the Windows buffer if UL has already torn down
                # the completed background operation.
                pass
            self.ul.win_buf_free(memhandle)

    def write_AO(self, channel, data):
        """Write one or more software-paced voltage values to an AO channel."""
        self._validate_channel(channel, self.ao_channel, "AO")
        values = [data] if isinstance(data, (int, float)) else data
        for value in values:
            voltage = float(value)
            if not -10.0 <= voltage <= 10.0:
                raise ValueError("analog-output values must be within +/-10 V")
            self.ul.v_out(
                self.board_num, channel, ULRange.BIP10VOLTS, voltage
            )

    def write_waveform_scan(self, channel, data, sample_rate):
        """Start continuous hardware-paced waveform output on one AO channel."""
        self._validate_channel(channel, self.ao_channel, "AO")
        values = [float(value) for value in data]
        if not values:
            raise ValueError("data must contain at least one voltage value")
        if any(value < -10.0 or value > 10.0 for value in values):
            raise ValueError("analog-output values must be within +/-10 V")
        if not 1 <= sample_rate <= 1_000_000:
            raise ValueError("sample_rate must be between 1 and 1,000,000 S/s")

        self.stop_output()
        memhandle = self.ul.scaled_win_buf_alloc(len(values))
        if not memhandle:
            raise MemoryError("Universal Library could not allocate the AO scan buffer")

        try:
            source = (c_double * len(values))(*values)
            self.ul.scaled_win_array_to_buf(source, memhandle, 0, len(values))
            options = (
                ScanOptions.BACKGROUND
                | ScanOptions.CONTINUOUS
                | ScanOptions.SCALEDATA
            )
            actual_rate = self.ul.a_out_scan(
                self.board_num,
                channel,
                channel,
                len(values),
                int(sample_rate),
                ULRange.BIP10VOLTS,
                memhandle,
                options,
            )
        except Exception:
            self.ul.win_buf_free(memhandle)
            raise

        self._active_memhandle = memhandle
        self._last_ao_scan_rate = actual_rate
        return actual_rate

    def set_dio_direction(self, dio_channel, dio_direction):
        """Configure one DIO line as input (``I``) or output (``O``)."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        direction = str(dio_direction).lower()
        directions = {
            "i": DigitalIODirection.IN,
            "o": DigitalIODirection.OUT,
        }
        if direction not in directions:
            raise ValueError("dio_direction must be 'I' or 'O'")
        port, bit = self._digital_port(dio_channel)
        self.ul.d_config_bit(self.board_num, port, bit, directions[direction])

    def read_DI(self, channel):
        """Read one digital I/O line as integer 0 or 1."""
        self._validate_channel(channel, self.dio_channel, "DIO")
        port, bit = self._digital_port(channel)
        return int(self.ul.d_bit_in(self.board_num, port, bit))

    def write_DO(self, channel, data):
        """Write one or more software-paced states to a digital I/O line."""
        self._validate_channel(channel, self.dio_channel, "DIO")
        values = [data] if isinstance(data, (int, bool)) else data
        port, bit = self._digital_port(channel)
        for value in values:
            if value not in (0, 1, False, True):
                raise ValueError("digital-output values must be 0/1 or False/True")
            self.ul.d_bit_out(self.board_num, port, bit, int(bool(value)))

    # Daq interface adapters. Selection and sample-rate methods retain settings
    # for later reads/writes because Universal Library receives these values at
    # operation time rather than through separate configuration commands.
    def set_AI_channel(self, channel):
        self._validate_ai_channel(channel)
        self._selected_ai_channel = channel

    def set_AI_range(self, channel, range):
        self.set_ai_range(channel, range)

    def set_AI_sample_rate(self, channel, sample_rate):
        self._validate_ai_channel(channel)
        if not 1 <= sample_rate <= 1_000_000:
            raise ValueError("sample_rate must be between 1 and 1,000,000 S/s")
        self._ai_sample_rates[channel] = sample_rate

    def configure_AI_channel(self, channel, range=None, sample_rate=None):
        self.set_AI_channel(channel)
        if range is not None:
            self.set_AI_range(channel, range)
        if sample_rate is not None:
            self.set_AI_sample_rate(channel, sample_rate)

    def set_AO_channel(self, channel):
        self._validate_channel(channel, self.ao_channel, "AO")
        self._selected_ao_channel = channel

    def set_AO_range(self, channel, range):
        self.set_ao_range(channel, range)

    def set_AO_sample_rate(self, channel, sample_rate):
        self._validate_channel(channel, self.ao_channel, "AO")
        if not 1 <= sample_rate <= 1_000_000:
            raise ValueError("sample_rate must be between 1 and 1,000,000 S/s")
        self._ao_sample_rates[channel] = sample_rate

    def configure_AO_channel(self, channel, range=None, sample_rate=None):
        self.set_AO_channel(channel)
        if range is not None:
            self.set_AO_range(channel, range)
        if sample_rate is not None:
            self.set_AO_sample_rate(channel, sample_rate)

    def set_DIO_channel(self, channel):
        self._validate_channel(channel, self.dio_channel, "DIO")
        self._selected_dio_channel = channel

    def set_DIO_mode(self, channel, mode):
        self.set_dio_direction(channel, mode)

    def configure_DIO_channel(self, channel, mode, sample_rate=None):
        self.set_DIO_channel(channel)
        self.set_DIO_mode(channel, mode)
        if sample_rate is not None:
            self.set_DIO_sample_rate(channel, sample_rate)

    def set_DI_channel(self, channel):
        self.set_DIO_channel(channel)

    def configure_DI_channel(self, channel, sample_rate=None):
        self.set_DI_channel(channel)
        self.set_DIO_mode(channel, "I")
        if sample_rate is not None:
            self.set_DI_sample_rate(channel, sample_rate)

    def set_DO_channel(self, channel):
        self.set_DIO_channel(channel)

    def configure_DO_channel(self, channel, sample_rate=None):
        self.set_DO_channel(channel)
        self.set_DIO_mode(channel, "O")
        if sample_rate is not None:
            self.set_DO_sample_rate(channel, sample_rate)

    def quick_read(self):
        return self.read_AI(self._selected_ai_channel)

    def read_data(self, channel):
        return self.read_AI(channel)
