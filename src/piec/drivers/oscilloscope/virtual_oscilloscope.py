"""
Virtual Oscilloscope class that mimics the Keysight DSOX3024a interface for testing and simulation purposes.
This module provides a software simulation of an oscilloscope for development and testing without physical hardware.
"""
import numpy as np
import pandas as pd

from .oscilloscope import Oscilloscope
from ..scpi import Scpi
from ..virtual_instrument import VirtualInstrument

class VirtualScope(VirtualInstrument, Oscilloscope, Scpi):
    """
    Virtual version of the KeysightDSOX3024a oscilloscope for simulation/testing.
    Stores state internally and generates synthetic data.

    Attributes:
        channel (list): Available channels [1-4]
        vdiv (tuple): Vertical division range (min, max) in volts
        y_range (tuple): Vertical range (min, max) in divisions
        y_position (tuple): Vertical position range (min, max)
        input_coupling (list): Available coupling modes ["AC", "DC"]
        probe_attenuation (tuple): Probe attenuation range (min, max)
        tdiv (tuple): Time division range (min, max) in seconds
        x_range (tuple): Horizontal range (min, max) in seconds
        x_position (tuple): Horizontal position range (min, max)
        trigger_source (list): Available trigger sources
        trigger_level (tuple): Trigger level range (min, max) in volts
        trigger_slope (list): Available trigger slope modes
        trigger_mode (list): Available trigger modes
        trigger_sweep (list): Available trigger sweep modes
        acquisition_mode (list): Available acquisition modes
        acquisition_points (tuple): Number of points range (min, max)
    """

    channel = [1, 2, 3, 4]
    vdiv = (0.001, 5.0)
    y_range = (0.008, 40.0)
    y_position = (-40.0, 40.0)
    input_coupling = ["AC", "DC"]
    probe_attenuation = (0.001, 10000.0)
    tdiv = (0.000000002, 50.0)
    x_range = (0.00000002, 500.0)
    x_position = (-500.0, 500.0)
    trigger_source = [1, 2, 3, 4, "EXT", "LINE", "WGEN"]
    trigger_level = (-6.0, 6.0)
    trigger_slope = ["POS", "NEG", "EITH", "ALT"]
    trigger_mode = ["EDGE"]
    trigger_sweep = ["AUTO", "NORM"]
    acquisition_mode = ["NORM", "AVER", "HRES", "PEAK"]
    acquisition_points = (100, 1000)

    def __init__(self, address='abc'):
        """
        Initialize virtual oscilloscope with default settings.

        Args:
            address (str): Virtual address for the instrument (default: 'abc')
        """
        VirtualInstrument.__init__(self, address=address)

        # In virtual mode, treat the instrument as self so SCPI helpers can call write/query safely
        self.instrument = self

        self.state = {
            'channels_on': {ch: True for ch in self.channel},
            'vdiv': {ch: 1.0 for ch in self.channel},
            'y_range': {ch: 8.0 for ch in self.channel},
            'y_position': {ch: 0.0 for ch in self.channel},
            'input_coupling': {ch: 'DC' for ch in self.channel},
            'probe_attenuation': {ch: 1.0 for ch in self.channel},
            'tdiv': 1e-3,
            'x_range': 8e-3,
            'x_position': 0.0,
            'trigger_source': 'CHAN1',
            'trigger_level': 0.0,
            'trigger_slope': 'POS',
            'trigger_mode': 'EDGE',
            'trigger_sweep': 'AUTO',
            'acquisition_mode': 'NORM',
            'acquisition_channel': 1,
            'running': False,
            'armed': False
        }

    def idn(self):
        """
        Get the identification string of the virtual oscilloscope.
        
        Returns:
            str: Identification string for the virtual oscilloscope
        """
        return "Virtual Oscilloscope"
    
    # --- Minimal SCPI surface for virtual mode ---
    def write(self, command):
        """Accept SCPI-like write commands (no-op for virtual scope)."""
        # For future: handle commands like *RST/*CLS if needed
        return None

    def query(self, command):
        """Respond to common SCPI queries used by base helpers."""
        if command == "*IDN?":
            return self.idn()
        if command == "*ESR?":
            return "0"
        if command == "*OPC?":
            return "1"
        return ""

    def reset(self):
        """Reset the virtual scope to defaults (equivalent to autoscale)."""
        # Reinitialize state to defaults
        self.__init__()

    def clear(self):
        """Clear status (no-op in virtual mode)."""
        return None

    def initialize(self):
        """Initialize virtual scope to a known state without external I/O."""
        # Keep any provided address; just refresh state
        self.autoscale()
    
    def autoscale(self):
        """
        Reset the oscilloscope to default settings.
        Simulates the autoscale functionality of a physical oscilloscope.
        """
        self.__init__()

    def toggle_channel(self, channel, on=True):
        """
        Enable or disable a specific channel.

        Args:
            channel (int): Channel number (1-4)
            on (bool, optional): True to enable, False to disable. Defaults to True.
        """
        self.state['channels_on'][channel] = on

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        """
        Set the vertical scale parameters for a channel.

        Args:
            channel (int): Channel number (1-4)
            vdiv (float, optional): Volts per division setting
            y_range (float, optional): Vertical range in divisions
        """
        if vdiv is not None:
            self.state['vdiv'][channel] = vdiv
        if y_range is not None:
            self.state['y_range'][channel] = y_range

    def set_vertical_position(self, channel, y_position):
        """
        Set the vertical position of a channel.

        Args:
            channel (int): Channel number (1-4)
            y_position (float): Vertical position in divisions (-40.0 to 40.0)
        """
        self.state['y_position'][channel] = y_position

    def set_input_coupling(self, channel, input_coupling):
        """
        Set the input coupling mode for a channel.

        Args:
            channel (int): Channel number (1-4)
            input_coupling (str): Coupling mode ("AC" or "DC")
        """
        self.state['input_coupling'][channel] = input_coupling

    def set_probe_attenuation(self, channel, probe_attenuation):
        """
        Set the probe attenuation factor for a channel.

        Args:
            channel (int): Channel number (1-4)
            probe_attenuation (float): Attenuation factor (0.001 to 10000.0)
        """
        self.state['probe_attenuation'][channel] = probe_attenuation

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        """
        Set the horizontal scale parameters.

        Args:
            tdiv (float, optional): Time per division in seconds
            x_range (float, optional): Total horizontal range in seconds
        """
        if tdiv is not None:
            self.state['tdiv'] = tdiv
        if x_range is not None:
            self.state['x_range'] = x_range

    def set_horizontal_position(self, x_position):
        """
        Set the horizontal position of the trigger point.

        Args:
            x_position (float): Horizontal position in seconds (-500.0 to 500.0)
        """
        self.state['x_position'] = x_position

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        """
        Configure multiple horizontal parameters at once.

        Args:
            tdiv (float, optional): Time per division in seconds
            x_range (float, optional): Total horizontal range in seconds
            x_position (float, optional): Horizontal position in seconds
        """
        self.set_horizontal_scale(tdiv, x_range)
        if x_position is not None:
            self.set_horizontal_position(x_position)

    def set_trigger_source(self, trigger_source):
        """
        Set the trigger source channel.

        Args:
            trigger_source (str or int): Source channel for triggering.
        """
        mapping = {1: 'CHAN1', 2: 'CHAN2', 3: 'CHAN3', 4: 'CHAN4', '1': 'CHAN1', '2': 'CHAN2', '3': 'CHAN3', '4': 'CHAN4'}
        src = mapping.get(trigger_source, trigger_source)
        self.state['trigger_source'] = src

    def set_trigger_level(self, trigger_level):
        """
        Set the trigger voltage level.

        Args:
            trigger_level (float): Voltage level to trigger at (-6.0V to 6.0V)
        """
        self.state['trigger_level'] = trigger_level

    def set_trigger_slope(self, trigger_slope):
        """
        Set the trigger slope mode.

        Args:
            trigger_slope (str): Edge slope to trigger on.
                Must be one of ["POS", "NEG", "EITH", "ALT"]
                POS: Rising edge
                NEG: Falling edge
                EITH: Either edge
                ALT: Alternate between edges
        """
        self.state['trigger_slope'] = trigger_slope

    def set_trigger_mode(self, trigger_mode):
        """
        Set the trigger mode.

        Args:
            trigger_mode (str): Trigger mode setting.
                Currently only supports "EDGE" mode.
        """
        self.state['trigger_mode'] = trigger_mode

    def set_trigger_sweep(self, trigger_sweep):
        """
        Set the trigger sweep mode.

        Args:
            trigger_sweep (str): Trigger sweep mode.
                Must be one of ["AUTO", "NORM"]
                AUTO: Free-running if no trigger
                NORM: Wait for trigger
        """
        self.state['trigger_sweep'] = trigger_sweep

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None):
        """
        Configure multiple trigger parameters at once.

        Args:
            trigger_source (str, optional): Source channel for triggering
            trigger_level (float, optional): Voltage level to trigger at
            trigger_slope (str, optional): Edge slope to trigger on
            trigger_mode (str, optional): Trigger mode setting

        Example:
            >>> scope.configure_trigger(
            ...     trigger_source="CHAN1",
            ...     trigger_level=1.0,
            ...     trigger_slope="POS",
            ...     trigger_mode="EDGE"
            ... )
        """
        if trigger_source is not None:
            self.set_trigger_source(trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(trigger_mode)

    def manual_trigger(self):
        """Sends a manual force trigger event to the oscilloscope."""
        # Virtual scope responds immediately
        pass

    def arm(self):
        """
        Arms the oscilloscope trigger system.
        
        Sets the scope to wait for the next trigger event based on current settings.
        """
        self.state['armed'] = True

    def set_acquisition(self):
        """Configure basic acquisition parameters (no-op for virtual scope)."""
        pass

    def set_acquisition_channel(self, channel):
        """
        Set the active acquisition channel.

        Args:
            channel (int): Channel number (1-4)
        """
        self.state['acquisition_channel'] = channel

    def set_acquisition_mode(self, acquisition_mode):
        """
        Set the acquisition mode.

        Args:
            acquisition_mode (str): One of ["NORM", "AVER", "HRES", "PEAK"]
        """
        self.state['acquisition_mode'] = acquisition_mode

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        """
        Configure multiple acquisition parameters at once.

        Args:
            channel (int, optional): Channel number (1-4)
            acquisition_mode (str, optional): Acquisition mode
            acquisition_points (int, optional): Number of acquisition points
        """
        if channel is not None:
            self.set_acquisition_channel(channel)
        if acquisition_mode is not None:
            self.set_acquisition_mode(acquisition_mode)
        if acquisition_points is not None:
            self.set_acquisition_points(acquisition_points)

    def quick_read(self):
        """
        Generate a synthetic waveform for testing.

        Returns:
            numpy.ndarray: Synthetic waveform data as 8-bit unsigned integers
        """
        points = self.acquisition_points[1]
        t = np.linspace(0, self.state['x_range'], points)
        freq = 1.0 / (self.state['x_range'] if self.state['x_range'] else 1e-3)
        v = np.sin(2 * np.pi * freq * t) * self.state['vdiv'][self.state['acquisition_channel']] * 2
        return v.astype(np.uint8)

    def get_data(self):
        """
        Get voltage and time data from the virtual scope.

        Returns:
            pandas.DataFrame: DataFrame containing 'Time' and 'Voltage' columns
        """
        voltages, times = self.sample.get_voltage_response()
        return pd.DataFrame({'Time': times, 'Voltage': voltages})

    def toggle_acquisition(self, run=True):
        """
        Start or stop the acquisition.

        Args:
            run (bool): True to start acquisition, False to stop
        """
        self.state['running'] = run
