# This driver has not been tested yet
import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class TektronixTDS2000(Scpi, Oscilloscope):
    """
    Driver for the Tektronix TDS 2000 Series Oscilloscope.
    e.g. TDS 2002, TDS 2012, TDS 2022, TDS 2024
    """
    
    # "TEKTRONIX,TDS 2012,..."
    AUTODETECT_ID = "TDS 2"
    
    channel = [1, 2, 3, 4]
    
    # Vertical: 2mV to 5V
    vdiv = (2e-3, 5.0)
    
    y_range = (0.016, 40.0) # 8 divisions * 2mV to 5V
    y_position = (-100.0, 100.0) # approx divisions?
    
    input_coupling = ["AC", "DC", "GND"]
    probe_attenuation = (1.0, 1000.0) # 1x, 10x, 100x, 1000x
    channel_impedance = ["1M"] # Fixed 1M usually
    
    # Timebase: 5ns to 50s
    tdiv = (5e-9, 50.0)
    
    x_range = (50e-9, 500.0) # 10 divisions * 5ns to 50s
    x_position = (-500.0, 500.0)
    
    trigger_source = [1, 2, 3, 4, "EXT", "EXT5", "LINE"]
    trigger_level = (-10.0, 10.0)
    trigger_slope = ["POS", "NEG", "RISE", "FALL"]
    trigger_mode = ["EDGE"]
    trigger_sweep = ["AUTO", "NORM"] # Mapped to mode usually
    
    acquisition_mode = ["NORM", "SAMPLE", "AVERAGE", "PEAKDETECT"]
    acquisition_points = (2500, 2500) # Fixed 2500 usually
    




    def autoscale(self):
        self.instrument.write("AUTOSet EXECute")

    def toggle_channel(self, channel, on=True):
        state = "ON" if on else "OFF"
        self.instrument.write(f"SELect:CH{channel} {state}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        if vdiv is not None:
            self.instrument.write(f"CH{channel}:SCAle {vdiv}")
        elif y_range is not None:
            self.instrument.write(f"CH{channel}:SCAle {y_range / 8.0}")

    def set_vertical_position(self, channel, y_position):
        # Tek uses divisions for position, not volts!
        # This wrapper might need to convert if base class expects volts.
        # But 'y_position' base definition says "in volts".
        # We'll assume the user passes divisions for now or add conversion logic.
        # Or better, check base class docstring: "vertical position in volts"
        # Tek TDS2000 manual: CH<x>:POSition <NR3> (in divisions from center)
        # We need self.vdiv to convert. We can store _current_vdiv if tracked.
        # For now, pass raw value (divisions) and document it, or try to retrieve scale.
        self.instrument.write(f"CH{channel}:POSition {y_position}")

    def set_input_coupling(self, channel, input_coupling):
        self.instrument.write(f"CH{channel}:COUPling {input_coupling}")

    def set_probe_attenuation(self, channel, probe_attenuation):
        # TDS 2000: CH<x>:PROBe {1|10|100|1000}
        self.instrument.write(f"CH{channel}:PROBe {int(probe_attenuation)}")
    
    def set_channel_impedance(self, channel, channel_impedance):
        norm = str(channel_impedance).upper().strip().removesuffix("OHM").strip()
        if norm in ("1M", "1MEG", "1000000", "1E6"):
            pass # TDS 2000 fixed 1M
        else:
            raise ValueError(
                f"channel_impedance {channel_impedance!r} not supported on TektronixTDS2000 (only '1M' supported)"
            )

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        if tdiv is not None:
            self.instrument.write(f"HORizontal:MAIn:SCAle {tdiv}")
        elif x_range is not None:
            self.instrument.write(f"HORizontal:MAIn:SCAle {x_range / 10.0}")

    def set_horizontal_position(self, x_position):
        self.instrument.write(f"HORizontal:MAIn:POSition {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        if tdiv is not None or x_range is not None:
            self.set_horizontal_scale(tdiv=tdiv, x_range=x_range)
        if x_position is not None:
            self.set_horizontal_position(x_position)

    def set_trigger_source(self, trigger_source):
        mapping = {1: 'CH1', 2: 'CH2', 3: 'CH3', 4: 'CH4', '1': 'CH1', '2': 'CH2', '3': 'CH3', '4': 'CH4'}
        src = mapping.get(trigger_source, trigger_source)
        self.instrument.write(f"TRIGger:MAIn:EDGE:SOURce {src}")

    def set_trigger_level(self, trigger_level):
        self.instrument.write(f"TRIGger:MAIn:LEVel {trigger_level}")

    def set_trigger_slope(self, trigger_slope):
        slope_str = str(trigger_slope).upper()
        mapping = {"POS": "RISE", "NEG": "FALL", "RISE": "RISE", "FALL": "FALL"}
        slope = mapping.get(slope_str)
        if slope is None:
            raise ValueError(
                f"trigger_slope {trigger_slope!r} not supported on TektronixTDS2000 (supported: {self.trigger_slope})"
            )
        self.instrument.write(f"TRIGger:MAIn:EDGE:SLOpe {slope}")

    def set_trigger_mode(self, trigger_mode):
        mode = str(trigger_mode).upper()
        if mode not in self.trigger_mode:
            raise ValueError(
                f"trigger_mode {trigger_mode!r} not supported on TektronixTDS2000 (supported: {self.trigger_mode})"
            )
        self.instrument.write(f"TRIGger:MAIn:TYPe {mode}")
    
    def set_trigger_sweep(self, trigger_sweep):
        sweep = str(trigger_sweep).upper()
        if sweep not in self.trigger_sweep:
            raise ValueError(
                f"trigger_sweep {trigger_sweep!r} not supported on TektronixTDS2000 (supported: {self.trigger_sweep})"
            )
        self.instrument.write(f"TRIGger:MAIn:MODE {sweep}")

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None, trigger_sweep=None):
        if trigger_source is not None:
            self.set_trigger_source(trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(trigger_mode)
        if trigger_sweep is not None:
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
        """Prepares and starts single-sequence acquisition."""
        self.instrument.write("ACQuire:STOPAfter SEQuence")
        self.instrument.write("ACQuire:STATE ON")

    def set_acquisition_channel(self, channel):
        self.instrument.write(f"DATa:SOUrce CH{channel}")
        
    def set_acquisition_mode(self, acquisition_mode):
        mode = str(acquisition_mode).upper()
        mapping = {"NORM": "SAMPLE", "NORMAL": "SAMPLE", "SAMPLE": "SAMPLE", "AVERAGE": "AVERAGE", "PEAKDETECT": "PEAKDETECT"}
        mapped = mapping.get(mode)
        if mapped is None:
            raise ValueError(
                f"acquisition_mode {acquisition_mode!r} not supported on TektronixTDS2000 (supported: {self.acquisition_mode})"
            )
        self.instrument.write(f"ACQuire:MODe {mapped}")

    def set_acquisition_points(self, acquisition_points):
        """
        Sets the number of points to transfer for CURVe? queries (1 to 2500).
        TDS2000 record length is fixed at 2500; transfer window is configured
        via DATa:STARt and DATa:STOP.
        """
        pts = min(max(int(acquisition_points), 1), 2500)
        self.instrument.write("DATa:STARt 1")
        self.instrument.write(f"DATa:STOP {pts}")
        self._acquisition_points = pts

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        if channel:
            self.set_acquisition_channel(channel)
        if acquisition_mode:
            self.set_acquisition_mode(acquisition_mode)

    def quick_read(self):
        # 1. Set encoding
        self.instrument.write("DATa:ENCdg RIBinary")
        self.instrument.write("DATa:WIDth 1")
        # 2. Query curve
        raw_data = self.instrument.query_binary_values("CURVe?", datatype='b', is_big_endian=True)
        return np.array(raw_data)

    def get_data(self):
        # Parse preamble
        # YMULT, YOFF, YZERO -> Voltage = (Value - YOFF) * YMULT + YZERO
        # XINCR, XZERO -> Time = Index * XINCR + XZERO
        
        # TDS 2000: WFMPRE?
        
        self.instrument.write("DATa:ENCdg RIBinary")
        self.instrument.write("DATa:WIDth 1")
        
        ymult = float(self.instrument.query("WFMPRE:YMULT?"))
        yoff = float(self.instrument.query("WFMPRE:YOFF?"))
        yzero = float(self.instrument.query("WFMPRE:YZERO?"))
        xincr = float(self.instrument.query("WFMPRE:XINCR?"))
        xzero = float(self.instrument.query("WFMPRE:XZERO?"))
        
        raw_data = self.instrument.query_binary_values("CURVe?", datatype='b', is_big_endian=True)
        
        data_volts = [(val - yoff) * ymult + yzero for val in raw_data]
        data_time = [i * xincr + xzero for i in range(len(raw_data))]
        
        return pd.DataFrame({'Time': data_time, 'Voltage': data_volts})

    def get_measurement(self, channel, measurement_type):
        """
        Uses the scope's built-in measurement engine.
        Tektronix TDS2000: MEASUrement:IMMed:SOUrce CH{ch}; TYPe {type}; VALue?
        """
        MEAS_MAP = {
            'VPP': 'PK2pk', 'VMAX': 'MAXImum', 'VMIN': 'MINImum', 'VRMS': 'RMS',
            'FREQ': 'FREQuency', 'PERIOD': 'PERIod', 'RISE': 'RISe',
            'FALL': 'FALL', 'PWIDTH': 'PWIdth', 'NWIDTH': 'NWIdth',
            'DUTYCYCLE': 'PDUty', 'AMPLITUDE': 'AMPlitude'
        }
        meas = MEAS_MAP.get(measurement_type.upper(), measurement_type)
        self.instrument.write(f"MEASUrement:IMMed:SOUrce CH{channel}")
        self.instrument.write(f"MEASUrement:IMMed:TYPe {meas}")
        result = self.instrument.query("MEASUrement:IMMed:VALue?")
        return float(result)

    def screenshot(self):
        """
        Captures the current display as a PNG image.
        Tektronix TDS2000: HARDCopy format BMP, converted to PNG.
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
