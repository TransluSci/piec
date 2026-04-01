"""
Virtual Arbitrary Waveform Generator (AWG) Module

This module provides a virtual implementation of the Keysight 81150A AWG for simulation and testing purposes.
It mimics the behavior of a physical AWG by maintaining internal state and generating synthetic waveforms.
"""

import numpy as np

from ..virtual_instrument import VirtualInstrument
from .awg import Awg
from ..scpi import Scpi

class VirtualAwg(VirtualInstrument, Awg, Scpi):
    """
    Virtual version of the Keysight81150a AWG for simulation/testing.
    Stores state internally and generates synthetic output.

    Attributes:
        channel (list): Available output channels [1, 2]
        waveform (list): Supported waveform types ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
        amplitude (tuple): Output amplitude range in volts (min, max)
        offset (tuple): DC offset range in volts (min, max)
        polarity (list): Output polarity modes ['NORM', 'INV']
        duty_cycle (tuple): Duty cycle range in percent (min, max)
        symmetry (tuple): Ramp symmetry range in percent (min, max)
        pulse_width (tuple): Pulse width range in seconds (min, max)
        pulse_delay (tuple): Pulse delay range in seconds (min, max)
        trigger_source (list): Available trigger sources ['IMM', 'INT', 'EXT', 'MAN']
        trigger_slope (list): Trigger slope options ['POS', 'NEG', 'EITH']
        trigger_mode (list): Trigger mode options ['EDGE', 'LEV']
        arb_dac_value (tuple): DAC value range for arbitrary waveforms (min, max)
        arb_data_length (tuple): Number of points range for arbitrary waveforms (min, max)
    """

    channel = [1, 2]
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
    amplitude = (0, 5)
    offset = amplitude
    polarity = ['NORM', 'INV']
    duty_cycle = (0.0, 100.0)
    symmetry = (0.0, 100.0)
    pulse_width = (4.1e-9, 950000)
    pulse_delay = pulse_width
    trigger_source = ['IMM', 'INT', 'EXT', 'MAN']
    trigger_slope = ['POS', 'NEG', 'EITH']
    trigger_mode = ['EDGE', 'LEV']

    arb_dac_value = (0, 16383) # Range for individual DAC points in arb_data_range data list
    arb_data_range = (2, 1000) # Points, for arbitrary waveform data len

    def __init__(self, address='123'):
        """
        Initialize the virtual AWG with default settings.

        Args:
            address (str, optional): Virtual address for the instrument. Defaults to '123'.
        """
        VirtualInstrument.__init__(self, address=address)

        self.instrument = self
        
        self.state = {
            'output': {ch: False for ch in self.channel},
            'waveform': {ch: 'SIN' for ch in self.channel},
            'frequency': {ch: 1e3 for ch in self.channel},
            'amplitude': {ch: 1.0 for ch in self.channel},
            'offset': {ch: 0.0 for ch in self.channel},
            'source_impedance': {ch: 5 for ch in self.channel},
            'load_impedance': {ch: 50.0 for ch in self.channel},
            'polarity': {ch: 'NORM' for ch in self.channel},
            'duty_cycle': {ch: 50.0 for ch in self.channel},
            'symmetry': {ch: 50.0 for ch in self.channel},
            'pulse_width': {ch: 1e-6 for ch in self.channel},
            'pulse_delay': {ch: 0.0 for ch in self.channel},
            'trigger_source': {ch: 'IMM' for ch in self.channel},
            'trigger_level': {ch: 0.0 for ch in self.channel},
            'trigger_slope': {ch: 'POS' for ch in self.channel},
            'trigger_mode': {ch: 'EDGE' for ch in self.channel},
            'arb_waveform': {ch: None for ch in self.channel},
            'acquisition_channel': 1,  # Default acquisition channel
        }
       
    
    def idn(self):
        """Get the identification string of the virtual AWG.
        
        Returns:
            str: Identification string "Virtual AWG"
        """
        return "Virtual AWG"

    def send_software_trigger(self):
        """Send a software trigger command to the AWG."""
        self.write('*TRG')

    def output_trigger(self):
        """
        Outputs the trigger signal for the awg.
        Equivalent to sending a manual trigger.
        """
        self.write(':TRIG')

    def write(self, command):
        """
        Simulate writing a SCPI command to the instrument.

        Args:
            command (str): SCPI command string to process
        """
        if command.upper() == '*TRG' or command.upper() == ':TRIG':
            
            v = self.get_waveform(self.state['acquisition_channel'])
            
            freq = self.state['frequency'][self.state['acquisition_channel']]
            duration = 1.0 / freq  # one period
            
            # Prepend zeros to simulate trigger delay and baseline for analysis
            prep_points = max(20, len(v) // 10)
            v = np.concatenate([np.zeros(prep_points), v])
            t = np.linspace(0, duration * (1 + prep_points / (len(v) - prep_points)), len(v))
            
            print("Applying waveform to virtual sample...")
           
            self.sample.apply_waveform(v, t)
        else: 
            pass
        # Simulate writing a command to the instrument
        
    def set_source_impedance(self, channel, source_impedance):
        """
        Set the source impedance for a channel.

        Args:
            channel (int): Channel number (1-2)
            source_impedance (float): Source impedance in ohms
        """
        self.state['source_impedance'][channel] = source_impedance

    def output(self, channel, on=True):
        """
        Enable or disable the output for a channel.

        Args:
            channel (int): Channel number (1-2)
            on (bool, optional): True to enable output, False to disable. Defaults to True.
        """
        self.state['output'][channel] = on

    def set_waveform(self, channel, waveform):
        """
        Set the waveform type for a channel.

        Args:
            channel (int): Channel number (1-2)
            waveform (str): Waveform type (e.g., 'SIN', 'SQU', etc.)
        """
        self.state['waveform'][channel] = waveform

    def set_frequency(self, channel, frequency):
        """
        Set the frequency for a channel.

        Args:
            channel (int): Channel number (1-2)
            frequency (float): Frequency in hertz
        """
        self.state['frequency'][channel] = frequency

    def set_amplitude(self, channel, amplitude):
        """
        Set the amplitude for a channel.

        Args:
            channel (int): Channel number (1-2)
            amplitude (float): Amplitude in volts
        """
        self.state['amplitude'][channel] = amplitude

    def set_offset(self, channel, offset):
        """
        Set the DC offset for a channel.

        Args:
            channel (int): Channel number (1-2)
            offset (float): DC offset in volts
        """
        self.state['offset'][channel] = offset

    def set_load_impedance(self, channel, load_impedance):
        """
        Set the load impedance for a channel.

        Args:
            channel (int): Channel number (1-2)
            load_impedance (float): Load impedance in ohms
        """
        self.state['load_impedance'][channel] = load_impedance

    def set_polarity(self, channel, polarity):
        """
        Set the output polarity for a channel.

        Args:
            channel (int): Channel number (1-2)
            polarity (str): Polarity mode ('NORM' or 'INV')
        """
        self.state['polarity'][channel] = polarity

    def configure_waveform(self, channel, waveform, frequency=None, amplitude=None, offset=None, load_impedance=None, polarity=None, user_func=None):
        """
        Configure the waveform settings for a channel.

        Args:
            channel (int): Channel number (1-2)
            waveform (str): Waveform type
            frequency (float, optional): Frequency in hertz
            amplitude (float, optional): Amplitude in volts
            offset (float, optional): DC offset in volts
            load_impedance (float, optional): Load impedance in ohms
            polarity (str, optional): Polarity mode ('NORM' or 'INV')
            user_func (callable, optional): User-defined function for 'USER' waveform
        """
        self.set_waveform(channel, waveform)
        if frequency is not None:
            self.set_frequency(channel, frequency)
        if amplitude is not None:
            self.set_amplitude(channel, amplitude)
        if offset is not None:
            self.set_offset(channel, offset)
        if load_impedance is not None:
            self.set_load_impedance(channel, load_impedance)
        if polarity is not None:
            self.set_polarity(channel, polarity)
        if waveform == 'USER' and user_func is not None:
            self.state['arb_waveform'][channel] = np.array(user_func)

    def set_square_duty_cycle(self, channel, duty_cycle):
        """
        Set the duty cycle for square waves.

        Args:
            channel (int): Channel number (1-2)
            duty_cycle (float): Duty cycle in percent
        """
        self.state['duty_cycle'][channel] = duty_cycle

    def set_ramp_symmetry(self, channel, symmetry):
        """
        Set the symmetry for ramp waves.

        Args:
            channel (int): Channel number (1-2)
            symmetry (float): Symmetry in percent
        """
        self.state['symmetry'][channel] = symmetry

    def set_pulse_width(self, channel, pulse_width):
        """
        Set the pulse width for pulse waves.

        Args:
            channel (int): Channel number (1-2)
            pulse_width (float): Pulse width in seconds
        """
        self.state['pulse_width'][channel] = pulse_width

    def set_pulse_rise_time(self, channel, rise_time):
        # Not simulated
        pass

    def set_pulse_fall_time(self, channel, fall_time):
        # Not simulated
        pass

    def set_pulse_duty_cycle(self, channel, duty_cycle):
        """
        Set the duty cycle for pulse waves.

        Args:
            channel (int): Channel number (1-2)
            duty_cycle (float): Duty cycle in percent
        """
        self.state['duty_cycle'][channel] = duty_cycle

    def set_pulse_delay(self, channel, pulse_delay):
        """
        Set the pulse delay for pulse waves.

        Args:
            channel (int): Channel number (1-2)
            pulse_delay (float): Pulse delay in seconds
        """
        self.state['pulse_delay'][channel] = pulse_delay

    def configure_pulse(self, channel, pulse_width=None, pulse_delay=None, rise_time=None, fall_time=None, duty_cycle=None):
        """
        Configure the pulse settings for a channel.

        Args:
            channel (int): Channel number (1-2)
            pulse_width (float, optional): Pulse width in seconds
            pulse_delay (float, optional): Pulse delay in seconds
            rise_time (float, optional): Rise time in seconds
            fall_time (float, optional): Fall time in seconds
            duty_cycle (float, optional): Duty cycle in percent
        """
        self.set_waveform(channel, 'PULS')
        if pulse_delay is not None:
            self.set_pulse_delay(channel, pulse_delay)
        if pulse_width is not None:
            self.set_pulse_width(channel, pulse_width)
        if rise_time is not None:
            self.set_pulse_rise_time(channel, rise_time)
        if fall_time is not None:
            self.set_pulse_fall_time(channel, fall_time)
        if duty_cycle is not None:
            self.set_pulse_duty_cycle(channel, duty_cycle)

    def create_arb_waveform(self, channel, name, data):
        """
        Create and store an arbitrary waveform.

        Args:
            channel (int): Channel number (1-2)
            name (str): Name of the waveform
            data (list or np.array): Waveform data points
        """
        # Store the arbitrary waveform in state
        data_arr = np.array(data)
        max_abs = np.max(np.abs(data_arr))
        if max_abs > 0:
            voltage_data = data_arr / max_abs
        else:
            voltage_data = data_arr
        
        self.state['arb_waveform'][channel] = voltage_data

    def set_arb_waveform(self, channel, name):
        """
        Set the arbitrary waveform for a channel.

        Args:
            channel (int): Channel number (1-2)
            name (str): Name of the waveform
        """
        # For simulation, just mark the waveform as selected
        self.state['waveform'][channel] = 'USER'
        

    def set_trigger_source(self, channel, trigger_source):
        """
        Set the trigger source for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_source (str): Trigger source ('IMM', 'INT', 'EXT', 'MAN')
        """
        self.state['trigger_source'][channel] = trigger_source

    def set_trigger_level(self, channel, trigger_level):
        """
        Set the trigger level for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_level (float): Trigger level voltage
        """
        self.state['trigger_level'][channel] = trigger_level

    def set_trigger_slope(self, channel, trigger_slope):
        """
        Set the trigger slope for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_slope (str): Trigger slope ('POS', 'NEG', 'EITH')
        """
        self.state['trigger_slope'][channel] = trigger_slope

    def set_trigger_mode(self, channel, trigger_mode):
        """
        Set the trigger mode for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_mode (str): Trigger mode ('EDGE' or 'LEV')
        """
        self.state['trigger_mode'][channel] = trigger_mode

    def configure_trigger(self, channel, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None):
        """
        Configure the trigger settings for a channel.

        Args:
            channel (int): Channel number (1-2)
            trigger_source (str, optional): Trigger source
            trigger_level (float, optional): Trigger level voltage
            trigger_slope (str, optional): Trigger slope
            trigger_mode (str, optional): Trigger mode
        """
        if trigger_source is not None:
            self.set_trigger_source(channel, trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(channel, trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(channel, trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(channel, trigger_mode)

    def configure_output_amplifier(self, channel='1', type='HIV'):
        """
        Configure the output amplifier settings.

        Args:
            channel (str, optional): Channel number as string ('1' or '2')
            type (str, optional): Amplifier type ('HIV' or 'HIB')
        """
        # Simulate amplifier config by changing amplitude range
        if type == 'HIV':
            self.amplitude = (0, 10)
        elif type == 'HIB':
            self.amplitude = (0, 5)

    def get_waveform(self, channel):
        """
        Generate a synthetic waveform based on current settings.

        Args:
            channel (int): Channel number (1-2)

        Returns:
            np.array: Array of waveform data points
        """
        print("Getting waveform for channel:", channel)
        wf = self.state['waveform'][channel]
        amp = self.state['amplitude'][channel]
        freq = self.state['frequency'][channel]
        offset = self.state['offset'][channel]
        t = np.linspace(0, 1, self.arb_data_range[1])
        
        
        if wf.upper() == 'SIN':
            v = amp * np.sin(2 * np.pi * t) + offset
        elif wf.upper() == 'SQU':
            v = amp * np.sign(np.sin(2 * np.pi * t)) + offset
        elif wf.upper() == 'RAMP':
            v = amp * (2 * (t % 1) - 1) + offset
        elif wf.upper() == 'PULS':
            duty = self.state['duty_cycle'][channel] / 100.0
            v = amp * (np.mod(t, 1) < duty) + offset
        elif wf.upper() == 'NOIS':
            v = amp * np.random.randn(self.arb_data_range) + offset
        elif wf.upper() == 'DC':
            v = np.ones(self.arb_data_range) * offset
        elif wf.upper() == 'USER' and self.state['arb_waveform'][channel] is not None:
            
            data = self.state['arb_waveform'][channel]
            v = np.interp(np.linspace(0, len(data)-1, self.arb_data_range[1]), np.arange(len(data)), data)
            v = v * amp
        else:
            v = np.zeros(self.arb_data_range[1])
        
        return v

