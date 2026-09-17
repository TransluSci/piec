"""
Driver for the Digilent Analog Discovery 2, used as a 2-channel
Oscilloscope (the AnalogIn instrument of the WaveForms SDK).

Not SCPI: this is a USB device controlled through the WaveForms Runtime
('dwf') library via ctypes, so it has no VISA address and does not inherit
from Scpi.

The WaveForms SDK only allows a single open handle per physical device, so
this class is an *adapter* rather than an owner of the USB connection: it
wraps an already-connected ``piec.drivers.analog_discovery.AnalogDiscovery``
instance (in practice, an ``AnalogDiscovery2Awg``) and issues AnalogIn calls
against its shared ``hdwf`` handle. This lets one physical Analog Discovery
2 drive its AWG and read back on its oscilloscope from the same script:

    awg = AnalogDiscovery2Awg(address=0)
    scope = AnalogDiscovery2Oscilloscope(awg)
"""
import ctypes

import numpy as np
import pandas as pd

from ..analog_discovery import DWFC
from .oscilloscope import Oscilloscope


class AnalogDiscovery2Oscilloscope(Oscilloscope):
    """
    Driver for the Digilent Analog Discovery 2 AnalogIn (oscilloscope)
    instrument.

    Specs (per Digilent Reference Manual):
      - 2 channels, 14-bit, up to 100 MS/s, 1M samples/channel buffer
      - +/-25V range (with default 1x probe), fixed 1MOhm/24pF input, DC coupled only
    """

    channel = [1, 2]
    vdiv = (None, None)
    y_range = (0.1, 50.0)
    y_position = (-25.0, 25.0)
    input_coupling = ["DC"]
    probe_attenuation = (0.001, 1000.0)
    channel_impedance = ["1M"]
    tdiv = (None, None)
    x_range = (1e-8, 500.0)
    x_position = (None, None)
    trigger_source = [1, 2, 'EXT']
    trigger_level = (-25.0, 25.0)
    trigger_slope = ["POS", "NEG", "EITH"]
    trigger_mode = ["EDGE"]
    trigger_sweep = ["AUTO", "NORM"]
    acquisition_mode = ["NORM"]
    acquisition_points = (8, 8192)
    max_sample_rate = 100e6  # 100 MS/s, per Digilent Reference Manual

    _SLOPE_MAP = {
        'POS': DWFC.DwfTriggerSlopeRise,
        'NEG': DWFC.DwfTriggerSlopeFall,
        'EITH': DWFC.DwfTriggerSlopeEither,
    }

    def __init__(self, device, check_params=False, verbose=False, **kwargs):
        """
        Args:
            device: A connected ``AnalogDiscovery`` instance (typically an
                ``AnalogDiscovery2Awg``) whose USB handle is reused. This
                class does not open its own device connection.
        """
        self._initialize_common_state(check_params=check_params, verbose=verbose)

        self.device = device
        self.dwf = device.dwf
        self.hdwf = device.hdwf

        self._acq_channel = 1
        self._points = 1000
        self._tdiv = 1e-3
        self._x_position = 0.0
        self._trigger_sweep = 'AUTO'
        self._auto_timeout_s = 1.0

        for ch in self.channel:
            self.dwf.FDwfAnalogInChannelEnableSet(self.hdwf, ctypes.c_int(ch - 1), ctypes.c_int(1))

        self.dwf.FDwfAnalogInAcquisitionModeSet(self.hdwf, ctypes.c_int(DWFC.acqmodeSingle))
        self.dwf.FDwfAnalogInTriggerAutoTimeoutSet(self.hdwf, ctypes.c_double(self._auto_timeout_s))

    # --- Standard PIEC commands (delegate to the shared device) ---

    def idn(self):
        return self.device.idn()

    def reset(self):
        self.dwf.FDwfAnalogInReset(self.hdwf)
        self._initialize_state()

    def clear(self):
        self.device.clear()

    def error(self):
        return self.device.error()

    def wait(self):
        pass

    def self_test(self):
        return self.device.self_test()

    def operation_complete(self):
        return "1"

    def initialize(self):
        self.reset()
        self.clear()

    # --- Internal helpers ---

    def _ch(self, channel):
        return ctypes.c_int(channel - 1)

    # --- Vertical ---

    def autoscale(self):
        print("[OPTIONAL SKIP] autoscale is not implemented for AnalogDiscovery2Oscilloscope "
              "— set vertical/horizontal scale manually.")

    def toggle_channel(self, channel, on=True):
        self.dwf.FDwfAnalogInChannelEnableSet(self.hdwf, self._ch(channel), ctypes.c_int(1 if on else 0))

    def set_vertical_scale(self, channel, vdiv, y_range=None):
        range_volts = y_range if y_range is not None else (vdiv * 8 if vdiv is not None else None)
        if range_volts is None:
            raise ValueError("Either vdiv or y_range must be provided")
        self.dwf.FDwfAnalogInChannelRangeSet(self.hdwf, self._ch(channel), ctypes.c_double(range_volts))

    def set_vertical_position(self, channel, y_position):
        self.dwf.FDwfAnalogInChannelOffsetSet(self.hdwf, self._ch(channel), ctypes.c_double(-y_position))

    def set_input_coupling(self, channel, input_coupling):
        if input_coupling.upper() != 'DC':
            print("AnalogDiscovery2Oscilloscope: Input channels are DC-coupled only "
                  "in hardware; request ignored.")

    def set_probe_attenuation(self, channel, probe_attenuation):
        self.dwf.FDwfAnalogInChannelAttenuationSet(self.hdwf, self._ch(channel), ctypes.c_double(probe_attenuation))

    def set_channel_impedance(self, channel, channel_impedance):
        print("AnalogDiscovery2Oscilloscope: Input impedance is fixed at 1MOhm in "
              "hardware; request ignored.")

    # --- Horizontal (shared across channels) ---

    def set_horizontal_scale(self, tdiv, x_range=None):
        self._tdiv = tdiv
        total_time = x_range if x_range is not None else tdiv * 10
        sample_rate = self._points / total_time if total_time > 0 else 1000.0
        self.dwf.FDwfAnalogInFrequencySet(self.hdwf, ctypes.c_double(sample_rate))

    def set_horizontal_position(self, x_position):
        self._x_position = x_position
        self.dwf.FDwfAnalogInTriggerPositionSet(self.hdwf, ctypes.c_double(x_position))

    def configure_horizontal(self, tdiv, x_range, x_position):
        self.set_horizontal_scale(tdiv, x_range)
        self.set_horizontal_position(x_position)

    # --- Trigger ---

    def set_trigger_source(self, trigger_source):
        if str(trigger_source).upper() == 'EXT':
            self.dwf.FDwfAnalogInTriggerSourceSet(self.hdwf, ctypes.c_ubyte(DWFC.trigsrcExternal1))
            return
        channel = int(trigger_source)
        self.dwf.FDwfAnalogInTriggerSourceSet(self.hdwf, ctypes.c_ubyte(DWFC.trigsrcDetectorAnalogIn))
        self.dwf.FDwfAnalogInTriggerChannelSet(self.hdwf, self._ch(channel))

    def set_trigger_level(self, trigger_level):
        self.dwf.FDwfAnalogInTriggerLevelSet(self.hdwf, ctypes.c_double(trigger_level))

    def set_trigger_slope(self, trigger_slope):
        slope = self._SLOPE_MAP.get(trigger_slope.upper())
        if slope is None:
            raise ValueError(f"Unsupported trigger_slope '{trigger_slope}' for Analog Discovery 2")
        self.dwf.FDwfAnalogInTriggerConditionSet(self.hdwf, ctypes.c_int(slope))

    def set_trigger_mode(self, trigger_mode):
        if trigger_mode.upper() != 'EDGE':
            raise ValueError("Analog Discovery 2 only supports 'EDGE' trigger_mode")
        self.dwf.FDwfAnalogInTriggerTypeSet(self.hdwf, ctypes.c_ubyte(DWFC.trigtypeEdge))

    def set_trigger_sweep(self, trigger_sweep):
        trigger_sweep = trigger_sweep.upper()
        self._trigger_sweep = trigger_sweep
        self._auto_timeout_s = 1.0 if trigger_sweep == 'AUTO' else 0.0
        self.dwf.FDwfAnalogInTriggerAutoTimeoutSet(self.hdwf, ctypes.c_double(self._auto_timeout_s))

    def configure_trigger(self, trigger_source, trigger_level, trigger_slope, trigger_mode, trigger_sweep):
        self.set_trigger_source(trigger_source)
        self.set_trigger_level(trigger_level)
        self.set_trigger_slope(trigger_slope)
        self.set_trigger_mode(trigger_mode)
        self.set_trigger_sweep(trigger_sweep)

    def manual_trigger(self):
        self.dwf.FDwfDeviceTriggerPC(self.hdwf)

    # --- Acquisition ---

    def toggle_acquisition(self, run=True):
        if not run:
            self.dwf.FDwfAnalogInConfigure(self.hdwf, ctypes.c_int(0), ctypes.c_int(0))

    def arm(self):
        self.dwf.FDwfAnalogInConfigure(self.hdwf, ctypes.c_int(1), ctypes.c_int(1))

    def set_acquisition(self):
        self.arm()

    def set_acquisition_channel(self, channel):
        self._acq_channel = channel

    def set_acquisition_mode(self, acquisition_mode):
        if acquisition_mode.upper() != 'NORM':
            raise ValueError("Analog Discovery 2 driver only implements 'NORM' acquisition_mode")
        self.dwf.FDwfAnalogInAcquisitionModeSet(self.hdwf, ctypes.c_int(DWFC.acqmodeSingle))

    def set_acquisition_points(self, acquisition_points):
        self._points = int(acquisition_points)
        self.dwf.FDwfAnalogInBufferSizeSet(self.hdwf, ctypes.c_int(self._points))

    def configure_acquisition(self, channel, acquisition_mode, acquisition_points):
        self.set_acquisition_channel(channel)
        self.set_acquisition_mode(acquisition_mode)
        self.set_acquisition_points(acquisition_points)

    # --- Data access ---

    def _acquire_channels(self, channels):
        """
        Arms a single acquisition, waits for completion, and reads the buffer
        for every requested channel from that *same* acquisition event.

        The AD2 samples all enabled channels off one shared ADC clock, so
        reading multiple channels this way (one arm/wait, then one
        FDwfAnalogInStatusData call per channel) keeps them exactly
        time-aligned -- unlike calling quick_read()/get_data() separately per
        channel, which would re-trigger independently and lose relative phase.

        Returns:
            dict[int, np.ndarray]: channel -> voltage samples.
        """
        self.dwf.FDwfAnalogInConfigure(self.hdwf, ctypes.c_int(1), ctypes.c_int(1))

        status = ctypes.c_ubyte()
        import time
        capture_time = max(self._tdiv * 10 * 2, 0.5)
        if self._trigger_sweep == 'NORM':
            # No hardware auto-trigger fallback in NORM -- wait generously for a real edge.
            host_timeout = capture_time + 10.0
        else:
            # AUTO mode: the AD2 itself falls back to a free-run capture after
            # self._auto_timeout_s with no qualifying edge (e.g. a flat/DC
            # signal never satisfies an edge trigger). The host-side poll
            # timeout below MUST exceed that by a solid margin -- otherwise
            # this loop can give up a hair before the device actually
            # reaches DwfStateDone, and FDwfAnalogInStatusData then returns a
            # stale/incomplete buffer from the previous acquisition instead
            # of raising any error.
            host_timeout = self._auto_timeout_s + capture_time + 1.0
        timeout = time.time() + host_timeout
        while True:
            self.dwf.FDwfAnalogInStatus(self.hdwf, ctypes.c_int(1), ctypes.byref(status))
            if status.value == DWFC.DwfStateDone:
                break
            if time.time() > timeout:
                print("AnalogDiscovery2Oscilloscope: Acquisition timed out waiting for trigger.")
                break
            time.sleep(0.001)

        result = {}
        for channel in channels:
            buf = (ctypes.c_double * self._points)()
            self.dwf.FDwfAnalogInStatusData(self.hdwf, self._ch(channel), buf, ctypes.c_int(self._points))
            result[channel] = np.array(buf[:])
        return result

    def _acquire(self, channel):
        return self._acquire_channels([channel])[channel]

    def quick_read(self):
        return self._acquire(self._acq_channel)

    def get_data(self):
        data = self._acquire(self._acq_channel)
        n = len(data)
        if n == 0:
            return pd.DataFrame()

        total_time = self._tdiv * 10
        dt = total_time / n if n > 1 else 0
        t = np.arange(n) * dt + self._x_position

        return pd.DataFrame({
            "Time": t,
            f"Channel {self._acq_channel}": data,
        })

    def get_multi_channel_data(self, channels=None):
        """
        Reads two or more channels from one simultaneous acquisition.

        Unlike get_data() (single, currently-selected acquisition channel),
        this lets phase-sensitive measurements (e.g. a Bode sweep comparing
        an amplifier's input and output) compare channels that were sampled
        off the exact same trigger event.

        args:
            channels (list[int]): Channels to read. Defaults to all enabled
                channels (self.channel).
        returns:
            data (DataFrame): 'Time' plus one 'Channel <n>' column per requested channel.
        """
        if channels is None:
            channels = list(self.channel)

        acquired = self._acquire_channels(channels)
        n = self._points
        if n == 0:
            return pd.DataFrame()

        total_time = self._tdiv * 10
        dt = total_time / n if n > 1 else 0
        t = np.arange(n) * dt + self._x_position

        df_data = {"Time": t}
        for channel in channels:
            df_data[f"Channel {channel}"] = acquired[channel]
        return pd.DataFrame(df_data)
