"""
This is an outline for what the osc.py file should be like.

A osc (oscilloscope) is defined as an instrument that has the typical features on expects an oscilloscope to have
"""
from ..instrument import Instrument
class Oscilloscope(Instrument):
    # Initializer / Instance attributes
    """
    All oscilloscopes must be able to read some data and give it to the computer
    """
    channel = [1]
    vdiv = (None, None)
    y_range = (None, None)
    y_position = (None, None)
    input_coupling = ["AC", "DC"]
    probe_attenuation = (None, None)
    channel_impedance = ["50"]
    tdiv = (None, None)
    x_range = (None, None)
    x_position = (None, None)
    trigger_source = [1]
    trigger_level = (None, None)
    trigger_slope = ["POS", "NEG", "EITH"]
    trigger_mode = ["EDGE"]
    trigger_sweep = ["AUTO", "NORM"]
    acquisition_mode = ["NORM"]
    acquisition_points = (None, None)

    def quick_read(self):
        """
        All oscilloscopes must be able to read something, so therefore we need a method to read the data. It would be very beneficial to
        ensure that all Measurers have a utility command that quickly reads out the data that is displayed (or the current value etc)
        """

    #These functions make the signal visible and are used on a per channel basis (aka channel dependant)
    def autoscale(self):
        """
        Autoscales the oscilloscope
        """

    def toggle_channel(self, channel, on=True):
        """
        Function that toggles the selected channel to on or off (what to display and what to acquire)
        args:
            channel (int): The channel to toggle
            on (bool): True to turn on, False to turn off
        """

    def set_vertical_scale(self, channel, vdiv, y_range):
        """
        Function that sets the vertical scale in either volts per divison or absolute range
        args:
            channel (int): The channel to set the vertical scale on
            vdiv (float): The volts per division setting
            y_range (float): The absolute range in volts
        """
    
    def set_vertical_position(self, channel, y_position):
        """
        Sets the vertical position of the scale (moves the waveform up and down)
        args:
            channel (int): The channel to set the vertical position on
            y_position (float): The vertical position in volts
        """
    
    def set_input_coupling(self, channel, input_coupling):
        """
        Sets the input coupling, e.g. AC, DC, Ground
        args:
            channel (int): The channel to set the input coupling on
            input_coupling (str): The input coupling type, e.g. 'AC', 'DC', 'GND'
        """
    
    def set_probe_attenuation(self, channel, probe_attenuation):
        """
        Sets the probe attenuation e.g. 1x, 10x etc
        args:
            channel (int): The channel to set the probe attenuation on
            probe_attenuation (int): The probe attenuation factor, e.g. 1 for 1x, 10 for 10x
        """
    
    def set_channel_impedance(self, channel, channel_impedance):
        """
        Sets the channel impedance, e.g. 1MOhm, 50Ohm
        args:
            channel (int): The channel to set the impedance on
            channel_impedance (str): The impedance setting, e.g. '1M', '50'
        """

    #Now we move too setting the time_window which is shared ACROSS channels

    def set_horizontal_scale(self, tdiv, x_range):
        """
        Sets the timebase in either time/division or in absolute range
        args:
            tdiv (float): The time per division setting
            x_range (float): The absolute time range in seconds
        """
    def set_horizontal_position(self, x_position):
        """ 
        Changes the position (delay) of the timebase
        args:
            x_position (float): The horizontal position in seconds
        """

    def configure_horizontal(self, tdiv, x_range, x_position):
        """
        Combines into one function calls set_horizontal_scale and set_horizontal_position
        args:
            tdiv (float): The time per division setting
            x_range (float): The absolute time range in seconds
            x_position (float): The horizontal position in seconds
        """
        

    #Now we can go to triggering

    def set_trigger_source(self, trigger_source):
        """
        Decides what the scope should trigger on
        args:
            trigger_source (str): The trigger source, e.g. 'CH1', 'CH2', 'EXT', 'INT'
        """
    def set_trigger_level(self, trigger_level):
        """
        The voltage level the signal must cross to initiate a capture
        args:
            trigger_level (float): The trigger level in volts
        """
    def set_trigger_slope(self, trigger_slope):
        """
        Changes the trigger from falling, rising etc
        args:
            trigger_slope (str): The trigger slope, e.g. 'rising', 'falling'
        """

    def set_trigger_mode(self, trigger_mode):
        """
        Sets the trigger mode (aka trigger type)
        args:
            trigger_mode (str): The trigger mode, e.g. 'EDGE'
        """

    def set_trigger_sweep(self, trigger_sweep):
        """
        Changes the trigger sweep settings of the oscilloscope
        args:
            trigger_sweep (str): The trigger sweep mode, e.g. 'AUTO', 'NORM'
        """

    def configure_trigger(self, trigger_source, trigger_level, trigger_slope, trigger_mode, trigger_sweep):
        """
        Combines all the trigger commands into one, calls set_trigger_source, set_trigger_level, set_trigger_slope, set_trigger_mode, and set_trigger_sweep
        args:
            trigger_source (str): The trigger source, e.g. 'CH1', 'CH2', 'EXT', 'INT'
            trigger_level (float): The trigger level in volts
            trigger_slope (str): The trigger slope, e.g. 'POS', 'NEG'
            trigger_mode (str): The trigger mode, e.g. 'EDGE'
            trigger_sweep (str): The trigger sweep mode, e.g. 'AUTO', 'NORM'
        """

    def manual_trigger(self):
        """
        Sends a manual force trigger event to the oscilloscope.
        """

    #Time to control acquisition process

    def toggle_acquisition(self, run=True):
        """
        Start or halt the process of capturing data
        args:
            run (bool): True to start acquisition, False to halt it
        """
    def arm(self):
        """
        Tells the scope to get ready to capture the data for the single shot etc
        """

    def set_acquisition(self):
        """
        Sets the oscilloscope to capture the data as set up on the configure_acquisition commands to be ready for a transfer
        """

    def set_acquisition_channel(self, channel):
        """
        Sets the scope to return the selected channel when asked for data
        args:
            channel (int): The desired channel to acquire 
        """

    def set_acquisition_mode(self, acquisition_mode):
        """
        Sets the acusition mode on the scope (e.g. normal, average, peak detect etc)
        args:
            acqusition_mode (str): The desired acquisition mode
        """

    def set_acquisition_points(self, acquisition_points):
        """
        Sets the scope to return the given number of points when asked for data
        args:
            points (int): The number of data points to capture
        """

    def configure_acquisition(self, channel, acquisition_mode, acquisition_points):
        """
        Configures the scope (ideally in binary) to specific parameters such as length (how much data to capture), etc
        args:
            channel (int): The desired channel to acquire
            acquisition_mode (str): The desired acquisition mode (e.g. normal or averaging) 
            acquisition_points (int): The number of data points to capture
        """
    
    #Time to get the data out
    def quick_read(self):
        """
        Quick read function that returns the default data in a numpy array. Typically this should be used to get a snapshot of the current waveform (e.g. the current display).
        
        args:
            None
        Returns:
            data (ndarray): Returns the data in a quick way.
        """

    def get_data(self):
        """
        Returns the data depending on how it was configured with the configure_acquisition command.
        Returns the data in a structured format, typically in a Pandas DataFrame that dispalys the time and voltage values in a structured way across all captured channels.
        args:
            None
        Returns:
            data (Dataframe): Returns the data in a Pandas Dataframe ideally complete with.
        """
    