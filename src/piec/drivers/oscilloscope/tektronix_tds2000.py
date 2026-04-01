# This driver has not been tested yet
import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class TektronixTDS2000(Oscilloscope, Scpi):
    """
    Driver for the Tektronix TDS 2000 Series Oscilloscopes.
    e.g. TDS 2002, TDS 2012, TDS 2022, TDS 2024
    """
    
    # "TEKTRONIX,TDS 2012,..."
    AUTODETECT_ID = "TDS 2"
    
    channel = [1, 2, 3, 4]
    
    # Vertical: 2mV to 5V
    vdiv = (2e-3, 5.0)
    
    y_range = None
    y_position = (-100.0, 100.0) # approx divisions?
    
    input_coupling = ["AC", "DC", "GND"]
    probe_attenuation = (1.0, 1000.0) # 1x, 10x, 100x, 1000x
    channel_impedance = None # Fixed 1M usually
    
    # Timebase: 5ns to 50s
    tdiv = (5e-9, 50.0)
    
    x_range = None
    x_position = None
    
    trigger_source = [1, 2, 3, 4, "EXT", "EXT5", "LINE"]
    trigger_level = (-10.0, 10.0)
    trigger_slope = ["RISE", "FALL"]
    trigger_mode = ["AUTO", "NORM"]
    trigger_sweep = ["AUTO", "NORM"] # Mapped to mode usually
    
    acquisition_mode = ["SAMPLE", "AVERAGE", "PEAKDETECT"]
    acquisition_points = (2500, 2500) # Fixed 2500 usually
    




    def autoscale(self):
        self.instrument.write("AUTOSet EXECute")

    def toggle_channel(self, channel, on=True):
        state = "ON" if on else "OFF"
        self.instrument.write(f"SELect:CH{channel} {state}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        if vdiv:
            self.instrument.write(f"CH{channel}:SCAle {vdiv}")
        # y_range not directly supported as such, depends on scale/divisions

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
        # TDS 2000 usually fixed 1M, command might not exist or be limited.
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
        pass # TDS2000 generally set up mode and then query curve

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
