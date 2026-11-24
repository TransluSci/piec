"""Generic MCC Universal Library DAQ fallback for unrecognized MCC boards.

This internal driver is not registered as a model-specific driver in
``_mcc_daq_driver_map()``. Instead, ``_open_mcc_driver(..., allow_generic=True)``
uses it when an MCC board is connected via Universal Library that does not yet
have a dedicated PIEC driver class. Capabilities (channels, ranges, DIO ports,
and scan support) are introspected dynamically from ``DaqDeviceInfo``.
"""

import time
from ctypes import c_double
import numpy as np

from ..mcc import MCC
from .daq import Daq

try:
    from mcculw.device_info import DaqDeviceInfo
    from mcculw.enums import (
        AnalogInputMode,
        DigitalIODirection,
        FunctionType,
        ScanOptions,
        Status,
        ULRange,
    )
except ImportError:
    DaqDeviceInfo = None
    AnalogInputMode = None
    DigitalIODirection = None
    FunctionType = None
    ScanOptions = None
    Status = None
    ULRange = None


_FALLBACK_RANGE_BOUNDS = {
    "BIP60VOLTS": (-60.0, 60.0),
    "BIP30VOLTS": (-30.0, 30.0),
    "BIP20VOLTS": (-20.0, 20.0),
    "BIP15VOLTS": (-15.0, 15.0),
    "BIP10VOLTS": (-10.0, 10.0),
    "BIP5VOLTS": (-5.0, 5.0),
    "BIP4VOLTS": (-4.0, 4.0),
    "BIP2PT5VOLTS": (-2.5, 2.5),
    "BIP2VOLTS": (-2.0, 2.0),
    "BIP1PT25VOLTS": (-1.25, 1.25),
    "BIP1VOLTS": (-1.0, 1.0),
    "BIPPT625VOLTS": (-0.625, 0.625),
    "BIPPT5VOLTS": (-0.5, 0.5),
    "BIPPT25VOLTS": (-0.25, 0.25),
    "BIPPT2VOLTS": (-0.2, 0.2),
    "BIPPT1VOLTS": (-0.1, 0.1),
    "UNI10VOLTS": (0.0, 10.0),
    "UNI5VOLTS": (0.0, 5.0),
    "UNI4VOLTS": (0.0, 4.0),
    "UNI2PT5VOLTS": (0.0, 2.5),
    "UNI2VOLTS": (0.0, 2.0),
    "UNI1PT25VOLTS": (0.0, 1.25),
    "UNI1VOLTS": (0.0, 1.0),
}


def _ul_range_to_tuple(ul_range):
    """Return ``(min_V, max_V)`` for a ``ULRange`` enum member, or ``None``."""
    low = getattr(ul_range, "range_min", None)
    high = getattr(ul_range, "range_max", None)
    if low is not None and high is not None:
        return (float(low), float(high))
    name = getattr(ul_range, "name", None)
    if name in _FALLBACK_RANGE_BOUNDS:
        return _FALLBACK_RANGE_BOUNDS[name]
    return None


def _pick_default_range(range_map):
    """Prefer +/-10 V when supported, else widest bipolar range, else first."""
    if (-10.0, 10.0) in range_map:
        return (-10.0, 10.0)
    bipolar = [r for r in range_map if r[0] < 0 < r[1]]
    if bipolar:
        return max(bipolar, key=lambda r: r[1] - r[0])
    return next(iter(range_map), None)


