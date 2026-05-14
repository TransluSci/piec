"""
Virtual DAQ class that mimics a generic MCC-style DAQ for testing and simulation.
This module provides a software simulation of a DAQ device for development
and testing without physical hardware.
"""
import numpy as np

from .daq import Daq
from ..virtual_instrument import VirtualInstrument


class VirtualDaq(VirtualInstrument, Daq):
    """
    Virtual version of a DAQ device for simulation/testing.
    Stores state internally and generates synthetic data.

    Mimics a device with:
    - 8 Single-Ended / 4 Differential Analog Inputs (+/- 10V, 16-bit)
    - 2 Analog Outputs (+/- 10V)
    - 8 Digital I/O (bit-configurable)
    """

    # --- Class Attributes ---
    ai_channel = [0, 1, 2, 3, 4, 5, 6, 7]
    ao_channel = [0, 1]
    dio_channel = [0, 1, 2, 3, 4, 5, 6, 7]
    ai_range = [(-10.0, 10.0)]
    ao_range = [(-10.0, 10.0)]
    ai_mode = ['SE', 'DIFF']
    ai_sample_rate = (1.0, 100000.0)
    ao_sample_rate = (1.0, 100000.0)
    dio_direction = ['I', 'O']

    def __init__(self, address='VIRTUAL', **kwargs):
        """
        Initialize virtual DAQ with default settings.

        Args:
            address (str): Virtual address (default: 'VIRTUAL').
            **kwargs: Additional arguments passed to parent classes.
        """
        VirtualInstrument.__init__(self, address=address)
        Daq.__init__(self, address=address, **kwargs)

        self.state = {
            'ai_mode': 'SE',
            'ai_values': {ch: 0.0 for ch in self.ai_channel},
            'ao_values': {ch: 0.0 for ch in self.ao_channel},
            'dio_direction': {ch: 'I' for ch in self.dio_channel},
            'dio_values': {ch: 0 for ch in self.dio_channel},
        }

    # --- SCPI-Equivalent Commands ---

    def idn(self):
        """
        Returns the identification string for the virtual DAQ.

        Returns:
            str: Virtual DAQ identification string.
        """
        return "PIEC,Virtual_DAQ,s/n_virtual,ver1.0"

    def reset(self):
        """
        Resets the virtual DAQ to its default state.
        """
        self.__init__()

    def clear(self):
        """
        Clears status (no-op in virtual mode).
        """
        return None

    def error(self):
        """
        Returns the error status (always clean in virtual mode).

        Returns:
            str: Error message.
        """
        return "No errors."

    def wait(self):
        """
        Waits for pending operations (instant in virtual mode).
        """
        return None

    def self_test(self):
        """
        Runs self-test (always passes in virtual mode).

        Returns:
            str: ``'0'`` for pass.
        """
        return "0"

    def operation_complete(self):
        """
        Checks operation completion (always complete in virtual mode).

        Returns:
            str: ``'1'`` (complete).
        """
        return "1"

    def close(self):
        """
        Releases virtual DAQ resources (no-op).
        """
        pass

    def initialize(self):
        """
        Initialises the virtual DAQ to a known state.
        """
        self.reset()

    # --- Analog Input Methods ---

    def set_AI_channel(self, channel):
        """
        Sets the Analog Input channel for data acquisition.
        """
        pass  # State tracked by auto_check_params

    def set_AI_range(self, channel, range):
        """
        Sets the range for the Analog Input channel.
        """
        pass  # Virtual DAQ has fixed +/- 10V range

    def set_AI_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Analog Input channel.
        """
        pass  # Accepted but no hardware to configure

    def configure_AI_channel(self, channel, range=None, sample_rate=None):
        """
        Configures the Analog Input channel.
        """
        if range is not None:
            self.set_AI_range(channel, range)
        if sample_rate is not None:
            self.set_AI_sample_rate(channel, sample_rate)

    def set_input_mode(self, ai_mode):
        """
        Switches between Single-Ended and Differential input modes.

        args:
            ai_mode (str): 'SE' (Single-Ended, 8 channels) or
                           'DIFF' (Differential, 4 channels).
        """
        mode_str = str(ai_mode).upper()
        self.state['ai_mode'] = mode_str

        if 'DIFF' in mode_str:
            self.ai_channel = [0, 1, 2, 3]
        else:
            self.ai_channel = [0, 1, 2, 3, 4, 5, 6, 7]

    # --- Analog Output Methods ---

    def set_AO_channel(self, channel):
        """
        Sets the Analog Output channel.
        """
        pass

    def set_AO_range(self, channel, range):
        """
        Sets the range for the Analog Output channel.
        """
        pass  # Fixed +/- 10V

    def set_AO_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Analog Output channel.
        """
        pass

    def configure_AO_channel(self, channel, range=None, sample_rate=None):
        """
        Configures the Analog Output channel.
        """
        if range is not None:
            self.set_AO_range(channel, range)
        if sample_rate is not None:
            self.set_AO_sample_rate(channel, sample_rate)

    def write_AO(self, channel, data):
        """
        Writes data to the Analog Output channel.

        args:
            channel (int): The channel to write to (0-1).
            data (float or list): The voltage(s) to output.
        """
        if isinstance(data, (int, float)):
            self.state['ao_values'][channel] = float(data)
        elif len(data) > 0:
            self.state['ao_values'][channel] = float(data[-1])

    # --- Digital I/O Methods ---

    def set_DI_channel(self, channel):
        """
        Sets the Digital Input channel.
        """
        pass

    def set_DI_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Digital Input channel.
        """
        pass

    def configure_DI_channel(self, channel, sample_rate=None):
        """
        Configures the Digital Input channel.
        """
        if sample_rate is not None:
            self.set_DI_sample_rate(channel, sample_rate)

    def set_DO_channel(self, channel):
        """
        Sets the Digital Output channel.
        """
        pass

    def set_DO_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Digital Output channel.
        """
        pass

    def configure_DO_channel(self, channel, sample_rate=None):
        """
        Configures the Digital Output channel.
        """
        if sample_rate is not None:
            self.set_DO_sample_rate(channel, sample_rate)

    def write_DO(self, channel, data):
        """
        Writes data to the Digital Output channel.

        args:
            channel (int): The channel to write to.
            data (int/bool or list): 1/True for High, 0/False for Low.
        """
        if isinstance(data, (int, bool)):
            self.state['dio_values'][channel] = 1 if data else 0
        elif len(data) > 0:
            self.state['dio_values'][channel] = 1 if data[-1] else 0

    def set_DIO_channel(self, channel):
        """
        Sets the Digital I/O channel.
        """
        pass

    def set_DIO_mode(self, channel, mode):
        """
        Sets the direction for the Digital I/O channel.
        """
        self.state['dio_direction'][channel] = mode

    def set_DIO_sample_rate(self, channel, sample_rate):
        """
        Sets the sample rate for the Digital I/O channel.
        """
        pass

    def configure_DIO_channel(self, channel, mode=None, sample_rate=None):
        """
        Configures the Digital I/O channel.
        """
        if mode is not None:
            self.set_DIO_mode(channel, mode)
        if sample_rate is not None:
            self.set_DIO_sample_rate(channel, sample_rate)

    def set_dio_direction(self, dio_channel, dio_direction):
        """
        Configures a digital pin as Input or Output.

        args:
            dio_channel (int): The channel to configure.
            dio_direction (str): 'I' for Input, 'O' for Output.
        """
        self.state['dio_direction'][dio_channel] = dio_direction

    # --- Data Acquisition Methods ---

    def quick_read(self):
        """
        Returns a simulated single-point voltage reading from channel 0.

        Returns:
            float: Simulated voltage (0.0V).
        """
        return 0.0

    def read_data(self, channel):
        """
        Reads data from the specified channel.

        Returns:
            float or int: Simulated value (0.0 for AI, 0 for DI).
        """
        if channel in self.state['ai_values']:
            return self.state['ai_values'][channel]
        return 0

    def read_AI(self, channel):
        """
        Reads a simulated voltage from the specified Analog Input channel.

        args:
            channel (int): The channel to read from.
        returns:
            float: Simulated voltage (0.0V).
        """
        return self.state['ai_values'].get(channel, 0.0)

    def read_AI_scan(self, channel, points, rate):
        """
        Reads a simulated stream of Analog Input data (hardware-paced).

        Generates a 10 Hz sine wave for testing.

        args:
            channel (int): The channel to read from.
            points (int): Number of points to acquire.
            rate (float): Sample rate in Hz.
        returns:
            list: Simulated voltage data.
        """
        t = np.linspace(0, points / rate, points)
        return (np.sin(2 * np.pi * 10 * t)).tolist()

    def read_DI(self, channel):
        """
        Reads the state of a simulated digital input channel.

        args:
            channel (int): The channel to read.
        returns:
            int: Simulated value (0).
        """
        return self.state['dio_values'].get(channel, 0)

    def output(self, channel, on=True):
        """
        Enables or disables output on a channel (no-op in virtual mode).

        args:
            channel (int): The channel.
            on (bool): True to enable, False to disable.
        """
        pass
