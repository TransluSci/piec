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

    # --- Class Attributes (Capabilities & Limits) ---
    # Child drivers MUST override these with their specific hardware values.
    # See DRIVER_DEVELOPMENT_GUIDE.md Section 4 for formatting rules.

    # Analog Input
    ai_channel = [0]                    # List of valid analog input channel indices
    ai_range = (None, None)             # (min_V, max_V) or list of supported (min, max) tuples
    ai_mode = None                      # e.g. ['SE', 'DIFF'] if hardware supports mode switching
    ai_sample_rate = (None, None)       # (min_Hz, max_Hz) for hardware-paced acquisition

    # Analog Output
    ao_channel = [0]                    # List of valid analog output channel indices
    ao_range = (None, None)             # (min_V, max_V) or list of supported (min, max) tuples
    ao_sample_rate = (None, None)       # (min_Hz, max_Hz) for hardware-paced output

    # Digital I/O
    dio_channel = [0]                   # List of valid digital I/O channel indices
    dio_direction = ['I', 'O']          # Supported directions: Input, Output

    # --- Default Convenience Command Skeletons ---
    # These provide the standard instrument management interface.
    # The method names mirror the SCPI class for consistency across all
    # instrument types.  MCC/Digilent-based DAQs will inherit real
    # implementations from Digilent.  DAQs using other protocols
    # (NI-DAQmx, proprietary serial, etc.) should override these with
    # their own native commands.

    def idn(self):
        """
        Returns the identification string of the DAQ device.

        For MCC/Digilent devices this queries the Universal Library board name.
        Other DAQ platforms should override this to return an equivalent
        identification string from their native SDK or protocol.

        Returns:
            str: Device identification string.
        """

    def reset(self):
        """
        Resets the DAQ device to its default / power-on state.

        For MCC/Digilent devices there is no single ``*RST``-style command;
        implementations should release and re-acquire the board, or call the
        platform-specific reset routine.  Other DAQ platforms should override
        this with their own reset mechanism.
        """

    def clear(self):
        """
        Clears the device's error / status state.

        For MCC/Digilent devices this is a no-op since the Universal Library
        does not maintain a persistent status register.  Other DAQ platforms
        should override this if they have a clearable status queue.
        """

    def error(self):
        """
        Queries the device's most recent error status or message.

        For MCC/Digilent devices this calls the Universal Library error
        message retrieval.  Other DAQ platforms should override this to
        return error information from their native SDK.

        Returns:
            str: The error message or status string.
        """

    def wait(self):
        """
        Blocks until all pending device operations have completed.

        For MCC/Digilent devices this polls the scan status until idle.
        Other DAQ platforms should override this with their own
        synchronisation mechanism.
        """

    def self_test(self):
        """
        Runs the device's built-in self-test routine, if available.

        Not all DAQ hardware supports self-test.  Implementations should
        handle extended timeouts appropriately.

        Returns:
            str: Self-test result (typically ``'0'`` for pass).
        """

    def operation_complete(self):
        """
        Queries whether the last operation has finished.

        For MCC/Digilent devices this checks the background scan status.
        Other DAQ platforms should override this with their native
        polling / synchronisation command.

        Returns:
            str: ``'1'`` when the operation is complete.
        """

    def close(self):
        """
        Releases the DAQ device and frees any associated resources.

        For MCC/Digilent devices this releases the board from the Universal
        Library.  Other DAQ platforms should override this with their own
        cleanup / disconnection routine.
        """

    def initialize(self):
        """
        Convenience method that resets the DAQ and clears any pending errors
        to bring it to a known good starting state.

        The default implementation calls :meth:`reset` followed by
        :meth:`clear`.  Override if additional initialisation steps are
        needed for a specific platform.
        """
        self.reset()
        self.clear()

    # --- DAQ-Specific Methods ---

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
    
    