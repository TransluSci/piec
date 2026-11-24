"""Driver family for the USB-1608G, USB-1608GX, and USB-1608GX-2AO."""

import math
import threading
import time
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


class USB1608G(MCC, Daq):
    """One driver for all three USB-1608G family models.

    The device provides 16 single-ended or 8 differential 16-bit analog inputs
    (±10 V, ±5 V, ±2 V, ±1 V), model-specific aggregate sampling rates
    (250 kS/s on USB-1608G; 500 kS/s on USB-1608GX and USB-1608GX-2AO), two
    fixed ±10 V 16-bit analog outputs on the USB-1608GX-2AO, 8 individually
    configurable digital I/O lines on ``AUXPORT``, and one hardware PWM timer
    output (``TMR``).
    """

    AUTODETECT_ID = [
        "USB-1608G",
        "USB-1608GX",
        "USB-1608GX-2AO",
    ]
    AI_STATUS = "generated"
    HARDWARE_TESTED = False  # Untested on physical hardware

    ai_channel = list(range(16))
    ai_range = [
        (-10.0, 10.0),
        (-5.0, 5.0),
        (-2.0, 2.0),
        (-1.0, 1.0),
    ]
    ai_mode = ["SE", "DIFF"]
    ai_sample_rate = (1, 500_000)

    # The class advertises the family maximum for validation and virtual use.
    # A physical instance replaces this with its exact model capability after
    # reading IDN in __init__.
    ao_channel = [0, 1]
    ao_range = [(-10.0, 10.0)]
    ao_sample_rate = (1, 500_000)

    dio_channel = list(range(8))
    dio_direction = ["I", "O"]

    _MODEL_SPECS = {
        "USB-1608G": {"ai_max_rate": 250_000, "ao_count": 0},
        "USB-1608GX": {"ai_max_rate": 500_000, "ao_count": 0},
        "USB-1608GX-2AO": {"ai_max_rate": 500_000, "ao_count": 2},
    }

    _AI_RANGES = {
        (-10.0, 10.0): "BIP10VOLTS",
        (-5.0, 5.0): "BIP5VOLTS",
        (-2.0, 2.0): "BIP2VOLTS",
        (-1.0, 1.0): "BIP1VOLTS",
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
        matches = [model for model in self._MODEL_SPECS if model in identity]
        if not matches:
            raise ValueError(
                f"Unsupported USB-1608G identity {identity!r}; expected one of "
                f"{list(self._MODEL_SPECS)}"
            )

        self.model = max(matches, key=len)
        spec = self._MODEL_SPECS[self.model]
        self.ai_sample_rate = (1, spec["ai_max_rate"])

        ao_count = spec["ao_count"]
        self.ao_channel = list(range(ao_count))
        if ao_count:
            self.ao_range = [(-10.0, 10.0)]
            self.ao_sample_rate = (1, 500_000)
        else:
            self.ao_range = []
            self.ao_sample_rate = (None, None)

    def get_trigger_pulse_capabilities(self):
        capabilities = super().get_trigger_pulse_capabilities()
        # 50% duty: 16 ns--33 s high/low widths stay within the documented
        # 0.0149 Hz--32 MHz timer frequency range for all USB-1608G variants.
        capabilities["timer"] = {
            "channels": [0],
            "timing": "hardware",
            "min_width": 16e-9,
            "max_width": 33.0,
        }
        return capabilities

    def send_trigger_pulse(self, channel, pulse_width, active_high=True, *,
                           resource='digital', require_hardware_timing=False, cancel_event=None):
        """Use TMR timer 0 for hardware pulses, or the base DIO software fallback.

        Universal Library ``pulse_out_start`` returns quantized frequency/duty/delay.
        Exactly one pulse is requested. Software controls launch latency; hardware
        controls the pulse width. This does not arm or synchronize an AO/AI scan.
        The TMR terminal must be reserved by the caller for the duration of this call.
        Manufacturer references:
        https://files.digilent.com/manuals/Mcculw_WebHelp/Users_Guide/Analog_Input_Boards/USB-1608G_Series.htm
        https://files.digilent.com/manuals/Mcculw_WebHelp/Function_Reference/Ctr-python/pulse_out_start.htm
        https://files.digilent.com/manuals/Mcculw_WebHelp/Function_Reference/Ctr-python/pulse_out_stop.htm
        """
        if resource == "digital":
            return super().send_trigger_pulse(
                channel,
                pulse_width,
                active_high,
                resource=resource,
                require_hardware_timing=require_hardware_timing,
                cancel_event=cancel_event,
            )
        self.validate_trigger_pulse(
            channel,
            pulse_width,
            active_high,
            resource=resource,
            require_hardware_timing=require_hardware_timing,
        )
        lock = self.__dict__.setdefault("_trigger_pulse_lock", threading.Lock())
        with lock:
            self._wait_trigger_pulse(0, cancel_event)
            idle = TimerIdleState.LOW if active_high else TimerIdleState.HIGH
            try:
                frequency, duty, delay = self.ul.pulse_out_start(
                    self.board_num,
                    channel,
                    0.5 / pulse_width,
                    0.5,
                    pulse_count=1,
                    initial_delay=0,
                    idle_state=idle,
                )
                if (
                    not all(math.isfinite(v) for v in (frequency, duty, delay))
                    or not 0.0149 <= frequency <= 32_000_000
                    or not 0 < duty < 1
                    or not 0 <= delay <= 67.11
                ):
                    raise ValueError(
                        "Invalid timer settings returned by Universal Library"
                    )
                # Wait a complete actual period, rather than stopping halfway
                # through the programmed pulse. Cancellation still stops early.
                self._wait_trigger_pulse(delay + 1.0 / frequency, cancel_event)
            finally:
                self.ul.pulse_out_stop(self.board_num, channel)
        return {
            "resource": resource,
            "channel": int(channel),
            "timing": "hardware",
            "requested_pulse_width": float(pulse_width),
            "programmed_pulse_width": duty / frequency,
            "active_high": active_high,
        }

    @staticmethod
    def _normalize_range(voltage_range):
        try:
            low, high = voltage_range
        except (TypeError, ValueError) as error:
            raise ValueError(
                "range must be a two-value (minimum, maximum) pair"
            ) from error
        return float(low), float(high)

    def _validate_ai_channel(self, channel):
        valid_channels = range(16) if self._ai_mode == "se" else range(8)
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
        enum_name = self._AI_RANGES[voltage_range]
        return getattr(ULRange, enum_name)

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
        valid_channels = set(range(16) if mode == "se" else range(8))
        self.ai_channel = sorted(valid_channels)
        self.ai_range = list(self._AI_RANGES)
        self._ai_ranges = {
            channel: voltage_range
            for channel, voltage_range in getattr(self, "_ai_ranges", {}).items()
            if channel in valid_channels and voltage_range in self._AI_RANGES
        }

    def set_ai_range(self, ai_channel, ai_range):
        """Select a supported input range for one analog-input channel."""
        self._validate_ai_channel(ai_channel)
        voltage_range = self._normalize_range(ai_range)
        if voltage_range not in self._AI_RANGES:
            raise ValueError(
                f"AI range {voltage_range} is invalid; "
                f"valid ranges are {list(self._AI_RANGES)}"
            )
        self._ai_ranges[ai_channel] = voltage_range

    def set_ao_range(self, ao_channel, ao_range):
        """Validate the USB-1608GX-2AO's fixed +/-10 V output range."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        voltage_range = self._normalize_range(ao_range)
        if voltage_range != (-10.0, 10.0):
            raise ValueError(f"{self.model} analog outputs have a fixed +/-10 V range")

    def read_AI(self, ai_channel):
        """Read one analog-input sample and return volts."""
        self._validate_ai_channel(ai_channel)
        return float(
            self.ul.v_in(self.board_num, ai_channel, self._ai_ul_range(ai_channel))
        )

    def read_AI_scan(self, ai_channel, points, rate, *, on_chunk=None, stop_event=None):
        """
        Acquire a finite, hardware-paced scan of one or more analog inputs.

        args:
            ai_channel (int or list[int]): One channel or a nonempty list of
                unique channels from `self.ai_channel`.
            points (int): Number of samples to acquire per channel.
            rate (float): Requested sample rate in Hz per channel.
            on_chunk (callable, optional): Keyword-only callback invoked with
                incremental scan DataFrames while the background scan is running.
            stop_event (threading.Event, optional): Keyword-only event checked
                while polling the scan buffer to stop acquisition early.
        Returns:
            data (pandas.DataFrame): 'Time' in seconds from scan start, followed
                by 'Voltage' (single channel) or 'AI<n>' columns (multiple channels).
                `data.attrs['sample_rate']` holds the actual per-channel rate in Hz.
        """
        channels = self._scan_channels(ai_channel)
        low, high = min(channels), max(channels)
        width = high - low + 1
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise ValueError("points must be a positive integer")
        if on_chunk is not None and not callable(on_chunk):
            raise TypeError("on_chunk must be callable when provided")
        if stop_event is not None and not callable(getattr(stop_event, "is_set", None)):
            raise TypeError("stop_event must provide an is_set() method when provided")
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
        sent_points = 0
        last_emit = time.monotonic()
        try:
            actual_rate = self.ul.a_in_scan(
                self.board_num, low, high, total, int(rate), ranges[0], handle, options
            )
            self._last_ai_scan_rate = actual_rate
            deadline = time.monotonic() + points / actual_rate + 5.0
            while True:
                status, cur_count, _ = self.ul.get_status(
                    self.board_num, FunctionType.AIFUNCTION
                )
                idle = status == Status.IDLE
                stopped = stop_event is not None and stop_event.is_set()
                cur_points = min(points, max(0, int(cur_count) // width))
                if on_chunk is not None and cur_points > sent_points:
                    now = time.monotonic()
                    if idle or stopped or (now - last_emit) >= 0.05:
                        n_new = cur_points - sent_points
                        count = n_new * width
                        chunk_buf = (c_double * count)()
                        self.ul.scaled_win_buf_to_array(
                            handle, chunk_buf, sent_points * width, count
                        )
                        chunk_vals = np.asarray(chunk_buf).reshape(n_new, width)[
                            :, columns
                        ]
                        chunk_times = np.arange(sent_points, cur_points) / actual_rate
                        on_chunk(
                            self._scan_dataframe(
                                channels, chunk_times, chunk_vals, actual_rate
                            )
                        )
                        sent_points = cur_points
                        last_emit = now
                if idle or stopped:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Analog input scan timed out")
                time.sleep(0.01)
            n_read = (
                sent_points
                if (stop_event is not None and stop_event.is_set() and on_chunk is not None)
                else (
                    cur_points
                    if (stop_event is not None and stop_event.is_set())
                    else points
                )
            )
            if n_read <= 0:
                return self._scan_dataframe(
                    channels, np.empty(0), np.empty((0, len(channels))), actual_rate
                )
            buffer = (c_double * (n_read * width))()
            self.ul.scaled_win_buf_to_array(handle, buffer, 0, n_read * width)
            values = np.asarray(buffer).reshape(n_read, width)[:, columns]
            return self._scan_dataframe(
                channels, np.arange(n_read) / actual_rate, values, actual_rate
            )
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
            self.ul.v_out(self.board_num, ao_channel, ULRange.BIP10VOLTS, voltage)

    def write_AO_scan(self, ao_channel, data, sample_rate):
        """Start continuous hardware-paced waveform output on one AO channel."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        values = [float(value) for value in data]
        if not values:
            raise ValueError("data must contain at least one voltage value")
        if any(value < -10.0 or value > 10.0 for value in values):
            raise ValueError("analog-output values must be within +/-10 V")
        low_rate, high_rate = self.ao_sample_rate
        if not low_rate <= sample_rate <= high_rate:
            raise ValueError(
                f"sample_rate must be between {low_rate} and {high_rate:,} S/s"
            )

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

    def close(self):
        """Stop any background AO scan before releasing the board."""
        self.stop_output()
        super().close()

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
        self.ul.d_config_bit(
            self.board_num, DigitalPortType.AUXPORT, dio_channel, directions[direction]
        )

    def read_DI(self, dio_channel):
        """Read one digital I/O line as integer 0 or 1."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        return int(
            self.ul.d_bit_in(self.board_num, DigitalPortType.AUXPORT, dio_channel)
        )

    def write_DO(self, dio_channel, data):
        """Write one or more software-paced states to a digital I/O line."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        values = [data] if isinstance(data, (int, bool)) else data
        for value in values:
            if value not in (0, 1, False, True):
                raise ValueError("digital-output values must be 0/1 or False/True")
            self.ul.d_bit_out(
                self.board_num, DigitalPortType.AUXPORT, dio_channel, int(bool(value))
            )

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
        low_rate, high_rate = self.ai_sample_rate
        if not low_rate <= sample_rate <= high_rate:
            raise ValueError(
                f"sample_rate must be between {low_rate} and {high_rate:,} S/s"
            )
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
        low_rate, high_rate = self.ao_sample_rate
        if not low_rate <= sample_rate <= high_rate:
            raise ValueError(
                f"sample_rate must be between {low_rate} and {high_rate:,} S/s"
            )
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
