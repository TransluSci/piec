import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class TDS6604(Oscilloscope, Scpi):
    """
    Driver for the Tektronix TDS 6604 Oscilloscope.
    """
    
    AUTODETECT_ID = "TDS6604"
    channel = [1, 2, 3, 4]
    
    vdiv = (0.001, 10.0)
    y_range = None
    y_position = None
    
    input_coupling = ["AC", "DC", "GND"]
    probe_attenuation = (1.0, 1000.0)
    channel_impedance = ["FIFTY", "ONEMEG"]
    
    tdiv = (100e-12, 10.0)
    x_range = None
    x_position = None
    
    trigger_source = [1, 2, 3, 4, "EXT", "LINE"]
    trigger_level = None
    trigger_slope = ["RISE", "FALL"]
    trigger_mode = ["AUTO", "NORMAL"]
    trigger_sweep = ["AUTO", "NORMAL"]
    
    acquisition_mode = ["SAMPLE", "AVERAGE", "PEAKDETECT", "ENVELOPE"]
    acquisition_points = None

    # Child-specific class attributes (auto-optional — not in parent Oscilloscope)
    bandwidth = ["FULL", 20e6, 250e6]  # FULL=6GHz, 20e6=20MHz, 250e6=250MHz

    def autoscale(self):
        """Autoscales the oscilloscope"""
        self.instrument.write("AUTOSet EXECute")

    def toggle_channel(self, channel, on=True):
        """Toggles the selected channel to on or off"""
        state = "ON" if on else "OFF"
        self.instrument.write(f"SELect:CH{channel} {state}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        """Sets the vertical scale in either volts per divison or absolute range"""
        if vdiv is not None:
            self.instrument.write(f"CH{channel}:SCAle {vdiv}")
        elif y_range is not None:
            self.instrument.write(f"CH{channel}:SCAle {y_range / 10.0}")

    def set_vertical_position(self, channel, y_position):
        """Sets the vertical position of the scale"""
        self.instrument.write(f"CH{channel}:POSition {y_position}")

    def set_input_coupling(self, channel, input_coupling):
        """Sets the input coupling, e.g. AC, DC, Ground"""
        self.instrument.write(f"CH{channel}:COUPling {input_coupling}")

    def set_probe_attenuation(self, channel, probe_attenuation):
        """Sets the probe attenuation e.g. 1x, 10x etc"""
        self.instrument.write(f"CH{channel}:PRObe {probe_attenuation}")

    def set_channel_impedance(self, channel, channel_impedance):
        """Sets the channel impedance, e.g. 1MOhm, 50Ohm"""
        if channel_impedance == '50':
            self.instrument.write(f"CH{channel}:IMPedance FIFTY")
        elif channel_impedance == '1M':
            self.instrument.write(f"CH{channel}:IMPedance ONEMEG")
        else:
            self.instrument.write(f"CH{channel}:IMPedance {channel_impedance}")

    def set_channel_bandwidth(self, channel, bandwidth):
        """
        Sets the bandwidth limit for the specified channel.
        
        This is a TDS6604-specific method (auto-optional). If measurement code
        calls this on a scope that doesn't support it, it will be skipped.
        
        args:
            channel (int): The channel to set the bandwidth on
            bandwidth: The bandwidth setting — 'FULL' (6GHz), 20 (20MHz), or 250 (250MHz)
        """
        BANDWIDTH_MAP = {20e6: 'TWEnty', 250e6: 'TWOfifty', 'FULL': 'FULl'}
        bw = BANDWIDTH_MAP.get(bandwidth, bandwidth)
        self.instrument.write(f"CH{channel}:BANdwidth {bw}")

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        """Sets the timebase in either time/division or in absolute range"""
        if tdiv is not None:
            self.instrument.write(f"HORizontal:MAIN:SCAle {tdiv}")
        elif x_range is not None:
            self.instrument.write(f"HORizontal:MAIN:SCAle {x_range / 10.0}")

    def set_horizontal_position(self, x_position):
        """Changes the position (delay) of the timebase"""
        self.instrument.write(f"HORizontal:DELay:TIMe {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        """Combines into one function calls set_horizontal_scale and set_horizontal_position"""
        if tdiv or x_range:
            self.set_horizontal_scale(tdiv=tdiv, x_range=x_range)
        if x_position:
            self.set_horizontal_position(x_position)

    def set_trigger_source(self, trigger_source):
        """Decides what the scope should trigger on"""
        mapping = {1: 'CH1', 2: 'CH2', 3: 'CH3', 4: 'CH4', '1': 'CH1', '2': 'CH2', '3': 'CH3', '4': 'CH4'}
        src = mapping.get(trigger_source, trigger_source)
        self.instrument.write(f"TRIGger:A:EDGE:SOURce {src}")

    def set_trigger_level(self, trigger_level):
        """The voltage level the signal must cross to initiate a capture"""
        self.instrument.write(f"TRIGger:A:LEVel {trigger_level}")

    def set_trigger_slope(self, trigger_slope):
        """Changes the trigger from falling, rising etc"""
        mapping = {'POS': 'RISE', 'NEG': 'FALL', 'RISING': 'RISE', 'FALLING': 'FALL'}
        slope = mapping.get(trigger_slope.upper(), trigger_slope.upper())
        self.instrument.write(f"TRIGger:A:EDGE:SLOpe {slope}")

    def set_trigger_mode(self, trigger_mode):
        """Changes the mode from auto, norm, manual, single, etc"""
        self.instrument.write(f"TRIGger:A:TYPe {trigger_mode.upper()}")

    def set_trigger_sweep(self, trigger_sweep):
        """Changes the trigger sweep settings of the oscilloscope"""
        self.instrument.write(f"TRIGger:A:MODe {trigger_sweep.upper()}")

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None, trigger_sweep=None):
        """Combines all the trigger commands into one"""
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
        """Start or halt the process of capturing data"""
        if run:
            self.instrument.write("ACQuire:STOPAfter RUNSTOP")
            self.instrument.write("ACQuire:STATE RUN")
        else:
            self.instrument.write("ACQuire:STATE STOP")

    def arm(self):
        """Tells the scope to get ready to capture the data for the single shot etc"""
        self.instrument.write("ACQuire:STOPAfter SEQuence")
        self.instrument.write("ACQuire:STATE RUN")

    def set_acquisition(self):
        """Sets the oscilloscope to capture the data as set up on the configure_acquisition commands to be ready for a transfer"""
        self.arm()

    def set_acquisition_channel(self, channel):
        """Sets the scope to return the selected channel when asked for data"""
        self._target_acquire_channel = channel

    def set_acquisition_mode(self, acquisition_mode):
        """Sets the acusition mode on the scope (e.g. normal, average, peak detect etc)"""
        mapping = {'NORMAL': 'SAMPLE', 'AVERAGE': 'AVERAGE', 'PEAK': 'PEAKDETECT', 'ENVELOPE': 'ENVELOPE'}
        mode = mapping.get(acquisition_mode.upper(), acquisition_mode.upper())
        self.instrument.write(f"ACQuire:MODe {mode}")

    def set_acquisition_points(self, acquisition_points):
        """Sets the scope to return the given number of points when asked for data"""
        self.instrument.write(f"HORizontal:RECOrdlength {int(acquisition_points)}")

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        """Configures the scope to specific parameters such as length"""
        if channel:
            self.set_acquisition_channel(channel)
        if acquisition_mode:
            self.set_acquisition_mode(acquisition_mode)
        if acquisition_points:
            self.set_acquisition_points(acquisition_points)

    def quick_read(self):
        """Quick read function that returns the default data in a numpy array."""
        ch = getattr(self, '_target_acquire_channel', 1)
        record_length = int(float(self.instrument.query("HORizontal:RECOrdlength?")))
        self.instrument.write(f"DATa:SOURce CH{ch};ENCdg RIBINARY;WIDth 2;STARt 1;STOP {record_length}")
        
        raw_data = self.instrument.query_binary_values('CURVe?', datatype='h', is_big_endian=True)
        return np.array(raw_data)

    def get_data(self):
        """Returns the data depending on how it was configured with the configure_acquisition command."""
        ch = getattr(self, '_target_acquire_channel', 1)
        record_length = int(float(self.instrument.query("HORizontal:RECOrdlength?")))
        self.instrument.write(f"DATa:SOURce CH{ch};ENCdg RIBINARY;WIDth 2;STARt 1;STOP {record_length}")
        
        x_incr = float(self.instrument.query('WFMPRE:XINCR?'))
        x_zero = float(self.instrument.query('WFMPRE:XZERO?'))
        y_mult = float(self.instrument.query('WFMPRE:YMULT?'))
        y_zero = float(self.instrument.query('WFMPRE:YZERO?'))
        y_off = float(self.instrument.query('WFMPRE:YOFF?'))
        
        raw_data = self.instrument.query_binary_values('CURVe?', datatype='h', is_big_endian=True)
        voltage = (np.array(raw_data) - y_off) * y_mult + y_zero
        time_array = np.arange(len(voltage)) * x_incr + x_zero
        
        df = pd.DataFrame()
        df['Time'] = time_array
        df[f'Voltage_CH{ch}'] = voltage
        return df
    
    def get_measurement(self, channel, measurement_type):
        """
        Uses the scope's built-in measurement engine.
        Tektronix TDS6604: MEASUrement:IMMed:SOUrce CH{ch}; TYPe {type}; VALue?
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
        Tektronix TDS6604: EXPort format BMP, read via FILESystem.
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
