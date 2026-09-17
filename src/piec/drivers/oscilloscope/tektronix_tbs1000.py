import time
import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class TektronixTBS1154(Scpi, Oscilloscope):
    """
    Driver for the Tektronix TBS1000 Series Oscilloscope.
    e.g. TBS1052B, TBS1072B, TBS1102B, TBS1104, TBS1152B, TBS1154, TBS1202B, TBS1204

    Verified against real TBS1154 hardware. The command set is shared with
    the older TDS2000 series (same TRIGger:MAIn:*/HORizontal:MAIn:* command
    namespace, not the newer TRIGger:A:* namespace used on higher-end Tek
    scopes) -- see TektronixTDS2000 for that driver. One confirmed
    difference: the TBS1000 series transfers CURVe? data as 16-bit values
    (DATa:WIDth 2), not the TDS2000's 8-bit (DATa:WIDth 1).

    AUTODETECT_ID is scoped to "TBS 1154" specifically rather than the whole
    "TBS 1" family since other models in the series have different channel
    counts (2 vs 4) and bandwidths.
    """

    # "TEKTRONIX,TBS 1154,C010298,CF:91.1CT FV:v26.05"
    AUTODETECT_ID = "TBS 1154"

    channel = [1, 2, 3, 4]

    # Vertical: 2mV to 5V
    vdiv = (2e-3, 5.0)

    y_range = None
    y_position = (-100.0, 100.0) # approx divisions?

    input_coupling = ["AC", "DC"]
    probe_attenuation = (1.0, 1000.0) # 1x, 10x, 100x, 1000x
    channel_impedance = None # Fixed 1M

    # Timebase: 5ns to 50s
    tdiv = (5e-9, 50.0)

    x_range = None
    x_position = None

    trigger_source = [1, 2, 3, 4, "EXT", "LINE"]
    trigger_level = (-10.0, 10.0)
    trigger_slope = ["RISE", "FALL"]
    trigger_mode = ["AUTO", "NORM"]
    trigger_sweep = ["AUTO", "NORM"] # Mapped to mode usually

    acquisition_mode = ["SAMPLE", "AVERAGE", "PEAKDETECT"]
    acquisition_points = (2500, 2500) # Fixed 2500 usually
    max_sample_rate = 1e9  # 1 GS/s per channel, simultaneously on all channels (Tektronix datasheet)

    def autoscale(self):
        self.instrument.write("AUTOSet EXECute")

    def toggle_channel(self, channel, on=True):
        state = "ON" if on else "OFF"
        self.instrument.write(f"SELect:CH{channel} {state}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        # The display is 8 vertical divisions (standard across the whole
        # TBS/TDS Tek family), so a full-scale y_range converts directly.
        # Without this, callers that only pass y_range (e.g.
        # FrequencyResponse's autoranging) would silently be no-ops here --
        # the scope's V/div would never actually change.
        if vdiv is None and y_range is not None:
            vdiv = y_range / 8.0
        if vdiv:
            self.instrument.write(f"CH{channel}:SCAle {vdiv}")

    def set_vertical_position(self, channel, y_position):
        # Tek uses divisions for position, not volts (CH<x>:POSition <NR3>, divisions from center)
        self.instrument.write(f"CH{channel}:POSition {y_position}")

    def set_input_coupling(self, channel, input_coupling):
        self.instrument.write(f"CH{channel}:COUPling {input_coupling}")

    def set_probe_attenuation(self, channel, probe_attenuation):
        self.instrument.write(f"CH{channel}:PRObe {int(probe_attenuation)}")

    def set_channel_impedance(self, channel, channel_impedance):
        # Fixed 1M, no command to change it.
        pass

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        if tdiv:
            self.instrument.write(f"HORizontal:MAIn:SCAle {tdiv}")

    def set_horizontal_position(self, x_position):
        self.instrument.write(f"HORizontal:MAIn:POSition {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        if tdiv:
            self.set_horizontal_scale(tdiv=tdiv)
        if x_position:
            self.set_horizontal_position(x_position)

    def set_trigger_source(self, trigger_source):
        mapping = {1: 'CH1', 2: 'CH2', 3: 'CH3', 4: 'CH4', '1': 'CH1', '2': 'CH2', '3': 'CH3', '4': 'CH4'}
        src = mapping.get(trigger_source, trigger_source)
        self.instrument.write(f"TRIGger:MAIn:EDGE:SOURce {src}")

    def set_trigger_level(self, trigger_level):
        self.instrument.write(f"TRIGger:MAIn:LEVel {trigger_level}")

    def set_trigger_slope(self, trigger_slope):
        # Tek: RISe, FALL
        slope = "RIS" if "POS" in str(trigger_slope).upper() else "FALL"
        if trigger_slope in ["RISE", "FALL"]: slope = trigger_slope
        self.instrument.write(f"TRIGger:MAIn:EDGE:SLOpe {slope}")

    def set_trigger_mode(self, trigger_mode):
        self.instrument.write(f"TRIGger:MAIn:TYPe {trigger_mode}")

    def set_trigger_sweep(self, trigger_sweep):
        self.instrument.write(f"TRIGger:MAIn:MODE {trigger_sweep}")

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None, trigger_sweep=None):
        if trigger_source:
            self.set_trigger_source(trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(trigger_level)
        if trigger_slope:
            self.set_trigger_slope(trigger_slope)
        if trigger_mode:
            self.set_trigger_mode(trigger_mode)
        if trigger_sweep:
            self.set_trigger_sweep(trigger_sweep)

    def manual_trigger(self):
        """Sends a manual force trigger event to the oscilloscope."""
        self.instrument.write("TRIGger FORCe")

    def toggle_acquisition(self, run=True):
        if run:
            self.instrument.write("ACQuire:STATE ON")
        else:
            self.instrument.write("ACQuire:STATE OFF")

    def arm(self):
        # Single shot
        self.instrument.write("ACQuire:STOPAfter SEQuence") # Single trigger mode
        self.instrument.write("ACQuire:STATE ON")

    def set_acquisition(self):
        pass # Set up mode/channel first, then query curve

    def set_acquisition_channel(self, channel):
        self.instrument.write(f"DATa:SOUrce CH{channel}")

    def set_acquisition_mode(self, acquisition_mode):
        # SAMPLE, PEAKDETECT, AVERAGE
        self.instrument.write(f"ACQuire:MODe {acquisition_mode}")

    def set_acquisition_points(self, acquisition_points):
        # Fixed 2500 usually
        pass

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        if channel:
            self.set_acquisition_channel(channel)
        if acquisition_mode:
            self.set_acquisition_mode(acquisition_mode)

    def quick_read(self):
        # Confirmed on real hardware: TBS1000 CURVe? data is 16-bit (not the
        # TDS2000's 8-bit), signed, big-endian ("h", matching DATa:WIDth 2).
        self.instrument.write("DATa:ENCdg RIBinary")
        self.instrument.write("DATa:WIDth 2")
        raw_data = self.instrument.query_binary_values("CURVe?", datatype='h', is_big_endian=True)
        return np.array(raw_data)

    def get_data(self):
        # Parse preamble
        # YMULT, YOFF, YZERO -> Voltage = (Value - YOFF) * YMULT + YZERO
        # XINCR, XZERO, PT_OFF -> Time = (Index - PT_OFF) * XINCR + XZERO
        self.instrument.write("DATa:ENCdg RIBinary")
        self.instrument.write("DATa:WIDth 2")

        ymult = float(self.instrument.query("WFMPRE:YMULT?"))
        yoff = float(self.instrument.query("WFMPRE:YOFF?"))
        yzero = float(self.instrument.query("WFMPRE:YZERO?"))
        xincr = float(self.instrument.query("WFMPRE:XINCR?"))
        xzero = float(self.instrument.query("WFMPRE:XZERO?"))
        pt_off = float(self.instrument.query("WFMPRE:PT_Off?"))

        raw_data = self.instrument.query_binary_values("CURVe?", datatype='h', is_big_endian=True)

        data_volts = [(val - yoff) * ymult + yzero for val in raw_data]
        data_time = [(i - pt_off) * xincr + xzero for i in range(len(raw_data))]

        return pd.DataFrame({'Time': data_time, 'Voltage': data_volts})

    def get_multi_channel_data(self, channels=None):
        """
        Arms a single acquisition and reads back two or more channels from
        that same acquisition event, for measurements (e.g. a Bode sweep)
        that need input/output sampled simultaneously rather than via
        separate, independently-triggered captures.

        args:
            channels (list[int]): Channels to read. Defaults to self.channel.
        returns:
            data (DataFrame): 'Time' plus one 'Channel <n>' column per requested channel.
        """
        if channels is None:
            channels = list(self.channel)

        self.instrument.write("ACQuire:STOPAfter SEQuence")
        self.instrument.write("ACQuire:STATE ON")

        # Bounded to a few seconds, not the scope's own (much longer) AUTO
        # trigger fallback -- in an automated sweep, a single unmeasurable
        # point should time out and move on quickly, not stall the run.
        timeout = time.time() + 3.0
        while True:
            state = self.instrument.query("ACQuire:STATE?").strip()
            if state in ("0", "STOP", "STOPPED"):
                break
            if time.time() > timeout:
                print("TektronixTBS1154: Acquisition timed out waiting for trigger.")
                break
            time.sleep(0.01)

        self.instrument.write("DATa:ENCdg RIBinary")
        self.instrument.write("DATa:WIDth 2")

        df_data = {}
        t = None
        for channel in channels:
            self.instrument.write(f"DATa:SOUrce CH{channel}")
            ymult = float(self.instrument.query("WFMPRE:YMULT?"))
            yoff = float(self.instrument.query("WFMPRE:YOFF?"))
            yzero = float(self.instrument.query("WFMPRE:YZERO?"))
            xincr = float(self.instrument.query("WFMPRE:XINCR?"))
            xzero = float(self.instrument.query("WFMPRE:XZERO?"))
            pt_off = float(self.instrument.query("WFMPRE:PT_Off?"))

            raw_data = self.instrument.query_binary_values("CURVe?", datatype='h', is_big_endian=True)
            volts = (np.array(raw_data) - yoff) * ymult + yzero
            df_data[f"Channel {channel}"] = volts

            if t is None:
                n = len(volts)
                t = (np.arange(n) - pt_off) * xincr + xzero

        return pd.DataFrame({"Time": t, **df_data})

    def screenshot(self):
        """
        Captures the current display as a PNG image.
        Tektronix TBS1000: HARDCopy format BMP, converted to PNG.
        returns:
            (bytes): PNG image data
        """
        from io import BytesIO
        try:
            from PIL import Image
        except ImportError:
            print("screenshot() requires Pillow for BMP→PNG conversion. Install with: pip install Pillow")
            return None
        self.instrument.write("HARDCopy:FORMat BMP")
        self.instrument.write("HARDCopy:PORT GPI")
        raw = self.instrument.query_binary_values("HARDCopy STARt", datatype='B')
        bmp_data = bytes(raw)
        img = Image.open(BytesIO(bmp_data))
        png_buffer = BytesIO()
        img.save(png_buffer, format='PNG')
        return png_buffer.getvalue()
