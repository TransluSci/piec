"""
Driver for the Digilent Analog Discovery 2, used as a 2-channel Arbitrary
Waveform Generator (the AnalogOut instrument of the WaveForms SDK).

Not SCPI: this is a USB device controlled through the WaveForms Runtime
('dwf') library via ctypes, so it has no VISA address and does not inherit
from Scpi. See ``piec.drivers.analog_discovery.AnalogDiscovery`` for the
connection layer.

To simultaneously use the Analog Discovery 2's oscilloscope (AnalogIn)
channels on the *same* physical device without a second USB connection
attempt (WaveForms only allows one open handle per device), wrap this
instance with ``AnalogDiscovery2Oscilloscope``:

    awg = AnalogDiscovery2Awg(address=0)
    scope = AnalogDiscovery2Oscilloscope(awg)
"""
import ctypes

import numpy as np

from ..analog_discovery import AnalogDiscovery, DWFC
from .awg import Awg


class AnalogDiscovery2Awg(AnalogDiscovery, Awg):
    """
    Driver for the Digilent Analog Discovery 2 AnalogOut (AWG) instrument.

    Specs (per Digilent Reference Manual):
      - 2 independent AWG channels (W1, W2)
      - +/-5V output range, 14-bit, up to 100 MS/s
      - Fixed output impedance (not software-adjustable)
    """

    channel = [1, 2]

    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']

    frequency = {
        'waveform': {
            'SIN': (1e-6, 20e6),
            'SQU': (1e-6, 20e6),
            'RAMP': (1e-6, 200e3),
            'PULS': (1e-6, 20e6),
            'NOIS': (1e-6, 20e6),
            'DC': None,
            'USER': (1e-6, 20e6),
        }
    }

    # Amplitude here is Vpp (piec convention); the SDK itself takes peak volts.
    amplitude = (0.0, 10.0)
    offset = (-5.0, 5.0)

    polarity = ['NORM', 'INV']
    duty_cycle = (0.0, 100.0)
    symmetry = (0.0, 100.0)
    pulse_width = (16e-9, None)
    pulse_delay = (0.0, None)

    _FUNC_MAP = {
        'SIN': DWFC.funcSine,
        'SQU': DWFC.funcSquare,
        'RAMP': DWFC.funcRampUp,
        'NOIS': DWFC.funcNoise,
        'DC': DWFC.funcDC,
    }

    _TRIGSRC_MAP = {
        'IMM': DWFC.trigsrcNone,
        'MAN': DWFC.trigsrcPC,
        'INT': DWFC.trigsrcAnalogIn,
        'EXT': DWFC.trigsrcExternal1,
    }

    def __init__(self, address=-1, **kwargs):
        super().__init__(address, **kwargs)

        self._enabled = {1: False, 2: False}
        self._amplitude_vpp = {1: 1.0, 2: 1.0}
        self._polarity = {1: 'NORM', 2: 'NORM'}
        self._arb_waveforms = {}
        self._pulse_params = {}
        self._active_arb_name = {1: None, 2: None}

    # --- Internal helpers ---

    def _ch(self, channel):
        """Converts piec's 1-based channel to the SDK's 0-based index."""
        return ctypes.c_int(channel - 1)

    def _carrier(self):
        return ctypes.c_int(DWFC.AnalogOutNodeCarrier)

    def _get_pulse_params(self, channel):
        if channel not in self._pulse_params:
            self._pulse_params[channel] = {
                'pulse_width': None,
                'pulse_delay': 0.0,
                'rise_time': 0.0,
                'fall_time': 0.0,
                'duty_cycle': 50.0,
            }
        return self._pulse_params[channel]

    def _apply_amplitude(self, channel):
        """(Re-)writes amplitude honoring the stored polarity sign."""
        vpp = self._amplitude_vpp[channel]
        peak = vpp / 2.0
        if self._polarity[channel] == 'INV':
            peak = -peak
        self.dwf.FDwfAnalogOutNodeAmplitudeSet(
            self.hdwf, self._ch(channel), self._carrier(), ctypes.c_double(peak)
        )

    def _reconfigure_if_active(self, channel):
        """Applies pending config changes immediately if output is already running."""
        if self._enabled.get(channel):
            self.dwf.FDwfAnalogOutConfigure(self.hdwf, self._ch(channel), ctypes.c_int(1))

    def _apply_pulse_waveform(self, channel):
        """
        Synthesizes the configured pulse shape as arbitrary data and loads
        it as the channel's custom (funcCustom) waveform.

        The AD2's native funcPulse timing nodes are not used here so pulse
        timing (width/rise/fall/delay) is guaranteed WYSIWYG regardless of
        WaveForms SDK version quirks; the waveform is generated in software
        and downloaded, exactly like the "PULS" shape of a standard AWG.
        """
        params = self._get_pulse_params(channel)
        freq = self._current_frequency if getattr(self, '_current_frequency', None) else 1000.0

        n = 2000
        period = 1.0 / freq
        t = np.linspace(0, period, n, endpoint=False)

        width = params['pulse_width'] if params['pulse_width'] is not None else period * (params['duty_cycle'] / 100.0)
        delay = params['pulse_delay']
        rise = max(params['rise_time'], period / n)
        fall = max(params['fall_time'], period / n)

        y = np.zeros(n)
        start = delay
        end = delay + width
        for i, ti in enumerate(t):
            tt = ti % period
            if tt < start:
                y[i] = 0.0
            elif tt < start + rise:
                y[i] = (tt - start) / rise
            elif tt < end - fall:
                y[i] = 1.0
            elif tt < end:
                y[i] = 1.0 - (tt - (end - fall)) / fall
            else:
                y[i] = 0.0

        self._arb_waveforms[f"__pulse_ch{channel}"] = y
        self._load_arb_data(channel, y)

    def _load_arb_data(self, channel, data):
        arr = (ctypes.c_double * len(data))(*[float(v) for v in data])
        self.dwf.FDwfAnalogOutNodeFunctionSet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_ubyte(DWFC.funcCustom))
        self.dwf.FDwfAnalogOutNodeDataSet(self.hdwf, self._ch(channel), self._carrier(), arr, ctypes.c_int(len(data)))

    # --- AWG interface ---

    def output(self, channel=1, on=True):
        self.dwf.FDwfAnalogOutNodeEnableSet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_int(1))
        self.dwf.FDwfAnalogOutConfigure(self.hdwf, self._ch(channel), ctypes.c_int(1 if on else 0))
        self._enabled[channel] = bool(on)

    def set_waveform(self, channel=1, waveform=None):
        if waveform is None:
            raise ValueError("waveform must be provided")
        waveform = waveform.upper()

        if waveform in ('PULS', 'USER'):
            if waveform == 'PULS':
                self._apply_pulse_waveform(channel)
            else:
                name = self._active_arb_name.get(channel)
                if name and name in self._arb_waveforms:
                    self._load_arb_data(channel, self._arb_waveforms[name])
        else:
            func = self._FUNC_MAP.get(waveform)
            if func is None:
                raise ValueError(f"Unsupported waveform '{waveform}' for Analog Discovery 2")
            self.dwf.FDwfAnalogOutNodeFunctionSet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_ubyte(func))

        self._reconfigure_if_active(channel)

    def set_frequency(self, channel=1, frequency=None):
        if frequency is None:
            raise ValueError("frequency must be provided")
        self.dwf.FDwfAnalogOutNodeFrequencySet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_double(frequency))
        self._reconfigure_if_active(channel)

    def set_amplitude(self, channel=1, amplitude=None):
        if amplitude is None:
            raise ValueError("amplitude must be provided")
        self._amplitude_vpp[channel] = amplitude
        self._apply_amplitude(channel)
        self._reconfigure_if_active(channel)

    def set_offset(self, channel=1, offset=None):
        if offset is None:
            raise ValueError("offset must be provided")
        self.dwf.FDwfAnalogOutNodeOffsetSet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_double(offset))
        self._reconfigure_if_active(channel)

    def set_load_impedance(self, channel=1, load_impedance=None):
        if load_impedance is None:
            raise ValueError("load_impedance must be provided")
        print("AnalogDiscovery2Awg: Output impedance is fixed by hardware and is not "
              "software-adjustable; request ignored.")

    def set_polarity(self, channel=1, polarity=None):
        if polarity is None:
            raise ValueError("polarity must be provided")
        polarity = polarity.upper()
        self._polarity[channel] = polarity
        self._apply_amplitude(channel)
        self._reconfigure_if_active(channel)

    def set_square_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self.dwf.FDwfAnalogOutNodeSymmetrySet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_double(duty_cycle))
        self._reconfigure_if_active(channel)

    def set_ramp_symmetry(self, channel=1, symmetry=None):
        if symmetry is None:
            raise ValueError("symmetry must be provided")
        self.dwf.FDwfAnalogOutNodeSymmetrySet(self.hdwf, self._ch(channel), self._carrier(), ctypes.c_double(symmetry))
        self._reconfigure_if_active(channel)

    def set_pulse_width(self, channel=1, pulse_width=None):
        if pulse_width is None:
            raise ValueError("pulse_width must be provided")
        self._get_pulse_params(channel)['pulse_width'] = pulse_width
        self._apply_pulse_waveform(channel)
        self._reconfigure_if_active(channel)

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        if rise_time is None:
            raise ValueError("rise_time must be provided")
        self._get_pulse_params(channel)['rise_time'] = rise_time
        self._apply_pulse_waveform(channel)
        self._reconfigure_if_active(channel)

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        if fall_time is None:
            raise ValueError("fall_time must be provided")
        self._get_pulse_params(channel)['fall_time'] = fall_time
        self._apply_pulse_waveform(channel)
        self._reconfigure_if_active(channel)

    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
            raise ValueError("duty_cycle must be provided")
        self._get_pulse_params(channel)['duty_cycle'] = duty_cycle
        self._apply_pulse_waveform(channel)
        self._reconfigure_if_active(channel)

    def set_pulse_delay(self, channel=1, pulse_delay=None):
        if pulse_delay is None:
            raise ValueError("pulse_delay must be provided")
        self._get_pulse_params(channel)['pulse_delay'] = pulse_delay
        self._apply_pulse_waveform(channel)
        self._reconfigure_if_active(channel)

    # --- Arbitrary waveforms ---

    def create_arb_waveform(self, channel=1, name=None, data=None):
        if name is None:
            raise ValueError("name must be provided")
        if data is None:
            raise ValueError("data must be provided")
        data = np.array(data, dtype=float)
        max_abs = np.max(np.abs(data)) if data.size else 0.0
        self._arb_waveforms[name] = data / max_abs if max_abs > 0 else data

    def set_arb_waveform(self, channel=1, name=None):
        if name is None:
            raise ValueError("name must be provided")
        if name not in self._arb_waveforms:
            raise ValueError(f"Arbitrary waveform '{name}' not found. Create it first.")
        self._active_arb_name[channel] = name
        self._load_arb_data(channel, self._arb_waveforms[name])
        self._reconfigure_if_active(channel)

    # --- Trigger ---

    def set_trigger_source(self, channel=1, trigger_source=None):
        if trigger_source is None:
            raise ValueError("trigger_source must be provided")
        trigsrc = self._TRIGSRC_MAP.get(trigger_source.upper())
        if trigsrc is None:
            raise ValueError(f"Unsupported trigger_source '{trigger_source}' for Analog Discovery 2")
        self.dwf.FDwfAnalogOutTriggerSourceSet(self.hdwf, self._ch(channel), ctypes.c_ubyte(trigsrc))
        self._reconfigure_if_active(channel)

    def set_trigger_level(self, channel=1, trigger_level=None):
        if trigger_level is None:
            raise ValueError("trigger_level must be provided")
        print("AnalogDiscovery2Awg: AnalogOut trigger level is not software-adjustable "
              "(only the trigger source can be selected); request ignored.")

    def set_trigger_slope(self, channel=1, trigger_slope=None):
        if trigger_slope is None:
            raise ValueError("trigger_slope must be provided")
        print("AnalogDiscovery2Awg: AnalogOut trigger slope is not software-adjustable "
              "(only the trigger source can be selected); request ignored.")

    def set_trigger_mode(self, channel=1, trigger_mode=None):
        if trigger_mode is None:
            raise ValueError("trigger_mode must be provided")
        # Only edge-style start/re-trigger is supported by AnalogOut; nothing to write.
