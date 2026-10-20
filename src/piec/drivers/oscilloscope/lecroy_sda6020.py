"""
Driver for the Teledyne LeCroy SDA 6020 Oscilloscope.
This class implements the specific functionalities for the SDA 6020 model,
inheriting from generic Oscilloscope and Scpi classes.
"""

import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi
import struct

class LeCroySDA6020(Scpi, Oscilloscope):
    """
    Driver for the Teledyne LeCroy SDA 6020 Oscilloscope.
    """

    AUTODETECT_ID = "SDA6020"
    AI_STATUS = "assisted"
    HARDWARE_TESTED = False  # Updated multi-channel acquisition needs bench verification

    channel = [1, 2, 3, 4]
    vdiv = (0.002, 1.0)              # 2 mV/div to 1 V/div (50 Ohm only)
    y_range = (0.016, 8.0)           # 8 div * vdiv
    y_position = (-4.0, 4.0)         # ±4V max offset
    input_coupling = ["DC", "GND"]   # 50 Ohm only, no AC coupling
    probe_attenuation = (0.001, 10000.0)
    channel_impedance = ["50"]        # 50 Ohm only
    tdiv = (20e-12, 1000.0)          # 20 ps/div to 1000 s/div
    x_range = (200e-12, 10000.0)     # 10 div * tdiv
    x_position = (-10000.0, 10000.0)
    trigger_source = [1, 2, 3, 4, "EXT", "EX10", "LINE"]
    trigger_level = (-4.0, 4.0)      # ±4V max input
    trigger_slope = ["POS", "NEG"]
    trigger_mode = ["EDGE"]
    trigger_sweep = ["AUTO", "NORM", "SINGLE", "STOP"]
    acquisition_mode = ["NORM"]
    acquisition_points = (1, 48000000)  # Up to 48 Mpts/Ch with option

    def autoscale(self):
        """
        Autoscales the oscilloscope
        """
        self.instrument.write("AUTO_SETUP")

    def reset(self):
        """
        Resets the oscilloscope to factory defaults with trigger in AUTO mode.

        Unlike *RST (which leaves the trigger in STOP mode, keeping old data
        visible), this uses the VBS automation command that mirrors the front-panel
        'Recall Default' button — resetting all settings AND starting fresh
        acquisition in AUTO trigger mode so old waveforms are cleared.
        """
        self.instrument.write("VBS 'app.SaveRecall.Setup.DoRecallDefaultPanelWithTriggerModeAuto'")
        self._initialize_state()
        self._current_acquisition_channel = None

    def toggle_channel(self, channel, on=True):
        """
        Function that toggles the selected channel to on or off
        """
        state = "ON" if on else "OFF"
        self.instrument.write(f"C{channel}:TRACE {state}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        """
        Function that sets the vertical scale in either volts per divison or absolute range
        """
        if vdiv is not None:
            self.instrument.write(f"C{channel}:VDIV {vdiv}")
        if y_range is not None:
            # LeCroy doesn't directly support V_range, calculate VDIV
            vdiv_calc = y_range / 8.0 
            self.instrument.write(f"C{channel}:VDIV {vdiv_calc}")

    def set_vertical_position(self, channel, y_position=None):
        """
        Sets the vertical position of the scale (offset)
        """
        if y_position is not None:
            self.instrument.write(f"C{channel}:OFFSET {y_position}")

    def set_input_coupling(self, channel, input_coupling=None):
        """
        Sets the input coupling. SDA 6020 is 50 Ohm only: DC or GND.
        """
        if input_coupling is not None:
            coupling = str(input_coupling).upper()
            if coupling == "DC":
                self.instrument.write(f"C{channel}:COUPLING D50")
            elif coupling == "GND":
                self.instrument.write(f"C{channel}:COUPLING GND")
            else:
                raise ValueError(
                    f"input_coupling {input_coupling!r} not supported on LeCroySDA6020 (supported: {self.input_coupling})"
                )

    def set_probe_attenuation(self, channel, probe_attenuation=None):
        """
        Sets the probe attenuation
        """
        if probe_attenuation is not None:
             self.instrument.write(f"C{channel}:ATTENUATION {probe_attenuation}")

    def set_channel_impedance(self, channel, channel_impedance=None):
        """
        The SDA 6020 is 50 Ohm only. This method exists for interface
        compatibility but only accepts '50'.
        """
        if channel_impedance is not None:
            imp = str(channel_impedance).upper().strip().removesuffix("OHM").strip()
            if imp in ("50", "FIFTY"):
                self.instrument.write(f"C{channel}:COUPLING D50")
            else:
                raise ValueError(
                    f"channel_impedance {channel_impedance!r} not supported on LeCroySDA6020 (only '50' supported)"
                )

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        """
        Sets the timebase in either time/division or in absolute range
        """
        if tdiv is not None:
            self.instrument.write(f"TIME_DIV {tdiv}")
        if x_range is not None:
            # LeCroy has 10 divisons horizontally
            tdiv_calc = x_range / 10.0
            self.instrument.write(f"TIME_DIV {tdiv_calc}")

    def set_horizontal_position(self, x_position=None):
        """ 
        Changes the position (delay) of the timebase
        """
        if x_position is not None:
            self.instrument.write(f"TRDL {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        """
        Combines calls to set_horizontal_scale and set_horizontal_position
        """
        if tdiv is not None or x_range is not None:
            self.set_horizontal_scale(tdiv=tdiv, x_range=x_range)
        if x_position is not None:
            self.set_horizontal_position(x_position=x_position)

    def wait(self):
        """
        Waits until the current acquisition has completed.

        Uses LeCroy's WAIT command instead of *WAI, which specifically blocks
        until acquisition is finished.
        """
        try:
            self.instrument.write("WAIT")
        except Exception as e:
            print(f"Warning: WAIT failed — {e}")

    def _to_lecroy_source(self, source):
        """
        Translates a user-facing trigger source value to LeCroy command syntax.
        e.g. int 1 -> 'C1', 'EXT' -> 'EX', 'EX10' -> 'EX10', 'LINE' -> 'LINE'
        """
        if isinstance(source, int):
            return f"C{source}"
        elif source == "EXT":
            return "EX"
        return source

    def _get_lecroy_trigger_source(self):
        """
        Returns the current trigger source in LeCroy command syntax.
        Uses the cached _current_trigger_source, falling back to 'C1'.
        """
        src = getattr(self, '_current_trigger_source', None)
        if src is None:
            return "C1"
        return self._to_lecroy_source(src)

    def set_trigger_source(self, trigger_source=None):
        """
        Decides what the scope should trigger on
        """
        if trigger_source is not None:
            src = self._to_lecroy_source(trigger_source)
            self.instrument.write(f"TRIG_SELECT EDGE,SR,{src}")

    def set_trigger_level(self, trigger_level=None):
        """
        The voltage level the signal must cross to initiate a capture.
        Applies the level to the currently active trigger source.
        """
        if trigger_level is not None:
            src = self._get_lecroy_trigger_source()
            self.instrument.write(f"{src}:TRLV {trigger_level}")

    def set_trigger_slope(self, trigger_slope=None):
        """
        Changes the trigger slope of the active trigger source.
        Valid values: POS, NEG.
        """
        if trigger_slope is not None:
            slope = str(trigger_slope).upper()
            if slope not in self.trigger_slope:
                raise ValueError(
                    f"trigger_slope {trigger_slope!r} not supported on LeCroySDA6020 (supported: {self.trigger_slope})"
                )
            src = self._get_lecroy_trigger_source()
            self.instrument.write(f"{src}:TRIG_SLOPE {slope}")

    def set_trigger_mode(self, trigger_mode=None):
        """
        Sets the trigger type (e.g., EDGE) via TRIG_SELECT.
        On LeCroy scopes the trigger type is part of TRIG_SELECT, not a
        separate command.
        """
        if trigger_mode is not None:
            src = self._get_lecroy_trigger_source()
            self.instrument.write(f"TRIG_SELECT {trigger_mode},SR,{src}")

    def set_trigger_sweep(self, trigger_sweep=None):
        """
        Changes the trigger sweep settings
        """
        if trigger_sweep is not None:
            self.instrument.write(f"TRIG_MODE {trigger_sweep}")

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None, trigger_sweep=None):
        """
        Combines all the trigger commands into one
        """
        if trigger_source is not None:
            self.set_trigger_source(trigger_source=trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(trigger_level=trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(trigger_slope=trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(trigger_mode=trigger_mode)
        if trigger_sweep is not None:
            self.set_trigger_sweep(trigger_sweep=trigger_sweep)

    def manual_trigger(self):
        """
        Sends a manual force trigger event
        """
        self.instrument.write("ARM")
        self.instrument.write("FRTR")

    def toggle_acquisition(self, run=True):
        """
        Start or halt the process of capturing data
        """
        if run:
            self.set_trigger_sweep("NORM")
        else:
            self.instrument.write("STOP")

    def arm(self):
        """
        Tells the scope to get ready to capture
        """
        self.instrument.write("ARM")

    def set_acquisition(self):
        """
        Prepares the acquisition
        """
        self.instrument.write("COMM_FORMAT DEF9,WORD,BIN")
        self.instrument.write("COMM_HEADER OFF")
        self.instrument.write("COMM_ORDER LO")
        # Transfer the entire record (NP=0), clearing any previous slicing.
        # MEMORY_SIZE controls acquisition memory; the actual record can have
        # extra points. Capping NP at the requested memory size can leave the
        # descriptor's LAST_VALID_PNT outside the transferred data array.
        self.instrument.write("WAVEFORM_SETUP SP,1,NP,0,FP,0,SN,0")

    def set_acquisition_channel(self, channel=None):
        """
        Sets the scope to return the selected channel when asked for data
        """
        # Data reading in LeCroy is often prefix-based (e.g. C1:WF?), so simply setting state here
        self._current_acquisition_channel = channel

    def set_acquisition_mode(self, acquisition_mode=None):
        """
        Sets the acquisition/sampling mode on the LeCroy oscilloscope.
        Supported modes: RealTime (normal single-shot), Sequence, RIS.
        """
        if acquisition_mode is None:
            return
        mode = str(acquisition_mode).upper()
        mapping = {
            "NORM": "RealTime",
            "NORMAL": "RealTime",
            "REAL_TIME": "RealTime",
            "REALTIME": "RealTime",
            "SINGLE_SHOT": "RealTime",
            "RIS": "RIS",
            "SEQUENCE": "Sequence",
            "SEQ": "Sequence",
        }
        vbs_mode = mapping.get(mode, "RealTime")
        self.instrument.write(f"VBS 'app.Acquisition.Horizontal.SampleMode = \"{vbs_mode}\"'")
        self._acquisition_mode = vbs_mode

    def set_acquisition_points(self, acquisition_points=None):
        if acquisition_points is not None:
             self.instrument.write(f"MEMORY_SIZE {acquisition_points}")

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        """
        Configures the scope for data reading.

        channel (int or list[int]): One channel or a nonempty list of supported
            channels, in the desired output order. None retains the selection.
            Enable the input traces with toggle_channel before acquiring.
        acquisition_mode (str): Normal real-time acquisition ('NORM').
        acquisition_points (int): Requested acquisition memory size; the scope
            rounds to a supported size and may include extra record points.
            The entire record is transferred so its descriptor remains valid.
        """
        if channel is not None:
            if isinstance(channel, list) and (not channel or len(set(channel)) != len(channel)):
                raise ValueError("Select a nonempty list of distinct channels")
            # The scalar setter is deliberately not used for a list. AutoCheckMeta
            # inherits the parent's annotation and validates each selected channel.
            self._current_acquisition_channel = channel.copy() if isinstance(channel, list) else channel
        if acquisition_mode is not None:
            self.set_acquisition_mode(acquisition_mode=acquisition_mode)
        if acquisition_points is not None:
            self.set_acquisition_points(acquisition_points=acquisition_points)

    def get_data(self):
        """
        Returns a Pandas DataFrame for the selected or, by default, displayed inputs.

        One channel returns 'Time', 'Voltage'; multiple channels return 'Time',
        'CH1', 'CH2', etc., in selection order. Each channel uses its own scaling.
        Running acquisition is paused during transfer and then resumed. A pending
        single acquisition is allowed to finish first (subject to the VISA timeout).
        Multi-channel records use C1's time axis when C1 is selected, otherwise
        the first selected channel's. Samples share the acquisition timebase;
        per-channel timestamp differences are ignored without resampling voltages.
        Raises ValueError for invalid descriptors or unequal channel record lengths.
        Only real-time records are supported; segmented and RIS records require
        different timing decoding.

        Protocol and descriptor layout: WM-RCM-E Rev D, pp. 57-58, 112, 257-258,
        and Appendix II (https://cdn.teledynelecroy.com/files/manuals/wm-rcm-e_rev_d.pdf).
        """
        self.set_acquisition()
        channels = getattr(self, "_current_acquisition_channel", None)
        if channels is None:
            channels = [ch for ch in self.channel
                        if self.instrument.query(f"C{ch}:TRACE?").strip().upper() == "ON"]
        elif not isinstance(channels, list):
            channels = [channels]
        if not channels:
            raise ValueError("No input channels are selected or displayed")

        trigger_mode = self.instrument.query("TRIG_MODE?").strip().upper()
        if trigger_mode == "SINGLE":
            self.instrument.query("WAIT;*OPC?")
        try:
            self.instrument.write("STOP")
            data = {}
            # Read the shared time reference first; retain the requested column order.
            read_channels = [1] + [ch for ch in channels if ch != 1] if 1 in channels else channels
            for channel in read_channels:
                times, volts = self._read_waveform(channel)
                if data:
                    if len(data['Time']) != len(volts):
                        raise ValueError(f"C{channel} has a different sample count; cannot combine channels")
                else:
                    data['Time'] = times
                data['Voltage' if len(channels) == 1 else f'CH{channel}'] = volts
            columns = ['Time', 'Voltage'] if len(channels) == 1 else ['Time'] + [f'CH{ch}' for ch in channels]
            return pd.DataFrame(data, columns=columns)
        finally:
            if trigger_mode in ("AUTO", "NORM"):
                self.instrument.write(f"TRIG_MODE {trigger_mode}")

    def _read_waveform(self, channel):
        """Decode one real-time waveform using the documented WAVEDESC offsets."""
        desc = bytes(self.instrument.query_binary_values(f"C{channel}:WF? DESC", datatype='B'))
        if len(desc) < 346 or not desc.startswith(b'WAVEDESC'):
            raise ValueError(f"C{channel}: invalid waveform descriptor")
        if struct.unpack_from('<hh', desc, 32) != (1, 1):
            raise ValueError(f"C{channel}: expected little-endian WORD waveform")
        if struct.unpack_from('<i', desc, 144)[0] > 1 or any(struct.unpack_from('<ii', desc, 48)):
            raise ValueError(f"C{channel}: segmented or RIS waveforms are not supported")
        v_gain, v_offset = struct.unpack_from('<ff', desc, 156)
        h_gain, h_offset = struct.unpack_from('<fd', desc, 176)
        if not np.isfinite([v_gain, v_offset, h_gain, h_offset]).all() or v_gain <= 0 or h_gain <= 0:
            raise ValueError(f"C{channel}: invalid waveform scaling")
        raw_data = np.asarray(self.instrument.query_binary_values(
            f"C{channel}:WF? DAT1", datatype='h', is_big_endian=False))
        count = struct.unpack_from('<i', desc, 116)[0]
        first, last = struct.unpack_from('<ii', desc, 124)
        if len(raw_data) != count or not (0 <= first <= last < count):
            raise ValueError(
                f"C{channel}: incomplete waveform data "
                f"(received={len(raw_data)}, expected={count}, first={first}, last={last})"
            )
        # Discard padding while retaining the samples' positions in the record.
        times = np.arange(first, last + 1) * h_gain + h_offset
        volts = raw_data[first:last + 1] * v_gain - v_offset
        return times, volts

    def get_measurement(self, channel, measurement_type):
        """
        Uses the scope's built-in measurement engine.
        LeCroy SDA6020: C{ch}:PAVA? {type}
        """
        MEAS_MAP = {
            'VPP': 'PKPK', 'VMAX': 'MAX', 'VMIN': 'MIN', 'VRMS': 'RMS',
            'FREQ': 'FREQ', 'PERIOD': 'PER', 'RISE': 'RISE',
            'FALL': 'FALL', 'PWIDTH': 'WIDLV', 'NWIDTH': 'NWID',
            'DUTYCYCLE': 'DUTY', 'AMPLITUDE': 'AMPL'
        }
        meas = MEAS_MAP.get(measurement_type.upper(), measurement_type)
        result = self.instrument.query(f"C{channel}:PAVA? {meas}")
        # LeCroy returns "C1:PAVA FREQ,1.234e6 Hz" — parse the value
        try:
            value_str = result.split(',')[1].split()[0]
            return float(value_str)
        except (IndexError, ValueError):
            return float(result)

    def screenshot(self):
        """
        Captures the current display as a PNG image.
        LeCroy SDA6020: HCSU configures the hardcopy destination to REMOTE
        so that SCDP sends the BMP data back over VISA instead of to a
        local file or printer.

        returns:
            (bytes): PNG image data
        """
        from io import BytesIO
        try:
            from PIL import Image
        except ImportError:
            print("screenshot() requires Pillow for BMP→PNG conversion. Install with: pip install Pillow")
            return None
        original_timeout = self.instrument.timeout
        self.instrument.timeout = 30000  # 30s for screen capture transfer
        try:
            # Configure hardcopy: BMP format, send to remote (VISA) port
            self.instrument.write("HARDCOPY_SETUP DEV,BMP,DEST,REMOTE,PORT,NET")
            self.instrument.write("SCDP")
            raw = self.instrument.read_raw()
            img = Image.open(BytesIO(raw))
            png_buffer = BytesIO()
            img.save(png_buffer, format='PNG')
            return png_buffer.getvalue()
        finally:
            self.instrument.timeout = original_timeout