class GenericMCCDaq(MCC, Daq):
    """Best-effort generic MCC DAQ driver populated from ``DaqDeviceInfo``.

    Intended as a fallback when no dedicated PIEC driver matches a connected
    MCC board. Capabilities are queried dynamically at connection time.
    """

    IS_GENERIC_FALLBACK = True
    AI_STATUS = "generated"
    HARDWARE_TESTED = False

    ai_channel = []
    ai_range = [(-10.0, 10.0)]
    ai_mode = ["SE", "DIFF"]
    ai_sample_rate = (1, 1_000_000)

    ao_channel = []
    ao_range = [(-10.0, 10.0)]
    ao_sample_rate = (1, 1_000_000)

    dio_channel = []
    dio_direction = ["I", "O"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = self.dev_name
        self._ai_ranges = {}
        self._ao_ranges = {}
        self._ai_sample_rates = {}
        self._ao_sample_rates = {}
        self._ai_range_map = {}
        self._ao_range_map = {}
        self._dio_bit_map = []
        self._supports_ai_scan = True
        self._supports_ao_scan = False
        self._active_memhandle = None
        self._introspect_capabilities()
        self._selected_ai_channel = self.ai_channel[0] if self.ai_channel else None
        self._selected_ao_channel = self.ao_channel[0] if self.ao_channel else None
        self._selected_dio_channel = self.dio_channel[0] if self.dio_channel else None
        print(
            f"MCC WARNING: Using generic MCC fallback for unsupported board "
            f"'{self.model}' (board {self.board_num}). Verify voltage ranges, "
            f"wiring mode, and sample rates before running experiments."
        )

    def _introspect_capabilities(self):
        """Populate channels, ranges, and scan flags from ``DaqDeviceInfo``."""
        dev_info = None
        if DaqDeviceInfo is not None:
            try:
                dev_info = DaqDeviceInfo(self.board_num)
            except Exception as error:
                if self.verbose:
                    print(f"GenericMCCDaq: Could not query DaqDeviceInfo: {error}")

        if dev_info is None:
            default_ul = getattr(ULRange, "BIP10VOLTS", None)
            self._ai_range_map = {(-10.0, 10.0): default_ul} if default_ul is not None else {}
            self._ao_range_map = {(-10.0, 10.0): default_ul} if default_ul is not None else {}
            self.ai_channel = list(range(8))
            self.ai_range = list(self._ai_range_map) or [(-10.0, 10.0)]
            self.ao_channel = [0, 1]
            self.ao_range = list(self._ao_range_map) or [(-10.0, 10.0)]
            self.ao_sample_rate = (1, 1_000_000)
            self._supports_ai_scan = True
            self._supports_ao_scan = True
            return

        # Analog Input
        if getattr(dev_info, "supports_analog_input", False):
            ai_info = dev_info.get_ai_info()
            self.ai_channel = list(range(int(getattr(ai_info, "num_chans", 0))))
            self._ai_range_map = {}
            for ul_range in getattr(ai_info, "supported_ranges", ()) or ():
                bounds = _ul_range_to_tuple(ul_range)
                if bounds is not None:
                    self._ai_range_map[bounds] = ul_range
            self.ai_range = list(self._ai_range_map) or [(-10.0, 10.0)]
            self._supports_ai_scan = bool(getattr(ai_info, "supports_scan", True))
        else:
            self.ai_channel = []
            self.ai_range = []
            self.ai_sample_rate = (None, None)
            self._supports_ai_scan = False

        # Analog Output
        if getattr(dev_info, "supports_analog_output", False):
            ao_info = dev_info.get_ao_info()
            self.ao_channel = list(range(int(getattr(ao_info, "num_chans", 0))))
            self._ao_range_map = {}
            for ul_range in getattr(ao_info, "supported_ranges", ()) or ():
                bounds = _ul_range_to_tuple(ul_range)
                if bounds is not None:
                    self._ao_range_map[bounds] = ul_range
            self.ao_range = list(self._ao_range_map) or [(-10.0, 10.0)]
            self._supports_ao_scan = bool(getattr(ao_info, "supports_scan", False))
            self.ao_sample_rate = (1, 1_000_000) if self.ao_channel else (None, None)
        else:
            self.ao_channel = []
            self.ao_range = []
            self.ao_sample_rate = (None, None)
            self._supports_ao_scan = False

        # Digital I/O
        self._dio_bit_map = []
        if getattr(dev_info, "supports_digital_io", False):
            dio_info = dev_info.get_dio_info()
            for port in getattr(dio_info, "port_info", ()) or ():
                num_bits = int(getattr(port, "num_bits", 0))
                port_type = getattr(port, "type", None)
                if port_type is not None and num_bits > 0:
                    for bit in range(num_bits):
                        self._dio_bit_map.append((port_type, bit))
        self.dio_channel = list(range(len(self._dio_bit_map)))

    @staticmethod
    def _normalize_range(voltage_range):
        try:
            low, high = voltage_range
        except (TypeError, ValueError) as error:
            raise ValueError("range must be a two-value (minimum, maximum) pair") from error
        return float(low), float(high)

    @staticmethod
    def _validate_channel(channel, valid_channels, channel_type):
        if channel not in valid_channels:
            raise ValueError(
                f"{channel_type} channel {channel} is invalid; "
                f"valid channels are {valid_channels}"
            )

    def _ai_ul_range(self, channel):
        voltage_range = self._ai_ranges.get(channel) or _pick_default_range(self._ai_range_map)
        if voltage_range in self._ai_range_map:
            return self._ai_range_map[voltage_range]
        return getattr(ULRange, "BIP10VOLTS", None)

    def _ao_bounds_and_ul_range(self, channel):
        voltage_range = self._ao_ranges.get(channel) or _pick_default_range(self._ao_range_map)
        if voltage_range in self._ao_range_map:
            return voltage_range, self._ao_range_map[voltage_range]
        return (-10.0, 10.0), getattr(ULRange, "BIP10VOLTS", None)

    def set_input_mode(self, ai_mode):
        """Attempt to set global analog-input wiring mode to ``SE`` or ``DIFF``."""
        mode = str(ai_mode).lower()
        modes = {
            "se": AnalogInputMode.SINGLE_ENDED,
            "diff": AnalogInputMode.DIFFERENTIAL,
        }
        if mode not in modes:
            raise ValueError("ai_mode must be 'SE' or 'DIFF'")
        try:
            self.ul.a_input_mode(self.board_num, modes[mode])
        except Exception as error:
            print(
                f"GenericMCCDaq WARNING: '{self.model}' did not accept global "
                f"a_input_mode({ai_mode!r}): {error}. Keeping current board mode."
            )
            return
        if DaqDeviceInfo is not None:
            try:
                ai_info = DaqDeviceInfo(self.board_num).get_ai_info()
                self.ai_channel = list(range(int(getattr(ai_info, "num_chans", len(self.ai_channel)))))
            except Exception:
                pass

    def set_ai_range(self, ai_channel, ai_range):
        """Select a supported input range for one analog-input channel."""
        self._validate_channel(ai_channel, self.ai_channel, "AI")
        voltage_range = self._normalize_range(ai_range)
        if self._ai_range_map and voltage_range not in self._ai_range_map:
            raise ValueError(
                f"AI range {voltage_range} is not supported by {self.model}; "
                f"valid ranges are {list(self._ai_range_map)}"
            )
        self._ai_ranges[ai_channel] = voltage_range

    def set_ao_range(self, ao_channel, ao_range):
        """Select or validate an output range for one analog-output channel."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        voltage_range = self._normalize_range(ao_range)
        if self._ao_range_map and voltage_range not in self._ao_range_map:
            raise ValueError(
                f"AO range {voltage_range} is not supported by {self.model}; "
                f"valid ranges are {list(self._ao_range_map)}"
            )
        self._ao_ranges[ao_channel] = voltage_range

    def read_AI(self, ai_channel):
        """Read one analog-input sample and return volts."""
        self._validate_channel(ai_channel, self.ai_channel, "AI")
        return float(self.ul.v_in(self.board_num, ai_channel, self._ai_ul_range(ai_channel)))

    def read_AI_scan(self, ai_channel, points, rate, *, on_chunk=None, stop_event=None):
        """Acquire a finite, hardware-paced scan of one or more analog inputs."""
        if not self._supports_ai_scan:
            raise NotImplementedError(f"{self.model} does not support hardware-paced AI scans")
        channels = self._scan_channels(ai_channel)
        low, high = min(channels), max(channels)
        width = high - low + 1
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise ValueError("points must be a positive integer")
        if on_chunk is not None and not callable(on_chunk):
            raise TypeError("on_chunk must be callable when provided")
        if stop_event is not None and not callable(getattr(stop_event, "is_set", None)):
            raise TypeError("stop_event must provide an is_set() method when provided")
        if rate <= 0:
            raise ValueError("rate must be positive")
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
                        chunk_vals = np.asarray(chunk_buf).reshape(n_new, width)[:, columns]
                        chunk_times = np.arange(sent_points, cur_points) / actual_rate
                        on_chunk(
                            self._scan_dataframe(channels, chunk_times, chunk_vals, actual_rate)
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
        (vmin, vmax), ul_range = self._ao_bounds_and_ul_range(ao_channel)
        values = [data] if isinstance(data, (int, float)) else data
        for value in values:
            voltage = float(value)
            if not vmin <= voltage <= vmax:
                raise ValueError(f"analog-output values must be within [{vmin}, {vmax}] V")
            self.ul.v_out(self.board_num, ao_channel, ul_range, voltage)

    def write_AO_scan(self, ao_channel, data, sample_rate):
        """Start continuous hardware-paced waveform output on one AO channel."""
        if not self._supports_ao_scan:
            raise NotImplementedError(
                f"{self.model} does not support hardware-paced AO scans; use stepped mode."
            )
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        (vmin, vmax), ul_range = self._ao_bounds_and_ul_range(ao_channel)
        values = [float(value) for value in data]
        if not values:
            raise ValueError("data must contain at least one voltage value")
        if any(value < vmin or value > vmax for value in values):
            raise ValueError(f"analog-output values must be within [{vmin}, {vmax}] V")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

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
                ul_range,
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
        port, bit = self._dio_bit_map[dio_channel]
        self.ul.d_config_bit(self.board_num, port, bit, directions[direction])

    def read_DI(self, dio_channel):
        """Read one digital I/O line as integer 0 or 1."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        port, bit = self._dio_bit_map[dio_channel]
        return int(self.ul.d_bit_in(self.board_num, port, bit))

    def write_DO(self, dio_channel, data):
        """Write one or more software-paced states to a digital I/O line."""
        self._validate_channel(dio_channel, self.dio_channel, "DIO")
        values = [data] if isinstance(data, (int, bool)) else data
        port, bit = self._dio_bit_map[dio_channel]
        for value in values:
            if value not in (0, 1, False, True):
                raise ValueError("digital-output values must be 0/1 or False/True")
            self.ul.d_bit_out(self.board_num, port, bit, int(bool(value)))

    # Daq interface adapters
    def set_AI_channel(self, ai_channel):
        self._validate_channel(ai_channel, self.ai_channel, "AI")
        self._selected_ai_channel = ai_channel

    def set_AI_range(self, ai_channel, range):
        self.set_ai_range(ai_channel, range)

    def set_AI_sample_rate(self, ai_channel, sample_rate):
        self._validate_channel(ai_channel, self.ai_channel, "AI")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
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
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
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
