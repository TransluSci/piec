"""
Virtual DAQ class that mimics a generic MCC-style DAQ for testing and simulation.
This module provides a software simulation of a DAQ device for development
and testing without physical hardware.
"""
import numpy as np

from .daq import Daq
from ..virtual_instrument import (
    VirtualInstrument,
    warn_for_large_simulation_points,
)


class VirtualDaq(VirtualInstrument, Daq):
    """
    Virtual version of a DAQ device for simulation/testing.
    Stores state internally and generates synthetic data.

    Generic instances inherit the Daq category capabilities, which advertise
    no analog or digital channels. Model-profiled instances use the physical
    model's capability attributes. Digital trigger pulses are simulated only
    when digital channels are advertised; hardware timing is not provided.
    """

    def __init__(self, address='VIRTUAL', **kwargs):
        """
        Initialize virtual DAQ with default settings.

        Args:
            address (str): Virtual address (default: 'VIRTUAL').
            **kwargs: Additional arguments passed to parent classes.
        """
        super().__init__(address=address, **kwargs)

        self.state = {
            'ai_mode': 'SE',
            'ai_values': {ch: 0.0 for ch in self.ai_channel},
            'ao_values': {ch: 0.0 for ch in self.ao_channel},
            'dio_direction': {ch: 'I' for ch in self.dio_channel},
            'dio_values': {ch: 0 for ch in self.dio_channel},
            'ai_channel': 0,
            'ai_range': {ch: (-10.0, 10.0) for ch in self.ai_channel},
            'ai_sample_rate': {ch: 1000.0 for ch in self.ai_channel},
            'ao_channel': 0,
            'ao_range': {ch: (-10.0, 10.0) for ch in self.ao_channel},
            'ao_sample_rate': {ch: 1000.0 for ch in self.ao_channel},
            'di_channel': 0,
            'do_channel': 0,
            'dio_channel': 0,
            'closed': False,
        }

    # --- SCPI-Equivalent Commands ---

    def get_trigger_pulse_capabilities(self):
        """Expose digital pulses as simulation, never hardware timing."""
        capabilities = super().get_trigger_pulse_capabilities()
        if 'digital' in capabilities:
            capabilities['digital']['timing'] = 'simulated'
        return capabilities

    def send_trigger_pulse(self, *args, **kwargs):
        """Simulate digital transitions and retain metadata for completed pulses."""
        result = super().send_trigger_pulse(*args, **kwargs)
        self.state.setdefault('trigger_pulses', []).append(dict(result))
        return result

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

    def error(self):
        """
        Returns the error status (always clean in virtual mode).

        Returns:
            str: Error message.
        """
        return "No errors."

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
        Releases virtual DAQ resources.
        """
        self.state['closed'] = True

    def initialize(self):
        """
        Initialises the virtual DAQ to a known state.
        """
        self.reset()

    # --- Analog Input Methods ---

    def set_AI_channel(self, ai_channel):
        """
        Sets the Analog Input channel for data acquisition.
        """
        self.state['ai_channel'] = ai_channel

    def set_AI_range(self, ai_channel, range):
        """
        Sets the range for the Analog Input channel.
        """
        self.state['ai_range'][ai_channel] = range

    def set_AI_sample_rate(self, ai_channel, sample_rate):
        """
        Sets the sample rate for the Analog Input channel.
        """
        self.state['ai_sample_rate'][ai_channel] = sample_rate

    def configure_AI_channel(self, ai_channel, range=None, sample_rate=None):
        """
        Configures the Analog Input channel.
        """
        if range is not None:
            self.set_AI_range(ai_channel, range)
        if sample_rate is not None:
            self.set_AI_sample_rate(ai_channel, sample_rate)

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

    def set_AO_channel(self, ao_channel):
        """
        Sets the Analog Output channel.
        """
        self.state['ao_channel'] = ao_channel

    def set_AO_range(self, ao_channel, range):
        """
        Sets the range for the Analog Output channel.
        """
        self.state['ao_range'][ao_channel] = range

    def set_AO_sample_rate(self, ao_channel, sample_rate):
        """
        Sets the sample rate for the Analog Output channel.
        """
        self.state['ao_sample_rate'][ao_channel] = sample_rate

    def configure_AO_channel(self, ao_channel, range=None, sample_rate=None):
        """
        Configures the Analog Output channel.
        """
        if range is not None:
            self.set_AO_range(ao_channel, range)
        if sample_rate is not None:
            self.set_AO_sample_rate(ao_channel, sample_rate)

    def write_AO(self, ao_channel, data):
        """
        Writes data to the Analog Output channel.

        args:
            ao_channel (int): The channel to write to (0-1).
            data (float or list): The voltage(s) to output.
        """
        if isinstance(data, (int, float)):
            self.state['ao_values'][ao_channel] = float(data)
        elif len(data) > 0:
            self.state['ao_values'][ao_channel] = float(data[-1])

    def write_AO_scan(self, ao_channel, data, sample_rate):
        """Simulate a continuous hardware-paced analog output waveform."""
        if len(data) > 0:
            self.state['ao_values'][ao_channel] = float(data[-1])
        self.state['ao_sample_rate'][ao_channel] = float(sample_rate)

    def stop_output(self):
        """Stop simulated continuous analog output."""
        pass

    # --- Digital I/O Methods ---

    def set_DI_channel(self, dio_channel):
        """
        Sets the Digital Input channel.
        """
        self.state['di_channel'] = dio_channel

    def set_DI_sample_rate(self, dio_channel, sample_rate):
        """
        Sets the sample rate for the Digital Input channel.
        """
        pass

    def configure_DI_channel(self, dio_channel, sample_rate=None):
        """
        Configures the Digital Input channel.
        """
        if sample_rate is not None:
            self.set_DI_sample_rate(dio_channel, sample_rate)

    def set_DO_channel(self, dio_channel):
        """
        Sets the Digital Output channel.
        """
        self.state['do_channel'] = dio_channel

    def set_DO_sample_rate(self, dio_channel, sample_rate):
        """
        Sets the sample rate for the Digital Output channel.
        """
        pass

    def configure_DO_channel(self, dio_channel, sample_rate=None):
        """
        Configures the Digital Output channel.
        """
        if sample_rate is not None:
            self.set_DO_sample_rate(dio_channel, sample_rate)

    def write_DO(self, dio_channel, data):
        """
        Writes data to the Digital Output channel.

        args:
            dio_channel (int): The channel to write to.
            data (int/bool or list): 1/True for High, 0/False for Low.
        """
        if isinstance(data, (int, bool)):
            self.state['dio_values'][dio_channel] = 1 if data else 0
        elif len(data) > 0:
            self.state['dio_values'][dio_channel] = 1 if data[-1] else 0

    def set_DIO_channel(self, dio_channel):
        """
        Sets the Digital I/O channel.
        """
        self.state['dio_channel'] = dio_channel

    def set_DIO_mode(self, dio_channel, mode):
        """
        Sets the direction for the Digital I/O channel.
        """
        self.state['dio_direction'][dio_channel] = mode

    def set_DIO_sample_rate(self, dio_channel, sample_rate):
        """
        Sets the sample rate for the Digital I/O channel.
        """
        pass

    def configure_DIO_channel(self, dio_channel, mode=None, sample_rate=None):
        """
        Configures the Digital I/O channel.
        """
        if mode is not None:
            self.set_DIO_mode(dio_channel, mode)
        if sample_rate is not None:
            self.set_DIO_sample_rate(dio_channel, sample_rate)

    def set_dio_direction(self, dio_channel, dio_direction):
        """
        Configures a digital pin as Input or Output.

        args:
            dio_channel (int): The channel to configure.
            dio_direction (str): 'I' for Input, 'O' for Output.
        """
        self.state['dio_direction'][dio_channel] = dio_direction

    # --- Data Acquisition Methods ---

    def read_data(self, ai_channel):
        """
        Reads data from the specified channel.

        Returns:
            float or int: Simulated value (0.0 for AI, 0 for DI).
        """
        if ai_channel in self.state['ai_values']:
            return self.state['ai_values'][ai_channel]
        return 0

    def read_AI(self, ai_channel):
        """
        Reads a simulated voltage from the specified Analog Input channel.

        args:
            ai_channel (int): The channel to read from.
        returns:
            float: Simulated voltage (0.0V).
        """
        return self.state['ai_values'].get(ai_channel, 0.0)

    def read_AI_scan(self, ai_channel, points, rate, *, on_chunk=None, stop_event=None):
        """
        Acquire a finite scan of one or more analog inputs.
        Use the device clock where available. A software fallback must
        document its timing and keep channel readings in the same scan.
        args:
            ai_channel (int or list[int]): One channel or a nonempty list of
                unique channels from the model's `ai_channel` capability.
            points (int): Number of samples to acquire per channel.
            rate (float): Requested sample rate in Hz per channel.
            on_chunk (callable, optional): Keyword-only callback invoked with
                incremental scan DataFrames while the scan is in progress.
            stop_event (threading.Event, optional): Keyword-only event checked
                while polling the scan buffer to stop acquisition early.
        Returns:
            data (pandas.DataFrame): 'Time' in seconds from scan start,
                followed by voltage columns in volts. One channel, including
                a one-element list, returns 'Time', 'Voltage'. Multiple
                channels return 'Time' followed by 'AI<n>' columns in
                selection order, where n is the DAQ channel number.
                data.attrs['sample_rate'] holds the actual per-channel rate in Hz.
        """
        channels = self._scan_channels(ai_channel)
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise ValueError('points must be a positive integer')
        if on_chunk is not None and not callable(on_chunk):
            raise TypeError('on_chunk must be callable when provided')
        if stop_event is not None and not callable(getattr(stop_event, 'is_set', None)):
            raise TypeError('stop_event must provide an is_set() method when provided')
        low, high = self.ai_sample_rate
        if not np.isfinite(rate) or rate <= 0 or (low is not None and rate < low) or (high is not None and rate > high):
            raise ValueError(f'Input scan rate must be between {low} and {high}')
        warn_for_large_simulation_points(points * len(channels), label="virtual DAQ scan")
        time = np.arange(points) / rate
        values = np.sin(2 * np.pi * 10 * time)
        scan = self._scan_dataframe(channels, time, np.repeat(values[:, None], len(channels), axis=1), rate)
        if on_chunk is not None:
            chunk_size = max(1, int(round(rate * 0.05)))
            emitted = 0
            for start in range(0, len(scan), chunk_size):
                if stop_event is not None and stop_event.is_set():
                    break
                chunk = scan.iloc[start:start + chunk_size].copy()
                chunk.attrs['sample_rate'] = rate
                on_chunk(chunk)
                emitted += len(chunk)
            if stop_event is not None and stop_event.is_set():
                trimmed = scan.iloc[:emitted].copy()
                trimmed.attrs['sample_rate'] = rate
                return trimmed
        return scan

    def read_DI(self, dio_channel):
        """
        Reads the state of a simulated digital input channel.

        args:
            dio_channel (int): The channel to read.
        returns:
            int: Simulated value (0).
        """
        return self.state['dio_values'].get(dio_channel, 0)

    def output(self, ao_channel, on=True):
        """
        Enables or disables output on a channel (no-op in virtual mode).

        args:
            ao_channel (int): The channel.
            on (bool): True to enable, False to disable.
        """
        pass
