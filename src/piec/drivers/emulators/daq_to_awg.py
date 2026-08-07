"""
Emulator class to allow a DAQ to function as an AWG.
"""
import numpy as np
from ..awg.awg import Awg
from ..daq.daq import Daq
import threading
import time

class DaqAsAwg(Awg):
    """
    Adapter class that wraps a Daq instance and exposes it as an Awg.
    
    This allows a DAQ to be used in scripts that expect an AWG, by
    synthesizing standard waveforms (SIN, SQU, etc.) into data arrays
    that the DAQ can write to its analog outputs.
    """
    
    def __init__(self, daq_instance: Daq, **kwargs):
        """
        Initialize the emulator.
        
        args:
            daq_instance (Daq): The underlying DAQ instrument driver instance.
        """
        self._initialize_common_state(
            check_params=kwargs.pop("check_params", False),
            verbose=kwargs.pop("verbose", False),
        )

        self.daq = daq_instance

        # State tracking for waveform parameters
        self._wav_params = {} # Key: channel, Value: dict of params
        
        # Default sample rate - this is CRITICAL for synthesizing waveforms
        # Ideally this comes from the DAQ or is configured. 
        # For now, we'll default to something reasonable or ask the DAQ (if implemented)
        if hasattr(daq_instance, 'max_rate'):
            self.sample_rate = daq_instance.max_rate
        else:
            self.sample_rate = 5000 # Safe default for MCC USB-231 
        
        # Background generation state
        self._output_thread = None
        self._stop_event = None 
        
        # Arbitrary Waveform Storage
        self._arb_waveforms = {} # Key: name, Value: numpy array 
        
        # Track active channels for auto-update
        self._active_channels = set()
        
    def _get_params(self, channel):
        if channel not in self._wav_params:
            self._wav_params[channel] = {
                'waveform': 'SIN',
                'frequency': 1000.0,
                'amplitude': 1.0,
                'offset': 0.0,
                'phase': 0.0,
                'duty_cycle': 50.0,
                'symmetry': 50.0, # for ramp
                'pulse_width': None
            }
        return self._wav_params[channel]

    def _update_if_active(self, channel):
        """Restarts output if the channel is currently active."""
        if channel in self._active_channels:
            self.output(channel, True)
    
    def set_sample_rate(self, sample_rate):
        """Sets the synthesis sample rate in Hz"""
        self.sample_rate = sample_rate
        # Changing sample rate affects all channels? 
        # For now, simplistic update:
        for ch in list(self._active_channels):
            self.output(ch, True)

    # --- Standard AWG Implementation ---

    def output(self, channel, on=True):
        """
        Starts or stops the generation.
        Argument 'on' turns output on (True) or off (False).
        """
        # Stop any existing background thread/scan first
        if hasattr(self, '_stop_event') and self._stop_event:
            self._stop_event.set()
        if hasattr(self, '_output_thread') and self._output_thread and self._output_thread.is_alive():
            self._output_thread.join()
            self._output_thread = None

        if on:
            self._active_channels.add(channel)
            
            # Synthesize data
            data = self._synthesize_waveform(channel)
            self._current_data = data # Store for thread access
            
            # --- Attempt 1: Harware Background Scan (mccdig style) ---
            # Try to use the high-performance scan if the driver supports it.
            # This is "Smart" mode: Check capability or Try/Except
            if hasattr(self.daq, 'write_waveform_scan'):
                try:
                    self.daq.write_waveform_scan(channel, data, int(self.sample_rate))
                    self._using_hardware_scan = True
                    return # Success!
                except Exception as e:
                    print(f"Hardware scan failed (fallback to software pacer): {e}")
                    self._using_hardware_scan = False
            
            # --- Attempt 2: Software Background Thread ---
            self._stop_event = threading.Event()
            self._output_thread = threading.Thread(target=self._generation_loop, args=(channel, data, self._stop_event))
            self._output_thread.daemon = True
            self._output_thread.start()
            
            # Note: We don't block here. The thread runs in background.
        else:
            # Output turned off.
            self._active_channels.discard(channel)
            
            # 1. Stop Hardware Scan
            if getattr(self, '_using_hardware_scan', False) and hasattr(self.daq, 'stop_output'):
                self.daq.stop_output()
                self._using_hardware_scan = False
                
            # 2. Stop Software Thread (already handled at top of function via Stop Event logic if running in parallel)
            # But we stopped it explicitly at start of this func.
            pass

    def _generation_loop(self, channel, data, stop_event):
        """
        Worker thread for software-paced generation.
        Uses drift correction to maintain average sample rate.
        """
        idx = 0
        modulus = len(data)
        
        # 1/SampleRate = time per point
        period = 1.0 / self.sample_rate 
        
        next_tick = time.perf_counter()
        
        while not stop_event.is_set():
            # 1. Output the point
            val = data[idx]
            try:
                self.daq.write_AO(channel, val)
            except Exception as e:
                print(f"Error in background generation: {e}")
                break
                
            idx = (idx + 1) % modulus
            
            # 2. Schedule next point
            next_tick += period
            now = time.perf_counter()
            sleep_duration = next_tick - now
            
            # 3. Sleep or Catch up
            if sleep_duration > 0:
                time.sleep(sleep_duration)
            else:
                # We are behind schedule (drift). 
                # If we are drastically behind (e.g. > 10 points), reset next_tick to avoid burst catch-up
                if sleep_duration < -10 * period:
                    next_tick = now # Reset schedule
                    # Maybe print a warning? "Sample rate too high for software pacing"

    def set_waveform(self, channel, waveform):
        params = self._get_params(channel)
        params['waveform'] = waveform
        self._update_if_active(channel)

    def set_frequency(self, channel, frequency):
        params = self._get_params(channel)
        params['frequency'] = frequency
        self._update_if_active(channel)
        
    def set_amplitude(self, channel, amplitude):
        params = self._get_params(channel)
        params['amplitude'] = amplitude
        self._update_if_active(channel)
        
    def set_offset(self, channel, offset):
        params = self._get_params(channel)
        params['offset'] = offset
        self._update_if_active(channel)

    # --- Waveform Type Specifics ---

    def set_square_duty_cycle(self, channel, duty_cycle):
        params = self._get_params(channel)
        params['duty_cycle'] = duty_cycle
        self._update_if_active(channel)

    def set_ramp_symmetry(self, channel, symmetry):
        params = self._get_params(channel)
        params['symmetry'] = symmetry
        self._update_if_active(channel)

    # --- Arbitrary Waveforms ---

    def _scale_waveform_data(self, data):
        """
        Helper to normalize waveform data to +/- 1.0.
        Mimics logic from k_81150a.py but targets float range [-1.0, 1.0].
        """
        data = np.array(data, dtype=float)
        max_abs = np.max(np.abs(data))
        
        if max_abs == 0:
            return data # All zeros
            
        # Scale to +/- 1.0
        scaled_data = data / max_abs
        return scaled_data

    def create_arb_waveform(self, channel, name, data):
        """
        Stores an arbitrary waveform data array.
        Data is normalized to +/- 1.0 upon creation.
        """
        scaled_data = self._scale_waveform_data(data)
        self._arb_waveforms[name] = scaled_data
        
    def set_arb_waveform(self, channel, name):
        """
        Selects the arbitrary waveform by name.
        """
        if name not in self._arb_waveforms:
            raise ValueError(f"Arbitrary waveform '{name}' not found. Create it first.")
        
        params = self._get_params(channel)
        params['waveform'] = 'USER'
        params['arb_name'] = name
        self._update_if_active(channel)

    # --- Synthesis ---

    def _synthesize_waveform(self, channel):
        """
        Generates the array of voltage values based on current settings.
        Returns a numpy array.
        """
        params = self._get_params(channel)
        freq = params['frequency']
        amp = params['amplitude'] # Vpp usually in AWGs, or Amplitude? AWG base says Vpp usually.
        # Let's assume Amplitude means Vpp for consistency with many drivers, or Vpeak?
        # Standard: Amplitude usually Vpp. So Peak is Amp/2.
        # CHECK awg.py docstring: "amplitude (float): ... (usually Vpp but use instrument default)"
        
        peak = amp / 2.0
        offset = params['offset']
        wf_type = params['waveform'].upper()
        
        # Generate one period or a stream? 
        # Typically DAQs want a buffer. If continuous, we might need N periods.
        # Let's generate 1 second worth of data or at least 1 period.
        # For efficiency, let's try to match 1000 points or something reasonable, 
        # or enough for 1 period if frequency is high.
        
        # Actually, to be safe, let's generate exactly 1 period if possible, 
        # or a large buffer if the DAQ loops it.
        # Let's assume the DAQ loops the buffer (common in functional generation mode).
        
        points_per_period = int(self.sample_rate / freq)
        if points_per_period < 2:
            print(f"Warning: Frequency {freq} too high for sample rate {self.sample_rate}. Nyquist violation.")
            points_per_period = 2 # Minimum to prevent crashes, but will be aliased
        
        t = np.linspace(0, 1/freq, points_per_period, endpoint=False)
        
        if wf_type == 'SIN':
            y = peak * np.sin(2 * np.pi * freq * t)
        elif wf_type in ['SQU', 'SQUARE', 'PULS', 'PULSE']:
            if wf_type in ['PULS', 'PULSE']:
                print("Log: PULS waveform not fully implemented for emulator; defaulting to SQU (Square wave).")
            from scipy import signal
            dc = params['duty_cycle'] / 100.0
            y = peak * signal.square(2 * np.pi * freq * t, duty=dc)
        elif wf_type == 'RAMP':
            from scipy import signal
            sym = params['symmetry'] / 100.0
            # Sawtooth in scipy: width=1 is rising ramp (symmetry 100?), width=0 is falling?
            # standard: symmetry 50% = triangle. 
            y = peak * signal.sawtooth(2 * np.pi * freq * t, width=sym)
        elif wf_type == 'DC':
            y = np.full_like(t, offset) # Just offset
            return y # Return early as we don't add offset again
        elif wf_type in ['NOIS', 'NOISE']:
            # Uniform noise between -peak and +peak
            y = np.random.uniform(-peak, peak, size=len(t))
        elif wf_type == 'USER':
            name = params.get('arb_name')
            if not name or name not in self._arb_waveforms:
                # Fallback if no arb selected
                print("Warning: USER waveform selected but no arb_name set. Defaulting to Zero.")
                return np.zeros_like(t) + offset
            
            arb_data = self._arb_waveforms[name]
            if len(arb_data) < 2:
                 return np.full_like(t, arb_data[0] if len(arb_data) > 0 else 0) * peak + offset
            
            # Resample arb_data to current t
            # arb_data is defined on domain [0, 1] (normalized index)
            # t is defined on [0, 1/freq).
            # We map t -> [0, 1) to sample arb_data.
            
            # Resample arb_data to current t using Zero-Order Hold (Nearest / Step)
            # This preserves sharp transitions matching typical AWG behavior.
            
            # Map [0, 1) target domain to [0, len) indices
            indices = (np.linspace(0, len(arb_data), len(t), endpoint=False)).astype(int)
            
            # Clamp indices just in case
            indices = np.clip(indices, 0, len(arb_data) - 1)
            
            y_base = arb_data[indices]
            
            # y_base is already normalized to +/- 1.0 by create_arb_waveform
            y = peak * y_base
        else:
            # Default to sine
            y = peak * np.sin(2 * np.pi * freq * t)
            
        return y + offset
