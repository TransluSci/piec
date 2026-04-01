"""
Emulator class to allow a DAQ to function as an Oscilloscope.
"""
import numpy as np
import pandas as pd
from ..oscilloscope.oscilloscope import Oscilloscope
from ..daq.daq import Daq

class DaqAsOscilloscope(Oscilloscope):
    """
    Adapter class that wraps a Daq instance and exposes it as an Oscilloscope.
    """
    
    def __init__(self, daq_instance: Daq, address="EMULATED_SCOPE", **kwargs):
        """
        Initialize the emulator.
        
        args:
            daq_instance (Daq): The underlying DAQ instrument driver instance.
            address (str): Dummy address.
        """
        super().__init__(address, **kwargs)
        self.daq = daq_instance
        
        # Internal state to map Scope params to DAQ params
        self._scope_state = {
            # Horizontal
            'tdiv': 1e-3, # 1 ms/div
            'x_pos': 0.0,
            
            # Acquisition
            'points': 1000,
            'acq_mode': 'NORM',
            'running': True,
            'acq_channel': 1, # Default to 1 (Scope Convention)
            
            # Trigger
            'trigger_source': 'CH1', # Scope Convention
            'trigger_level': 0.0,
            'trigger_slope': 'POS',
            'trigger_mode': 'AUTO',
            'trigger_sweep': 'AUTO',
            
            # Channel specific storage
            'channels': {}
        }
        
        # Initialize channels based on DAQ capabilities
        self._sync_channels_from_daq()

    def _sync_channels_from_daq(self):
        """
        Populates the scope channels based on the underlying DAQ's available AI channels.
        Converts DAQ 0-based indices to Scope 1-based indices.
        """
        if hasattr(self.daq, 'ai_channel') and self.daq.ai_channel:
             daq_channels = self.daq.ai_channel
        else:
             # Fallback if DAQ doesn't expose list
             daq_channels = [0]
             
        # Convert to 1-based SCOPE channels
        scope_channels = [ch + 1 for ch in daq_channels]
             
        # Initialize state for each available channel
        for ch in scope_channels:
            if ch not in self._scope_state['channels']:
                self._scope_state['channels'][ch] = {
                    'vdiv': 1.0,
                    'y_pos': 0.0,
                    'coupling': 'DC',
                    'impedance': '1M',
                    'attenuation': 1.0,
                    'on': True
                }
        
        # If current acq_channel is invalid, reset to first available
        if self._scope_state['acq_channel'] not in scope_channels:
             self._scope_state['acq_channel'] = scope_channels[0]
             
        # Expose to base class
        self.channel = scope_channels

    def _get_ch_state(self, channel):
        if channel not in self._scope_state['channels']:
            # Auto-create if missing
             self._scope_state['channels'][channel] = {
                'vdiv': 1.0,
                'y_pos': 0.0,
                'coupling': 'DC',
                'impedance': '1M',
                'attenuation': 1.0,
                'on': True
            }
        return self._scope_state['channels'][channel]
        
    # --- Helper to calculate DAQ parameters ---
    
    def _apply_settings_to_daq(self, channel):
        """
        Translates scope settings (time/div) into DAQ settings (sample rate, num points).
        Maps Scope Channel (1-based) to DAQ Channel (0-based).
        """
        daq_channel = channel - 1 # Convert to 0-based for hardware
        
        # Time Base
        total_time = self._scope_state['tdiv'] * 10
        num_points = self._scope_state['points']
        
        if total_time <= 0:
             sample_rate = 1000
        else:
             sample_rate = num_points / total_time
        
        ch_state = self._get_ch_state(channel)
        
        v_range_scope_display = ch_state['vdiv'] * 8
        v_range_daq_input = v_range_scope_display / ch_state['attenuation']
        
        try:
            self.daq.configure_AI_channel(daq_channel, range=v_range_daq_input, sample_rate=sample_rate)
        except Exception as e:
            print(f"Warning: DAQ configuration failed for channel {channel} (DAQ: {daq_channel}): {e}")

    # --- Vertical ---

    def autoscale(self):
        """
        Mock autoscale. In a real emulator, we might scan ranges.
        Here we just reset to defaults.
        """
        print("Emulating autoscale... (resetting to defaults)")
        self._scope_state['tdiv'] = 1e-3
        if 1 in self._scope_state['channels']:
             self._scope_state['channels'][1]['vdiv'] = 1.0
             self._scope_state['channels'][1]['y_pos'] = 0.0

    def toggle_channel(self, channel, on=True):
        self._get_ch_state(channel)['on'] = on

    def set_vertical_scale(self, channel, vdiv, y_range=None):
        self._get_ch_state(channel)['vdiv'] = vdiv
        
    def set_vertical_position(self, channel, y_position):
        self._get_ch_state(channel)['y_pos'] = y_position
        
    def set_input_coupling(self, channel, input_coupling):
        input_coupling = input_coupling.upper()
        self._get_ch_state(channel)['coupling'] = input_coupling
        if input_coupling != 'DC':
            print(f"Warning: DAQ Emulator typically only supports DC coupling. Set {input_coupling} ignored in hardware.")

    def set_probe_attenuation(self, channel, probe_attenuation):
        self._get_ch_state(channel)['attenuation'] = probe_attenuation

    def set_channel_impedance(self, channel, channel_impedance):
        self._get_ch_state(channel)['impedance'] = channel_impedance
        
    def set_input_mode(self, mode):
        """
        Sets the input mode of the DAQ (e.g. 'SE' for Single-Ended, 'DIFF' for Differential).
        And refreshes the available channel list.
        """
        if hasattr(self.daq, 'set_input_mode'):
            try:
                self.daq.set_input_mode(mode)
                # Sync new channels
                self._sync_channels_from_daq()
            except Exception as e:
                print(f"Error setting input mode: {e}")
        else:
            print("Warning: Underlying DAQ does not support 'set_input_mode'.")
            
    # --- Horizontal ---
    
    def set_horizontal_scale(self, tdiv, x_range=None):
        self._scope_state['tdiv'] = tdiv
        
    def set_horizontal_position(self, x_position):
        self._scope_state['x_pos'] = x_position

    def configure_horizontal(self, tdiv, x_range, x_position):
        self.set_horizontal_scale(tdiv, x_range)
        self.set_horizontal_position(x_position)

    # --- Trigger ---
    
    def set_trigger_source(self, trigger_source):
        self._scope_state['trigger_source'] = trigger_source.upper()
        
    def set_trigger_level(self, trigger_level):
        self._scope_state['trigger_level'] = trigger_level
        
    def set_trigger_slope(self, trigger_slope):
        self._scope_state['trigger_slope'] = trigger_slope.upper()

    def set_trigger_mode(self, trigger_mode):
        self._scope_state['trigger_mode'] = trigger_mode.upper()

    def set_trigger_sweep(self, trigger_sweep):
        self._scope_state['trigger_sweep'] = trigger_sweep.upper()

    def configure_trigger(self, trigger_source, trigger_level, trigger_slope, trigger_mode):
        self.set_trigger_source(trigger_source)
        self.set_trigger_level(trigger_level)
        self.set_trigger_slope(trigger_slope)
        self.set_trigger_mode(trigger_mode)

    # --- Acquisition ---
    
    def toggle_acquisition(self, run=True):
        self._scope_state['running'] = run
        
    def arm(self):
        # Prepare for single shot if needed
        pass

    def set_acquisition(self):
        # Apply current settings to DAQ
        # Usually applied just-in-time before read, but valid here too.
        self._apply_settings_to_daq(self._scope_state['acq_channel'])

    def set_acquisition_channel(self, channel):
        self._scope_state['acq_channel'] = channel

    def set_acquisition_mode(self, acquisition_mode):
        self._scope_state['acq_mode'] = acquisition_mode.upper()

    def set_acquisition_points(self, acquisition_points):
        self._scope_state['points'] = acquisition_points

    def configure_acquisition(self, channel, acquisition_mode, acquisition_points):
        self.set_acquisition_channel(channel)
        self.set_acquisition_mode(acquisition_mode)
        self.set_acquisition_points(acquisition_points)

    # --- Data Access ---

    def _acquire_waveform(self, channel):
        """
        Acquires a waveform. Prefers hardware scan, falls back to software loop.
        Returns:
            tuple: (data_array, actual_duration_seconds)
        """
        # Ensure configured
        self._apply_settings_to_daq(channel)
        
        daq_channel = channel - 1 # Convert to 0-based for hardware
        
        num_points = self._scope_state['points']
        total_time_target = self._scope_state['tdiv'] * 10
        
        # 1. Try Hardware Scan
        if hasattr(self.daq, 'read_AI_scan'):
            try:
                sample_rate = num_points / total_time_target
                
                # Check for Max Rate Limit (USB-231 limit is 50kHz)
                MAX_RATE = 50000.0
                if sample_rate > MAX_RATE:
                    new_points = int(total_time_target * MAX_RATE)
                    # Don't let it drop below minimum
                    if new_points < 10: new_points = 10
                    
                    print(f"Warning: Requested rate {sample_rate/1000:.1f} kHz exceeds limit ({MAX_RATE/1000:.1f} kHz). Reducing points from {num_points} to {new_points} to maintain timebase.")
                    
                    num_points = new_points
                    sample_rate = MAX_RATE
                
                # Hardware scan assumes perfect timing
                # NOTE: data might be shorter now, but duration is same
                data = np.array(self.daq.read_AI_scan(daq_channel, num_points, sample_rate))
                return data, total_time_target
            except Exception as e:
                print(f"Hardware scan failed, falling back to software: {e}")
                pass # Fallback
        
        # 2. Software Scan
        if num_points > 1:
            dt = total_time_target / num_points
        else:
            dt = 0
            
        data = []
        import time
        
        # Measure ACTUAL duration
        start_time = time.perf_counter()
        next_sample = start_time
        
        read_func = self.daq.read_AI
        sleep = time.sleep
        perf_counter = time.perf_counter
        
        for _ in range(num_points):
            try:
                val = read_func(daq_channel)
                data.append(val)
            except Exception as e:
                print(f"Acquisition error: {e}")
                break
            
            # Soft Pacing
            next_sample += dt
            now = perf_counter()
            if next_sample > now:
                 sleep(next_sample - now)
        
        actual_duration = time.perf_counter() - start_time
        return np.array(data), actual_duration

    def quick_read(self):
        """
        Returns a snapshot (numpy array).
        """
        if not self._scope_state['running']:
             return np.array([])
             
        channel = self._scope_state['acq_channel']
        ch_state = self._get_ch_state(channel)
        
        raw_data, _ = self._acquire_waveform(channel)
        
        if len(raw_data) == 0:
            return np.array([])
            
        scaled_data = raw_data * ch_state['attenuation']
        return scaled_data

    def get_data(self):
        """
        Returns a DataFrame with 'Time' and Channel data.
        """
        channel = self._scope_state['acq_channel']
        ch_state = self._get_ch_state(channel)
        
        if not ch_state['on']:
             return pd.DataFrame()
             
        raw_data, actual_duration = self._acquire_waveform(channel)
        
        n = len(raw_data)
        if n == 0:
            return pd.DataFrame()
            
        # Reconstruct Time Axis using ACTUAL duration if significantly different from target
        # This fixes the "wrong time scale" issue when software loop is too slow.
        target_time = self._scope_state['tdiv'] * 10
        
        # If actual duration is > 10% larger than target, use actual (System is lagging)
        # Otherwise typically use target (clean numbers)
        if actual_duration > target_time * 1.1:
            total_time = actual_duration
            # Maybe print a warning once per run?
            # print(f"Warning: System unable to maintain sample rate. Slowed down to {actual_duration:.2f}s")
        else:
            total_time = target_time
            
        if n > 1:
            dt = total_time / n
        else:
             dt = 0
             
        t = np.arange(n) * dt + self._scope_state['x_pos']
        
        scaled_data = raw_data * ch_state['attenuation']
        
        df = pd.DataFrame({
            "Time": t,
            f"Channel {channel}": scaled_data
        })
        return df

