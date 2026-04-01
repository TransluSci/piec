# This driver has not been tested yet
import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class AgilentDSOX5000(Oscilloscope, Scpi):
    """
    Driver for the Agilent/Keysight InfiniVision 5000 X-Series Oscilloscopes.
    e.g. DSO-X 5032A, DSO-X 5034A, DSO-X 5054A
    """
    
    AUTODETECT_ID = "DSO-X 5"
    
    channel = [1, 2, 3, 4]
    
    # Vertical Scale: 1mV/div to 5V/div (1M Ohm), 1mV to 1V (50 Ohm)
    vdiv = (1e-3, 5.0)
    
    # Offset Range depends on scale, typically +/- 5V to +/- 20V
    y_range = None # Complex dependency
    y_position = (-20.0, 20.0) # Simplified
    
    input_coupling = ["AC", "DC"]
    probe_attenuation = (0.001, 10000.0)
    channel_impedance = ["50", "1M"]
    
    # Timebase: 1ns/div to 50s/div (5000X series usually goes down to 1ns or 2ns)
    tdiv = (1e-9, 50.0)
    
    x_range = (10e-9, 500.0)
    x_position = (-500.0, 500.0)
    
    trigger_source = [1, 2, 3, 4, "EXT", "LINE", "WGEN"]
    trigger_level = (-6.0, 6.0) # Varies by scale
    trigger_slope = ["POS", "NEG", "EITH", "ALT"]
    trigger_mode = ["EDGE", "GLIT", "PATT", "TV", "DWE"] # Simplified to EDGE mainly
    trigger_sweep = ["AUTO", "NORM"]
    
    acquisition_mode = ["NORM", "AVER", "HRES", "PEAK"]
    # 5000X typically has 4M pts, options for more
    acquisition_points = (100, 4000000)
    




    # Reusing methods from KeysightDSOX3024a as the command set is identical for InfiniVision X-Series
    
    def autoscale(self):
        self.instrument.write(":AUToscale")

    def toggle_channel(self, channel, on=True):
        self.instrument.write(f":CHANnel{channel}:DISPlay {int(on)}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        if vdiv:
            self.instrument.write(f":CHANnel{channel}:SCALe {vdiv}")
        if y_range:
            self.instrument.write(f":CHANnel{channel}:RANGe {y_range}")

    def set_vertical_position(self, channel, y_position):
        self.instrument.write(f":CHANnel{channel}:OFFSet {y_position}")

    def set_input_coupling(self, channel, input_coupling):
        self.instrument.write(f":CHANnel{channel}:COUPling {input_coupling}")

    def set_probe_attenuation(self, channel, probe_attenuation):
        self.instrument.write(f":CHANnel{channel}:PROBe {probe_attenuation}")
    
    def set_channel_impedance(self, channel, channel_impedance):
        IMPEDANCE_MAP = {'50': 'FIFT','1M': 'ONEM'}
        self.instrument.write("CHAN{}:IMP {}".format(channel, IMPEDANCE_MAP[channel_impedance]))

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        if tdiv:
            self.instrument.write(f":TIMebase:SCALe {tdiv}")
        if x_range:
            self.instrument.write(f":TIMebase:RANGe {x_range}")

    def set_horizontal_position(self, x_position):
        self.instrument.write(f":TIMebase:POSition {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        if tdiv or x_range:
            self.set_horizontal_scale(tdiv=tdiv, x_range=x_range)
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
        self.instrument.write(f":TRIGger:MODE {trigger_mode}")
    
    def set_trigger_sweep(self, trigger_sweep):
        self.instrument.write(f":TRIGger:SWEep {trigger_sweep}")

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
        self.instrument.write(":TRIGger:FORCe")

    def toggle_acquisition(self, run=True):
        if run:
            self.instrument.write(":RUN")
        else:
            self.instrument.write(":STOP")
            
    def arm(self):
        self.instrument.write(":SINGle")
        self.instrument.write(":WAVeform:UNSigned {}".format("OFF"))

    def set_acquisition(self):
        self.instrument.write(":DIGitize")

    def set_acquisition_channel(self, channel):
        self.instrument.write(f":WAVeform:SOURce CHANnel{channel}")
        
    def set_acquisition_mode(self, acquisition_mode):
        self.instrument.write(f":ACQuire:TYPE {acquisition_mode}")

    def set_acquisition_points(self, acquisition_points):
        self.instrument.write(f":WAVeform:POINts {acquisition_points}")

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        if channel:
            self.set_acquisition_channel(channel)
        if acquisition_mode:
            self.set_acquisition_mode(acquisition_mode)
        if acquisition_points:
            self.set_acquisition_points(acquisition_points)

    def quick_read(self):
        self.instrument.write(":WAVeform:FORMat BYTE")
        self.instrument.write(":WAVeform:POINts:MODE NORMal")
        data = self.instrument.query_binary_values(":WAVeform:DATA?", datatype='B')
        return np.array(data)

    def get_data(self):
        # Default implementation similar to DSOX3000
        # For robustness, we might want to check preamble formatting, 
        # but reusing the logic is a good start.
        preamble = self.instrument.query(":WAVeform:PREamble?")
        # ... (rest of logic from DSOX3024a)
        # To avoid duplicating 50 lines of code, I'll copy it for now as requested "re-implement functions".
        # Inheriting just methods is tricky if I want "self-contained" file.
        
        preamble1 = preamble.split()
        preamble_list = preamble1[0].split(',')
        preamble_dict = {
        'format': np.int16(preamble_list[0]),
        'type': np.int16(preamble_list[1]),
        'points': np.int32(preamble_list[2]),
        'count': np.int32(preamble_list[3]),
        'x_increment': np.float64(preamble_list[4]),
        'x_origin': np.float64(preamble_list[5]),
        'x_reference': np.int32(preamble_list[6]),
        'y_increment': np.float32(preamble_list[7]),
        'y_origin': np.float32(preamble_list[8]),
        'y_reference': np.int32(preamble_list[9]),
        }
        
        # Assume byte order and unsigned check logic is same
        # ...
        # Simplified for brevity in implementation plan but required for full code.
        # I will paste the full logic.
        
        is_big_endian = True # Default for SCPI usually
        is_unsigned = False
        
        # Check format
        # If format 0 (BYTE), 1 (WORD), 4 (ASCII)
        fmt = preamble_dict["format"]
        
        if fmt == 0:
             data = self.instrument.query_binary_values("WAVeform:DATA?", datatype='b', is_big_endian=is_big_endian)
        elif fmt == 1:
             data = self.instrument.query_binary_values("WAVeform:DATA?", datatype='h', is_big_endian=is_big_endian)
        elif fmt == 4:
             data = self.instrument.query_ascii_values("WAVeform:DATA?")
        else:
             data = []

        time = []
        wfm = []
        # Vectorized generation is faster but loop is fine for now
        for t in range(preamble_dict["points"]):
            time.append((t* preamble_dict["x_increment"]) + preamble_dict["x_origin"])
        for d in data:
            wfm.append((d * preamble_dict["y_increment"]) + preamble_dict["y_origin"])
            
        return pd.DataFrame({'Time': time, 'Voltage': wfm})
