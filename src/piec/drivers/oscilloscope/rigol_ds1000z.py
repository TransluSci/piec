# This driver has not been tested yet
import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class RigolDS1000Z(Oscilloscope, Scpi):
    """
    Driver for the Rigol DS1000Z Series Oscilloscopes.
    e.g. DS1054Z, DS1074Z, DS1104Z
    """
    
    # "RIGOL TECHNOLOGIES,DS1054Z,..."
    AUTODETECT_ID = "DS1"
    
    channel = [1, 2, 3, 4]
    
    # Vertical Scale: 1mV/div to 10V/div
    vdiv = (1e-3, 10.0)
    
    y_range = None
    y_position = (-100.0, 100.0) # Varies by scale
    
    input_coupling = ["AC", "DC", "GND"]
    probe_attenuation = (0.01, 1000.0)
    channel_impedance = ["1M"] # DS1000Z is 1M only usually
    
    # Timebase: 5ns/div to 50s/div
    tdiv = (5e-9, 50.0)
    
    x_range = None
    x_position = (-500.0, 500.0)
    
    trigger_source = [1, 2, 3, 4, "EXT", "LINE", "AC"]
    trigger_level = (-100.0, 100.0)
    trigger_slope = ["POS", "NEG", "RFAL"]
    trigger_mode = ["AUTO", "NORM", "SING"]
    trigger_sweep = ["AUTO", "NORM", "SING"]
    
    acquisition_mode = ["NORM", "AVER", "PEAK", "HRES"]
    acquisition_points = (100, 24000000) # Up to 24M optional
    




    def autoscale(self):
        self.instrument.write(":AUToscale")

    def toggle_channel(self, channel, on=True):
        self.instrument.write(f":CHANnel{channel}:DISPlay {int(on)}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        if vdiv:
            self.instrument.write(f":CHANnel{channel}:SCALe {vdiv}")

    def set_vertical_position(self, channel, y_position):
        self.instrument.write(f":CHANnel{channel}:OFFSet {y_position}")

    def set_input_coupling(self, channel, input_coupling):
        self.instrument.write(f":CHANnel{channel}:COUPling {input_coupling}")

    def set_probe_attenuation(self, channel, probe_attenuation):
        self.instrument.write(f":CHANnel{channel}:PROBe {probe_attenuation}")
    
    def set_channel_impedance(self, channel, channel_impedance):
        pass # Only 1M usually

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        if tdiv:
            self.instrument.write(f":TIMebase:SCALe {tdiv}")

    def set_horizontal_position(self, x_position):
        self.instrument.write(f":TIMebase:POSition {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        if tdiv:
            self.set_horizontal_scale(tdiv=tdiv)
        if x_position:
            self.set_horizontal_position(x_position)

    def set_trigger_source(self, trigger_source):
        mapping = {1: 'CHAN1', 2: 'CHAN2', 3: 'CHAN3', 4: 'CHAN4', '1': 'CHAN1', '2': 'CHAN2', '3': 'CHAN3', '4': 'CHAN4'}
        src = mapping.get(trigger_source, trigger_source)
        self.instrument.write(f":TRIGger:EDGE:SOURce {src}")

    def set_trigger_level(self, trigger_level):
        self.instrument.write(f":TRIGger:EDGE:LEVel {trigger_level}")

    def set_trigger_slope(self, trigger_slope):
        self.instrument.write(f":TRIGger:EDGE:SLOPe {trigger_slope}")

    def set_trigger_mode(self, trigger_mode):
        pass # Rigol puts sweep in sweep command usually
    
    def set_trigger_sweep(self, trigger_sweep):
        self.instrument.write(f":TRIGger:SWEep {trigger_sweep}")

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None):
        if trigger_source:
            self.set_trigger_source(trigger_source)
        if trigger_level:
            self.set_trigger_level(trigger_level)
        if trigger_slope:
            self.set_trigger_slope(trigger_slope)
        if trigger_mode:
            self.set_trigger_sweep(trigger_mode) # Rigol uses sweep for mode

    def manual_trigger(self):
        """Sends a manual force trigger event to the oscilloscope."""
        self.instrument.write(":TFORce")

    def toggle_acquisition(self, run=True):
        if run:
            self.instrument.write(":RUN")
        else:
            self.instrument.write(":STOP")
            
    def arm(self):
        self.instrument.write(":SINGle")

    def set_acquisition(self):
        pass # Standard run/stop

    def set_acquisition_channel(self, channel):
        self.instrument.write(f":WAVeform:SOURce CHANnel{channel}")
        
    def set_acquisition_mode(self, acquisition_mode):
        self.instrument.write(f":ACQuire:TYPE {acquisition_mode}")

    def set_acquisition_points(self, acquisition_points):
        # Sets MEM DEPTH
        # Modes: AUTO, 12k, 120k, 1.2M, 12M, 24M
        # Map roughly
        if acquisition_points == "AUTO":
             self.instrument.write(":ACQuire:MDEPth AUTO")
        else:
             self.instrument.write(f":ACQuire:MDEPth {int(acquisition_points)}")

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        if channel:
             self.set_acquisition_channel(channel)
        if acquisition_mode:
            self.set_acquisition_mode(acquisition_mode)

    def quick_read(self):
        self.instrument.write(":WAVeform:FORMat BYTE")
        self.instrument.write(":WAVeform:MODE NORMal")
        data = self.instrument.query_binary_values(":WAVeform:DATA?", datatype='B')
        return np.array(data)

    def get_data(self):
        self.instrument.write(":WAVeform:FORMat BYTE")
        self.instrument.write(":WAVeform:MODE NORMal")
        
        preamble = self.instrument.query(":WAVeform:PREamble?")
        # Format: <format>,<type>,<points>,<count>,<xinc>,<xorig>,<xref>,<yinc>,<yorig>,<yref>
        pre = preamble.split(',')
        
        # Rigol DS1000Z indices:
        # 0: format (0=BYTE, 1=WORD, 2=ASC)
        # 2: points
        # 4: xinc
        # 5: xorig
        # 6: xref
        # 7: yinc
        # 8: yorig
        # 9: yref
        
        points = int(pre[2])
        xinc = float(pre[4])
        xorig = float(pre[5])
        xref = float(pre[6])
        yinc = float(pre[7])
        yorig = float(pre[8])
        yref = float(pre[9])
        
        raw_data = self.instrument.query_binary_values(":WAVeform:DATA?", datatype='B', is_big_endian=False) # Rigol is usually little endian? check manual. Usually IEE block.
        
        # Manual says: TMC Blockheader...
        # If query_binary_values handles header, we are good.
        
        # Convert
        data_volts = [(val - yref) * yinc + yorig for val in raw_data]
        data_time = [i * xinc + xorig for i in range(len(raw_data))]
        
        return pd.DataFrame({'Time': data_time, 'Voltage': data_volts})
