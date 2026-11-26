"""Driver family for the USB-1608G, USB-1608GX, and USB-1608GX-2AO."""

import math
import threading

from ._mcc_daq import _MCCDaq

try:
    from mcculw.enums import (
        AnalogInputMode,
        DigitalPortType,
        TimerIdleState,
        ULRange,
    )
except ImportError:
    AnalogInputMode = None
    DigitalPortType = None
    TimerIdleState = None
    ULRange = None


class USB1608G(_MCCDaq):
    """One driver for all three USB-1608G family models.

    Provides 16 single-ended or 8 differential 16-bit analog inputs
    (±10 V, ±5 V, ±2 V, ±1 V), model-specific aggregate sampling rates
    (250 kS/s on USB-1608G; 500 kS/s on USB-1608GX and USB-1608GX-2AO), two
    fixed ±10 V 16-bit analog outputs on USB-1608GX-2AO, 8 individually
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

    # Family maximums at class level for validation and virtual dispatch;
    # physical instances refine these from IDN in __init__.
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
        self._init_mcc_daq_state()
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

    def _ai_ul_range(self, channel):
        voltage_range = self._ai_ranges.get(channel, (-10.0, 10.0))
        return getattr(ULRange, self._AI_RANGES[voltage_range])

    @staticmethod
    def _digital_port(dio_channel):
        return DigitalPortType.AUXPORT, dio_channel

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
            ch: vr for ch, vr in self._ai_ranges.items() if ch in valid_channels
        }

    def set_ai_range(self, ai_channel, ai_range):
        """Select a supported input range for one analog-input channel."""
        self._validate_channel(ai_channel, self.ai_channel, "AI")
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
        if self._normalize_range(ao_range) != (-10.0, 10.0):
            raise ValueError(f"{self.model} analog outputs have a fixed +/-10 V range")

    def get_trigger_pulse_capabilities(self):
        capabilities = super().get_trigger_pulse_capabilities()
        # 50% duty: 16 ns--33 s stays within the 0.0149 Hz--32 MHz timer range.
        capabilities["timer"] = {
            "channels": [0],
            "timing": "hardware",
            "min_width": 16e-9,
            "max_width": 33.0,
        }
        return capabilities

    def send_trigger_pulse(self, channel, pulse_width, active_high=True, *,
                           resource='digital', require_hardware_timing=False, cancel_event=None):
        """Use TMR timer 0 for hardware pulses, or the base DIO software fallback."""
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
