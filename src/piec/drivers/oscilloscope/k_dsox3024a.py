"""
Driver for the Keysight DSOX3024A oscilloscope.
This class implements the specific functionalities for the DSOX3024A model,
inheriting from generic Oscilloscope and Scpi classes.
"""
import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi

class KeysightDSOX3024a(Oscilloscope, Scpi):
    """
    Specific Class for this exact model of scope: Keysight DSOX3024a. Mostly AI Generated.
    NOTE: Not tested yet
    """

    # Class attributes for parameter restrictions, named after function arguments.
    AUTODETECT_ID = "DSO-X 3024A"  # Identifier string for the instrument

    channel = [1, 2, 3, 4]
    vdiv = (0.001, 5.0)
    y_range = (0.008, 40.0)
    y_position = (-40.0, 40.0)
    input_coupling = ["AC", "DC"]
    probe_attenuation = (0.001, 10000.0)
    channel_impedance = ["50", "1M"]
    tdiv = (0.000000002, 50.0)
    x_range = (0.00000002, 500.0)
    x_position = (-500.0, 500.0)
    trigger_source = [1, 2, 3, 4, "EXT", "LINE", "WGEN"]
    trigger_level = (-6.0, 6.0)
    trigger_slope = ["POS", "NEG", "EITH", "ALT"]
    trigger_mode = ["EDGE"]
    trigger_sweep = ["AUTO", "NORM"]
    acquisition_mode = ["NORM", "AVER", "HRES", "PEAK"]
    acquisition_points = (100, 8000000)

    def autoscale(self):
        """
        Autoscales the oscilloscope
        """
        self.instrument.write(":AUToscale")

    def toggle_channel(self, channel, on=True):
        """
        Function that toggles the selected channel to on or off (what to display and what to acquire)
        args:
            channel (int): The channel to toggle
            on (bool): True to turn on, False to turn off
        """
        self.instrument.write(f":CHANnel{channel}:DISPlay {int(on)}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        """
        Function that sets the vertical scale in either volts per divison or absolute range
        args:
            channel (int): The channel to set the vertical scale on
            vdiv (float): The volts per division setting
            y_range (float): The absolute range in volts
        """
        if vdiv:
            self.instrument.write(f":CHANnel{channel}:SCALe {vdiv}")
        if y_range:
            self.instrument.write(f":CHANnel{channel}:RANGe {y_range}")

    def set_vertical_position(self, channel, y_position):
        """
        Sets the vertical position of the scale (moves the waveform up and down)
        args:
            channel (int): The channel to set the vertical position on
            y_position (float): The vertical position in volts
        """
        self.instrument.write(f":CHANnel{channel}:OFFSet {y_position}")

    def set_input_coupling(self, channel, input_coupling):
        """
        Sets the input coupling, e.g. AC, DC, Ground
        args:
            channel (int): The channel to set the input coupling on
            input_coupling (str): The input coupling type, e.g. 'AC', 'DC', 'GND'
        """
        self.instrument.write(f":CHANnel{channel}:COUPling {input_coupling}")

    def set_probe_attenuation(self, channel, probe_attenuation):
        """
        Sets the probe attenuation e.g. 1x, 10x etc
        args:
            channel (int): The channel to set the probe attenuation on
            probe_attenuation (int): The probe attenuation factor, e.g. 1 for 1x, 10 for 10x
        """
        self.instrument.write(f":CHANnel{channel}:PROBe {probe_attenuation}")
    
    def set_channel_impedance(self, channel, channel_impedance):
        """
        Sets the channel impedance, e.g. 1MOhm, 50Ohm
        args:
            channel (int): The channel to set the impedance on
            channel_impedance (str): The impedance setting, e.g. '1M', '50'
        """
        IMPEDANCE_MAP = {'50': 'FIFT','1M': 'ONEM'}
        self.instrument.write("CHAN{}:IMP {}".format(channel, IMPEDANCE_MAP.get(str(channel_impedance), 'ONEM')))

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        """
        Sets the timebase in either time/division or in absolute range
        args:
            tdiv (float): The time per division setting
            x_range (float): The absolute time range in seconds
        """
        if tdiv:
            self.instrument.write(f":TIMebase:SCALe {tdiv}")
        if x_range:
            self.instrument.write(f":TIMebase:RANGe {x_range}")

    def set_horizontal_position(self, x_position):
        """ 
        Changes the position (delay) of the timebase
        args:
            x_position (float): The horizontal position in seconds
        """
        self.instrument.write(f":TIMebase:POSition {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        """
        Combines into one function calls set_horizontal_scale and set_horizontal_position
        args:
            tdiv (float): The time per division setting
            x_range (float): The absolute time range in seconds
            x_position (float): The horizontal position in seconds
        """
        if tdiv or x_range:
            self.set_horizontal_scale(tdiv=tdiv, x_range=x_range)
        if x_position:
            self.set_horizontal_position(x_position)

    def set_trigger_source(self, trigger_source):
        """
        Decides what the scope should trigger on
        args:
            trigger_source (str or int): The trigger source, e.g. 1, 2, 'EXT', 'INT'
        """
        mapping = {1: 'CHAN1', 2: 'CHAN2', 3: 'CHAN3', 4: 'CHAN4', '1': 'CHAN1', '2': 'CHAN2', '3': 'CHAN3', '4': 'CHAN4'}
        src = mapping.get(trigger_source, trigger_source)
        self.instrument.write(f":TRIGger:EDGE:SOURce {src}")

    def set_trigger_level(self, trigger_level):
        """
        The voltage level the signal must cross to initiate a capture
        args:
            trigger_level (float): The trigger level in volts
        """
        self.instrument.write(f":TRIGger:EDGE:LEVel {trigger_level}")

    def set_trigger_slope(self, trigger_slope):
        """
        Changes the trigger from falling, rising etc
        args:
            trigger_slope (str): The trigger slope, e.g. 'rising', 'falling'
        """
        self.instrument.write(f":TRIGger:EDGE:SLOPe {trigger_slope}")

    def set_trigger_mode(self, trigger_mode):
        """
        Changes the mode from auto, norm, manual, single, etc
        args:
            mode (str): The trigger mode, e.g. 'EDGE"
        """
        self.instrument.write(f":TRIGger:MODE {trigger_mode}")
    
    def set_trigger_sweep(self, trigger_sweep):
        """
        Changes the trigger sweep settings of the oscilloscope
        args:
            trigger_sweep (str): The trigger sweep mode, e.g. 'auto'
        """
        self.instrument.write(f":TRIGger:SWEep {trigger_sweep}")


    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None, trigger_sweep=None):
        """
        Combines all the trigger commands into one, calls set_trigger_source, set_trigger_level, set_trigger_slope, set_trigger_mode, and set_trigger_sweep
        args:
            trigger_source (str): The trigger source, e.g. 'CH1', 'CH2', 'EXT', 'INT'
            trigger_level (float): The trigger level in volts
            trigger_slope (str): The trigger slope, e.g. 'POS', 'NEG'
            trigger_mode (str): The trigger mode, e.g. 'EDGE'
            trigger_sweep (str): The trigger sweep mode, e.g. 'AUTO', 'NORM'
        """
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
        
        # Check the instrument's error using the inherited Scpi command
        error_response = self.error()
        try:
            if int(error_response) != 0:
                print(f"Error during manual trigger (ESR: {error_response.strip()}). Changing trigger sweep to NORM.")
                self.set_trigger_sweep("NORM")
                self.clear() # Clear the error queue
        except ValueError:
            pass

    def toggle_acquisition(self, run=True):
        """
        Start or halt the process of capturing data
        args:
            run (bool): True to start acquisition, False to halt it
        """
        if run:
            self.instrument.write(":RUN")
        else:
            self.instrument.write(":STOP")
            
    def arm(self):
        """
        Tells the scope to get ready to capture the data for the single shot etc
        """
        self.instrument.write(":SINGle")
        self.instrument.write(":WAVeform:UNSigned {}".format("OFF"))

    def set_acquisition(self):
        """
        Sets the oscilloscope to capture the data as set up on the configure_acquisition commands to be ready for a transfer
        """
        self.instrument.write(":DIGitize")

    def set_acquisition_channel(self, channel):
        """
        Sets the scope to return the selected channel when asked for data
        args:
            channel (int): The desired channel to acquire 
        """
        self.instrument.write(f":WAVeform:SOURce CHANnel{channel}")
        
    def set_acquisition_mode(self, acquisition_mode):
        """
        Sets the acusition mode on the scope (e.g. normal, average, peak detect etc)
        args:
            acqusition_mode (str): The desired acquisition mode
        """
        self.instrument.write(f":ACQuire:TYPE {acquisition_mode}")

    def set_acquisition_points(self, acquisition_points):
        """
        Sets the scope to return the given number of points when asked for data
        args:
            points (int): The number of data points to capture
        """
        self.instrument.write(f":WAVeform:POINts {acquisition_points}")

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        """
        Configures the scope (ideally in binary) to specific parameters such as length (how much data to capture), etc
        args:
            channel (int): The desired channel to acquire
            acquisition_mode (str): The desired acquisition mode (e.g. normal or averaging) 
            acquisition_points (int): The number of data points to capture
        """
        if channel:
            self.set_acquisition_channel(channel)
        if acquisition_mode:
            self.set_acquisition_mode(acquisition_mode)
        if acquisition_points:
            self.set_acquisition_points(acquisition_points)

    def quick_read(self):
        """
        Quick read function that returns the default data in a numpy array. Typically this should be used to get a snapshot of the current waveform (e.g. the current display).
        
        args:
            None
        Returns:
            data (ndarray): Returns the data in a quick way.
        """
        self.instrument.write(":WAVeform:FORMat BYTE")
        self.instrument.write(":WAVeform:POINts:MODE NORMal")
        data = self.instrument.query_binary_values(":WAVeform:DATA?", datatype='B')
        return np.array(data)

    def get_data(self):
        """
        Returns the data depending on how it was configured with the configure_acquisition command. Requires set_acquisition to be called first. 
        Returns the data in a structured format, typically in a Pandas DataFrame that dispalys the time and voltage values in a structured way across all captured channels.
        args:
            None
        Returns:
            data (Dataframe): Returns the data in a Pandas Dataframe ideally complete with.
        """
        byte_order = 'msbf'  # Default byte order
        unsigned = 'off'  # Default unsigned setting
        preamble = self.instrument.query(":WAVeform:PREamble?")
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
        if byte_order == 'msbf':
            is_big_endian = True
        if byte_order == 'lsbf':
            is_big_endian = False
        if unsigned == 'off':
            is_unsigned = False
        if unsigned == 'on':
            is_unsigned = True
        else:
            if preamble_dict["format"] == 0 and not is_unsigned:
                data = self.instrument.query_binary_values("WAVeform:DATA?", datatype='b', is_big_endian=is_big_endian)
            if preamble_dict["format"] == 0 and is_unsigned:
                data = self.instrument.query_binary_values("WAVeform:DATA?", datatype='B', is_big_endian=is_big_endian)
            if preamble_dict["format"] == 1 and not is_unsigned:
                data = self.instrument.query_binary_values("WAVeform:DATA?", datatype='h', is_big_endian=is_big_endian)
            if preamble_dict["format"] == 1 and is_unsigned:
                data = self.instrument.query_binary_values("WAVeform:DATA?", datatype='H', is_big_endian=is_big_endian)
            if preamble_dict["format"] == 4:
                data = self.instrument.query_ascii_values("WAVeform:DATA?")
            time = []
            wfm = []
            for t in range(preamble_dict["points"]):
                time.append((t* preamble_dict["x_increment"]) + preamble_dict["x_origin"])
            for d in data:
                wfm.append((d * preamble_dict["y_increment"]) + preamble_dict["y_origin"])
        
        return pd.DataFrame({'Time': time, 'Voltage': wfm})