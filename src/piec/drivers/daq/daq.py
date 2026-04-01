"""
This is an outline for what the daq.py file should be like.

A daq (Data Acqusition System) is defined as an instrument that has the typical features one expects a daq to have
"""
from ..instrument import Instrument 
class Daq(Instrument):
    # Initializer / Instance attributes
    """
    All daqs must be able to acquire data and output signals. Need a way to get the list of analog and digital IO
    """
    #Core Information Functions
    """
    We should have some hardcoded information about the daq, such as the number of analog and digital channels, the sample rate, etc.
    """
    #analog input functions
    def set_AI_channel(self, channel):
        """
        Sets the Analog input channel for data acquisition
        """
    def set_AI_range(self, channel, range):
        """
        Sets the range for the Analog input channel
        """
    def set_AI_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Analog input channel
        """
    def configure_AI_channel(self, channel, range, sample_rate):
        """
        Calls the set_AI_channel, set_AI_range, and set_AI_sample_rate functions to configure the Analog input channel
        """
    
    #analog output functions
    def set_AO_channel(self, channel):
        """
        Sets the Analog output channel for data output
        """
    def set_AO_range(self, channel, range):
        """
        Sets the range for the Analog output channel
        """
    def set_AO_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Analog output channel
        """
    def configure_AO_channel(self, channel, range, sample_rate):
        """
        Calls the set_AO_channel, set_AO_range, and set_AO_sample_rate functions to configure the Analog output channel
        """
    def write_AO(self, channel, data):
        """
        Writes data to the Analog Output channel.
        args:
            channel (int): The channel to write to
            data (list or ndarray): The data to write
        """
    #NOTE: Issue with digital IO is that some are only input and some only output but most can be both.
    #digital input_only functions
    def set_DI_channel(self, channel):
        """
        Sets the Digital input channel for data acquisition
        """
    def set_DI_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Digital input channel
        """
    def configure_DI_channel(self, channel, sample_rate):
        """
        Calls the set_DI_channel and set_DI_sample_rate functions to configure the Digital input channel
        """
    #digital output_only functions
    def set_DO_channel(self, channel):
        """
        Sets the Digital output channel for data output
        """
    def set_DO_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Digital output channel
        """
    def configure_DO_channel(self, channel, sample_rate):
        """
        Calls the set_DO_channel and set_DO_sample_rate functions to configure the Digital output channel
        """
    def write_DO(self, channel, data):
        """
        Writes data to the Digital Output channel.
        args:
            channel (int): The channel to write to
            data (list or ndarray): The data to write
        """
    #digital input/output functions
    def set_DIO_channel(self, channel):
        """
        Sets the Digital input/output channel for data acquisition or output
        """
    def set_DIO_mode(self, channel, mode):
        """
        Sets the mode for the Digital input/output channel (input or output)
        """
    def set_DIO_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Digital input/output channel
        """
    def configure_DIO_channel(self, channel, mode, sample_rate):
        """
        Calls the set_DIO_channel, set_DIO_mode, and set_DIO_sample_rate functions to configure the Digital input/output channel
        """
    #data acquisition functions
    def quick_read(self):
        """
        Quick read function that returns the default data (off of whatever is the default channel typically 0 or 1) (e.g., analog input data)
        """
    def read_data(self, channel):
        """
        Reads the data from the specified channel (e.g., analog input, digital input, etc.)
        Logic may be needed to determine the type of channel and read accordingly
        """
    def read_AI(self, channel):
        """
        Reads the Analog input data from the specified channel
        """
    def read_AI_scan(self, channel, points, rate):
        """
        Reads a stream of Analog input data (hardware paced).
        args:
            channel (int): The channel to read from.
            points (int): Number of points to acquire.
            rate (float): Sample rate in Hz.
        returns:
            list/array: The acquired voltage data.
        """
    def read_DI(self, channel):
        """
        Reads the Digital input data from the specified channel
        """
    #ouput functions
    def output(self, channel, on=True):
        """
        Turns the output on or off for the specified channel (e.g., Analog output, Digital output
        may require logic to determine the type of channel and output accordingly).
        
        NOTE: For many DAQs, writing data starts the generation. This function can be used as an
        enable/disable switch if the hardware supports explicitly arming/disarming the output.
        """
    
    