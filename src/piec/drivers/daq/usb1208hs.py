"""Driver family for the USB-1208HS, USB-1208HS-2AO, and -4AO."""

import time
import math
import threading
from ctypes import c_double
import numpy as np

from ..mcc import MCC
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
    # MCC raises a contextual ImportError when physical hardware is opened.
    AnalogInputMode = None
    DigitalIODirection = None
    DigitalPortType = None
    FunctionType = None
    ScanOptions = None
    Status = None
    TimerIdleState = None
    ULRange = None


class USB1208HS(MCC, Daq):
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
    AI_STATUS = "generated"
    HARDWARE_TESTED = True  # Tested on physical hardware

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
        Manufacturer references:
        https://files.digilent.com/manuals/Mcculw_WebHelp/Users_Guide/Analog_Input_Boards/USB-1208HS_Series.htm
        https://files.digilent.com/manuals/Mcculw_WebHelp/Function_Reference/Ctr-python/pulse_out_start.htm
        https://files.digilent.com/manuals/Mcculw_WebHelp/Function_Reference/Ctr-python/pulse_out_stop.htm
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

    def read_AI(self, ai_channel):
        """Read one analog-input sample and return volts."""
        self._validate_ai_channel(ai_channel)
        return float(self.ul.v_in(self.board_num, ai_channel, self._ai_ul_range(ai_channel)))

    def read_AI_scan(self, ai_channel, points, rate):
        """Acquire a finite, hardware-paced scan of one or more analog inputs (int or list[int])."""
        channels = self._scan_channels(ai_channel)
        low, high = min(channels), max(channels)
        width = high - low + 1
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise ValueError("points must be a positive integer")
        minimum_rate, aggregate_rate = self.ai_sample_rate
        if not minimum_rate <= rate <= aggregate_rate / width:
            raise ValueError("Requested rate exceeds the input scan limits")
        ranges = [self._ai_ul_range(ch) for ch in range(low, high + 1)]
        if any(value != ranges[0] for value in ranges):
            raise ValueError("All inputs in the scan span must use the same range")
        total = points * width
        if total > 20_000_000:
            raise ValueError("Scan exceeds 20 million buffered samples; reduce points")

        handle = self.ul.scaled_win_buf_alloc(total)
        if not handle:
            raise MemoryError("Could not allocate analog input scan buffer")
        columns = np.asarray(channels) - low
        options = ScanOptions.BACKGROUND | ScanOptions.SCALEDATA
        idle = False
        try:
            actual_rate = self.ul.a_in_scan(
                self.board_num, low, high, total, int(rate), ranges[0], handle, options
            )
            self._last_ai_scan_rate = actual_rate
            deadline = time.monotonic() + points / actual_rate + 5.0
            while True:
                status, _, _ = self.ul.get_status(self.board_num, FunctionType.AIFUNCTION)
                idle = status == Status.IDLE
                if idle:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Analog input scan timed out")
                time.sleep(0.01)
            buffer = (c_double * total)()
            self.ul.scaled_win_buf_to_array(handle, buffer, 0, total)
            values = np.asarray(buffer).reshape(points, width)[:, columns]
            return self._scan_dataframe(channels, np.arange(points) / actual_rate, values, actual_rate)
        finally:
            try:
                self.ul.stop_background(self.board_num, FunctionType.AIFUNCTION)
            except Exception:
                if not idle:
                    raise
            finally:
                self.ul.win_buf_free(handle)


    def write_AO(self, ao_channel, data):
        """Write one or more software-paced voltage values to an AO channel."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        values = [data] if isinstance(data, (int, float)) else data
        for value in values:
            voltage = float(value)
            if not -10.0 <= voltage <= 10.0:
                raise ValueError("analog-output values must be within +/-10 V")
            self.ul.v_out(
                self.board_num, ao_channel, ULRange.BIP10VOLTS, voltage
            )

    def write_AO_scan(self, ao_channel, data, sample_rate):
        """Start continuous hardware-paced waveform output on one AO channel."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
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
                ao_channel,
                ao_channel,
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

    def stop_output(self):
        """Stop any active background AO scan and free its buffer."""
        try:
            self.ul.stop_background(self.board_num, FunctionType.AOFUNCTION)
        except Exception:
            pass
        if getattr(self, "_active_memhandle", None):
            try:
                self.ul.win_buf_free(self._active_memhandle)
            except Exception:
                pass
            self._active_memhandle = None

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

    def read_DI(self, dio_channel):
        """Read one digital I/O line as integer 0 or 1."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        port, bit = self._digital_port(dio_channel)
        return int(self.ul.d_bit_in(self.board_num, port, bit))

    def write_DO(self, dio_channel, data):
        """Write one or more software-paced states to a digital I/O line."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        values = [data] if isinstance(data, (int, bool)) else data
        port, bit = self._digital_port(dio_channel)
        for value in values:
            if value not in (0, 1, False, True):
                raise ValueError("digital-output values must be 0/1 or False/True")
            self.ul.d_bit_out(self.board_num, port, bit, int(bool(value)))

    # Daq interface adapters. Selection and sample-rate methods retain settings
    # for later reads/writes because Universal Library receives these values at
    # operation time rather than through separate configuration commands.
    def set_AI_channel(self, ai_channel):
        self._validate_ai_channel(ai_channel)
        self._selected_ai_channel = ai_channel

    def set_AI_range(self, ai_channel, range):
        self.set_ai_range(ai_channel, range)

    def set_AI_sample_rate(self, ai_channel, sample_rate):
        self._validate_ai_channel(ai_channel)
        if not 1 <= sample_rate <= 1_000_000:
            raise ValueError("sample_rate must be between 1 and 1,000,000 S/s")
        self._ai_sample_rates[ai_channel] = sample_rate

    def configure_AI_channel(self, ai_channel, range=None, sample_rate=None):
        self.set_AI_channel(ai_channel)
        if range is not None:
            self.set_AI_range(ai_channel, range)
        if sample_rate is not None:
            self.set_AI_sample_rate(ai_channel, sample_rate)

    def set_AO_channel(self, ao_channel):
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        self._selected_ao_channel = ao_channel

    def set_AO_range(self, ao_channel, range):
        self.set_ao_range(ao_channel, range)

    def set_AO_sample_rate(self, ao_channel, sample_rate):
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        if not 1 <= sample_rate <= 1_000_000:
            raise ValueError("sample_rate must be between 1 and 1,000,000 S/s")
        self._ao_sample_rates[ao_channel] = sample_rate

    def configure_AO_channel(self, ao_channel, range=None, sample_rate=None):
        self.set_AO_channel(ao_channel)
        if range is not None:
            self.set_AO_range(ao_channel, range)
        if sample_rate is not None:
            self.set_AO_sample_rate(ao_channel, sample_rate)

    def set_DIO_channel(self, dio_channel):
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        self._selected_dio_channel = dio_channel

    def set_DIO_mode(self, dio_channel, mode):
        self.set_dio_direction(dio_channel, mode)

    def configure_DIO_channel(self, dio_channel, mode, sample_rate=None):
        self.set_DIO_channel(dio_channel)
        self.set_DIO_mode(dio_channel, mode)
        if sample_rate is not None:
            self.set_DIO_sample_rate(dio_channel, sample_rate)

    def set_DI_channel(self, dio_channel):
        self.set_DIO_channel(dio_channel)

    def configure_DI_channel(self, dio_channel, sample_rate=None):
        self.set_DI_channel(dio_channel)
        self.set_DIO_mode(dio_channel, "I")
        if sample_rate is not None:
            self.set_DI_sample_rate(dio_channel, sample_rate)

    def set_DO_channel(self, dio_channel):
        self.set_DIO_channel(dio_channel)

    def configure_DO_channel(self, dio_channel, sample_rate=None):
        self.set_DO_channel(dio_channel)
        self.set_DIO_mode(dio_channel, "O")
        if sample_rate is not None:
            self.set_DO_sample_rate(dio_channel, sample_rate)

    def read_data(self, ai_channel):
        return self.read_AI(ai_channel)
