"""Generic MCC Universal Library DAQ fallback for unrecognized MCC boards.

Not registered in ``_mcc_daq_driver_map()``; used only when
``_open_mcc_driver(..., allow_generic=True)`` encounters an MCC board without a
dedicated PIEC driver. Capabilities are introspected from ``DaqDeviceInfo``.
"""

from ._mcc_daq import _MCCDaq

try:
    from mcculw.device_info import DaqDeviceInfo
    from mcculw.enums import AnalogInputMode, ULRange
except ImportError:
    DaqDeviceInfo = None
    AnalogInputMode = None
    ULRange = None


def _ul_range_bounds(ul_range):
    """Return ``(min_V, max_V)`` from a ``ULRange`` enum member, or ``None``."""
    low = getattr(ul_range, "range_min", None)
    high = getattr(ul_range, "range_max", None)
    if low is not None and high is not None:
        return (float(low), float(high))
    return None


def _pick_default_range(range_map):
    """Prefer +/-10 V when supported, else widest bipolar range, else first."""
    if (-10.0, 10.0) in range_map:
        return (-10.0, 10.0)
    bipolar = [r for r in range_map if r[0] < 0 < r[1]]
    if bipolar:
        return max(bipolar, key=lambda r: r[1] - r[0])
    return next(iter(range_map), None)


class GenericMCCDaq(_MCCDaq):
    """Best-effort generic MCC DAQ driver populated from ``DaqDeviceInfo``."""

    IS_GENERIC_FALLBACK = True
    AI_STATUS = "generated"
    HARDWARE_TESTED = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = self.dev_name
        self._ai_range_map = {}
        self._ao_range_map = {}
        self._dio_bit_map = []
        self._introspect_capabilities()
        self._init_mcc_daq_state()
        print(
            f"MCC WARNING: Using generic MCC fallback for unsupported board "
            f"'{self.model}' (board {self.board_num}). Verify voltage ranges, "
            f"wiring mode, and sample rates before running experiments."
        )

    def _introspect_capabilities(self):
        """Populate channels, ranges, and scan flags from ``DaqDeviceInfo``."""
        if DaqDeviceInfo is None:
            raise ConnectionError(
                f"Cannot open generic MCC fallback for '{self.model}': "
                "mcculw.device_info.DaqDeviceInfo is unavailable."
            )
        try:
            dev_info = DaqDeviceInfo(self.board_num)
        except Exception as error:
            raise ConnectionError(
                f"Could not query Universal Library capabilities for '{self.model}': {error}"
            ) from error

        if getattr(dev_info, "supports_analog_input", False):
            ai_info = dev_info.get_ai_info()
            self.ai_channel = list(range(int(getattr(ai_info, "num_chans", 0))))
            self._ai_range_map = {
                bounds: r
                for r in (getattr(ai_info, "supported_ranges", ()) or ())
                if (bounds := _ul_range_bounds(r)) is not None
            }
            self.ai_range = list(self._ai_range_map)
            self.ai_sample_rate = (None, None)
            self._supports_ai_scan = bool(getattr(ai_info, "supports_scan", False))
        else:
            self.ai_channel = []
            self.ai_range = []
            self.ai_sample_rate = (None, None)
            self._supports_ai_scan = False

        if getattr(dev_info, "supports_analog_output", False):
            ao_info = dev_info.get_ao_info()
            self.ao_channel = list(range(int(getattr(ao_info, "num_chans", 0))))
            self._ao_range_map = {
                bounds: r
                for r in (getattr(ao_info, "supported_ranges", ()) or ())
                if (bounds := _ul_range_bounds(r)) is not None
            }
            self.ao_range = list(self._ao_range_map)
            self._supports_ao_scan = bool(getattr(ao_info, "supports_scan", False))
            self.ao_sample_rate = (
                (1, 1_000_000) if (self.ao_channel and self._supports_ao_scan) else (None, None)
            )
        else:
            self.ao_channel = []
            self.ao_range = []
            self.ao_sample_rate = (None, None)
            self._supports_ao_scan = False

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

    def _ai_ul_range(self, channel):
        voltage_range = self._ai_ranges.get(channel) or _pick_default_range(
            self._ai_range_map
        )
        if voltage_range in self._ai_range_map:
            return self._ai_range_map[voltage_range]
        raise ValueError(f"No supported analog-input range found for {self.model}")

    def _ao_bounds_and_ul_range(self, channel):
        voltage_range = self._ao_ranges.get(channel) or _pick_default_range(
            self._ao_range_map
        )
        if voltage_range in self._ao_range_map:
            return voltage_range, self._ao_range_map[voltage_range]
        raise ValueError(f"No supported analog-output range found for {self.model}")

    def _digital_port(self, dio_channel):
        return self._dio_bit_map[dio_channel]

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
        try:
            ai_info = DaqDeviceInfo(self.board_num).get_ai_info()
            self.ai_channel = list(
                range(int(getattr(ai_info, "num_chans", len(self.ai_channel))))
            )
        except Exception:
            pass

    def set_ai_range(self, ai_channel, ai_range):
        """Select a supported input range for one analog-input channel."""
        self._validate_channel(ai_channel, self.ai_channel, "AI")
        voltage_range = self._normalize_range(ai_range)
        if voltage_range not in self._ai_range_map:
            raise ValueError(
                f"AI range {voltage_range} is not supported by {self.model}; "
                f"valid ranges are {list(self._ai_range_map)}"
            )
        self._ai_ranges[ai_channel] = voltage_range

    def set_ao_range(self, ao_channel, ao_range):
        """Select a supported output range for one analog-output channel."""
        self._validate_channel(ao_channel, self.ao_channel, "AO")
        voltage_range = self._normalize_range(ao_range)
        if voltage_range not in self._ao_range_map:
            raise ValueError(
                f"AO range {voltage_range} is not supported by {self.model}; "
                f"valid ranges are {list(self._ao_range_map)}"
            )
        self._ao_ranges[ao_channel] = voltage_range
