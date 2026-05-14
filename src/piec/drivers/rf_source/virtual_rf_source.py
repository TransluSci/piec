"""
Virtual RF Source class for testing and simulation.
This module provides a software simulation of an RF Source device for development
and testing without physical hardware.
"""
from .rf_source import RF_source
from ..virtual_instrument import VirtualInstrument


class VirtualRFSource(VirtualInstrument, RF_source):
    """
    Virtual version of an RF Source device for simulation/testing.
    Stores state internally but produces no physical output.
    """

    # --- Class Attributes ---
    # These would normally define the hardware's capabilities. We define some sensible defaults.
    channel = [1]
    frequency = (1e3, 6e9)      # 1 kHz to 6 GHz
    power = (-130.0, 20.0)      # -130 dBm to +20 dBm
    modulation = ['AM', 'FM', 'PM', 'PULSE']

    def __init__(self, address='VIRTUAL', **kwargs):
        """
        Initialize virtual RF source with default settings.

        Args:
            address (str): Virtual address (default: 'VIRTUAL').
            **kwargs: Additional arguments passed to parent classes.
        """
        VirtualInstrument.__init__(self, address=address)
        RF_source.__init__(self, address=address, **kwargs)

        # Internal state tracker
        self.state = {
            'frequency': 1e9,           # 1 GHz default
            'power': -20.0,             # -20 dBm default
            'output_on': {ch: False for ch in self.channel},
            
            # Modulation state
            'modulation_type': 'AM',
            'modulation_enabled': False,
            'am_depth': 50.0,           # 50%
            'am_frequency': 1000.0,     # 1 kHz
            'fm_deviation': 10000.0,    # 10 kHz
            'fm_frequency': 1000.0,     # 1 kHz
            'pulse_width': 1e-6,        # 1 us
            'pulse_period': 10e-6,      # 10 us
            
            # Reference/Sweep state
            'reference_source': 'INT',
            'sweep_start_freq': 1e6,
            'sweep_stop_freq': 1e9,
            'sweep_points': 1001,
            'sweep_output_on': False,
            'sweep_mode': 'LIN'
        }

    # --- SCPI-Equivalent Commands ---

    def idn(self):
        return "PIEC,Virtual_RF_Source,s/n_virtual,ver1.0"

    def reset(self):
        self.__init__()

    def clear(self):
        pass

    def error(self):
        return "No errors."

    def wait(self):
        pass

    def self_test(self):
        return "0"

    def operation_complete(self):
        return "1"

    def initialize(self):
        self.reset()

    # --- RF Source-Specific Methods ---

    # Core RF output functions
    def set_frequency(self, frequency):
        self.state['frequency'] = frequency

    def set_power(self, power):
        self.state['power'] = power

    def output(self, channel, on=True):
        self.state['output_on'][channel] = on

    # Basic modulation functions
    def set_modulation(self, modulation_type):
        self.state['modulation_type'] = modulation_type.upper()

    def enable_modulation(self, on=True):
        self.state['modulation_enabled'] = on

    # AM
    def set_am_depth(self, depth):
        self.state['am_depth'] = depth

    def set_am_frequency(self, frequency):
        self.state['am_frequency'] = frequency

    # FM
    def set_fm_deviation(self, deviation):
        self.state['fm_deviation'] = deviation

    def set_fm_frequency(self, frequency):
        self.state['fm_frequency'] = frequency

    # PM (Pulse)
    def set_pulse_width(self, width):
        self.state['pulse_width'] = width

    def set_pulse_period(self, period):
        self.state['pulse_period'] = period

    # Frequency reference control
    def set_reference_source(self, source):
        self.state['reference_source'] = source.upper()

    # Basic sweep functions
    def set_sweep_start_frequency(self, frequency):
        self.state['sweep_start_freq'] = frequency

    def set_sweep_stop_frequency(self, frequency):
        self.state['sweep_stop_freq'] = frequency

    def set_sweep_points(self, points):
        self.state['sweep_points'] = points

    def output_sweep(self, on=True):
        self.state['sweep_output_on'] = on

    def set_sweep_mode(self, mode):
        self.state['sweep_mode'] = mode.upper()
