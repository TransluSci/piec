import numpy as np
import time
import pandas as pd
import matplotlib.pyplot as plt
from piec.analysis.utilities import *
from piec.analysis.pund import *
from piec.analysis.hysteresis import *

class DiscreteWaveform:
    """
    Parent class for managing discrete waveform generation and measurement experiments.

    Provides core functionality for configuring Arbitrary Waveform Generator (awg)
    and oscilloscope (osc), capturing waveforms, saving data, and running analysis
    on captured waveforms. Designed to be subclassed for specific measurement types.
    Currently implemented subclasses are Hysteresis and ThreePulsePUND.

    Attributes:
        :awg (visa.Resource): AWG instrument object (REQUIRED)
        :osc (visa.Resource): Oscilloscope instrument object (REQUIRED)
        :v_div (float): Oscilloscope vertical scale in volts/division
        :voltage_channel (str): AWG channel used for voltage output
        :save_dir (str): Directory path for data storage
        :filename (str): Name of saved data file
        :data (pd.DataFrame): Captured waveform data (time and voltage)
        :metadata (pd.DataFrame): Measurement parameters and metadata
    """
    mtype = None
    length = None
    filename = None
    data = None

    def __init__(self, awg, osc, v_div=0.01, voltage_channel='1', save_dir=r'\\scratch'):
        """Initialize core waveform measurement system.

        Args:
            :awg: VISA address or initialized AWG object
            :osc: VISA address or initialized oscilloscope object
            :v_div: Oscilloscope vertical sensitivity (volts/division)
            :voltage_channel: AWG channel number for voltage output (default '1')
            :save_dir: Data storage directory path (default network scratch)
        """

        self.v_div = v_div
        self.awg = awg
        self.osc = osc
        self.voltage_channel = voltage_channel
        self.save_dir = save_dir
        self.history = []
        self._update_metadata()

    def _update_metadata(self):
        """
        Update metadata DataFrame with current measurement parameters.
        
        Captures instrument IDs, measurement type, and timestamp.
        Should be called after any parameter changes or before saving data.
        """
        params = {key: value for key, value in self.__dict__.items() 
                if not key.startswith('_') and 
                not callable(value) and
                key not in ['awg', 'osc', 'data', 'metadata', 'history']}
        
        self.metadata = pd.DataFrame(params, index=[0])

        # Other info
        self.metadata['mtype'] = self.mtype
        self.metadata['awg'] = self.awg.idn()
        self.metadata['osc'] = self.osc.idn()
        if hasattr(self, 'length'):
            self.metadata['length'] = self.length
        self.metadata['timestamp'] = time.time()
        self.metadata['processed'] = False

    def _update_notes(self):
        """
        Does nothing, overwrite in child class if you want to change the name of the saved file with each parameter change.
        """
        pass

    def _update_history(self):
        """
        Does nothing, overwrite in child class if you want to change the name of the saved file with each parameter change.
        """
        self.history.append(self.metadata.copy())

    def initialize_awg(self):
        """
        Configure basic AWG settings for waveform generation.
        
        Sets up impedance matching (50Ω), and manual triggering.
        Should be called before any waveform-specific configuration.
        """
        self.awg.initialize()
        self.awg.set_load_impedance(channel=int(self.voltage_channel), load_impedance=50)
        self.awg.set_trigger_source(channel=int(self.voltage_channel), trigger_source='MAN')

    def configure_oscilloscope(self, channel = 1):
        """
        Set up oscilloscope for waveform capture.
        
        Configures timebase, triggering, and channel settings optimized for
        capturing the generated waveform. Uses external triggering.

        Args:
            :channel: Oscilloscope channel to configure (default 1)
        """
        self.osc.initialize()
        self.osc.configure_horizontal(tdiv=self.length/8, x_position=5*(self.length/10))
        self.osc.set_vertical_scale(channel=channel, vdiv=float(self.v_div))
        self.osc.set_trigger_source(trigger_source='EXT')
        self.osc.set_trigger_level(trigger_level=0.95) # Using the old high_level value
        self.osc.set_trigger_sweep(trigger_sweep='NORM')
        self.osc.set_channel_impedance(channel, channel_impedance='50')
        # configure_trigger_edge call removed as functionality is now in the calls above.

    def configure_awg(self):
        """
        Placeholder for waveform-specific AWG configuration.
        
        Raises:
            :AttributeError: If not implemented in child class
        """
        raise AttributeError("configure_awg() must be defined in the child class specific to a waveform")

    def apply_and_capture_waveform(self):
        """
        Execute waveform generation and data acquisition sequence.
        
        Coordinates instrument triggering, captures time-voltage data from oscilloscope,
        and stores results in self.data attribute (pandas DataFrame object). Includes instrument synchronization.
        """
        print(f"Capturing waveform of type {self.mtype} for {self.length} seconds...")
        self.osc.arm()
        self.awg.output(channel=int(self.voltage_channel), on=True)
        self.awg.output_trigger()
        
        # New driver lacks a blocking operation complete query.
        # Wait for a duration slightly longer than the waveform to ensure capture.
        time.sleep(self.length * 1.2)
        
        self.osc.set_acquisition_channel(channel=1) # Setup waveform source
        
        # New driver returns a structured DataFrame
        df = self.osc.get_data()
        self.data = pd.DataFrame({"time (s)": df['Time'], "voltage (V)": df['Voltage']}) # Store data
        print("Waveform captured.")

    def save_waveform(self):
        """
        Save captured waveform data to CSV file.
        
        Uses meaurement type and notes to generate filename.
        Requires successful waveform capture prior to calling (self.data must not be None).
        """
        self._update_metadata()
        self._update_notes()

        if self.data is not None:
            self.filename = create_measurement_filename(self.save_dir, self.mtype, self.notes)
            metadata_and_data_to_csv(self.metadata, self.data, self.filename)
            print(f"Waveform data saved to {self.filename}")
        else:
            print("No data to save. Capture the waveform first.")

    def analyze(self):
        """
        Placeholder for measurement-specific analysis.
        
        Intended for post-processing of captured data. Child classes should
        implement analysis routines for their specific measurement type.
        """
        if self.data is not None:
            print(f"Analysis method not defined. Not changing {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")
        
    def run_experiment(self):
        """
        Execute complete measurement workflow.
        
        Standard sequence:
        1. Configure oscilloscope
        2. Initialize AWG
        3. Apply waveform-specific configuration
        4. Capture waveform data
        5. Save results
        6. Perform analysis
        7. Update history with metadata
        """
        print(f"Running experiment for {self.mtype} measurement...")
        self.configure_oscilloscope()
        print("Oscilloscope configured.")
        self.initialize_awg()
        print("AWG initialized.")
        self.configure_awg()
        print("AWG configured.")
        self.apply_and_capture_waveform()
        print("Waveform applied and captured.")
        self.save_waveform()
        print("Waveform saved.")
        self.analyze()
        print("Analysis complete.")
        self._update_history()
        print("Experiment complete.")

### SPECIFIC WAVEFORM MEASURMENT CLASSES ###

class HysteresisLoop(DiscreteWaveform):
    """
    Hysteresis loop measurement using triangular excitation waveform.
    
    Specializes DiscreteWaveform for ferroelectric hysteresis measurements.
    Generates bipolar triangle waves and analyzes polarization-voltage loops.

    Attributes:
        :type (str): Measurement type identifier ('hysteresis')
        :frequency (float): Excitation frequency in Hz
        :amplitude (float): Peak voltage amplitude in volts
        :n_cycles (int): Number of waveform cycles to capture
        :area (float): Capacitor area for polarization calculation (m²)
        :show_plots (bool): Display interactive plots flag
        :save_plots (bool): Save plot images flag
    """

    mtype = "hysteresis"

    def __init__(self, awg=None, osc=None, v_div=0.1, frequency=1000.0, amplitude=1.0, offset=0.0,
                 n_cycles=2, voltage_channel:str='1', area=1.0e-5, time_offset=1e-8,
                 show_plots=False, save_plots=True, auto_timeshift=False,
                 save_dir=r'\\scratch'):
        """
        Initialize hysteresis measurement parameters.

        Args:
            :frequency: Triangle wave frequency (1-1000 Hz typical)
            :amplitude: Peak-to-peak voltage amplitude (V)
            :offset: DC voltage offset (V)
            :n_cycles: Number of complete bipolar cycles
            :area: Device capacitor area for polarization calc (m²)
            :time_offset: Manual trigger-capture time alignment (s)
            :show_plots: Show matplotlib plots post analysis?
            :save_plots: Save analysis plots to disk?
            :auto_timeshift: Try to automatically determine t0 of captured waveform - t0 of trigger waveform?
        """
        self.length = 1/frequency
        self.frequency = frequency
        self.amplitude = amplitude
        self.offset = offset
        self.n_cycles = n_cycles
        self.area = area
        self.time_offset = time_offset
        self.voltage_channel = voltage_channel
        self.show_plots = show_plots
        self.save_plots = save_plots
        self.auto_timeshift = auto_timeshift
        super().__init__(awg, osc, v_div, voltage_channel, save_dir)

    def _update_notes(self):
        self.notes = str(self.amplitude).replace('.', 'p')+'V_'+str(int(self.frequency))+'Hz'

    def analyze(self):
        """
        Process hysteresis data and calculate polarization parameters.
        
        Performs time alignment, integration for polarization calculation,
        and generates hysteresis loop plots. Results appended to CSV.
        """
        if self.data is not None:
            process_raw_hyst(self.filename, show_plots=self.show_plots, save_plots=self.save_plots, auto_timeshift=self.auto_timeshift)
            print(f"Analysis succeeded, updated {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")

    def configure_awg(self):
        """
        Generate AWG triangle waveform for hysteresis measurement.
        
        Creates multi-cycle bipolar triangle wave with specified parameters.
        """
        interp_v_array = [0,1,0,-1,0]+([1,0,-1,0]*((self.n_cycles)-1))

        n_points = self.awg.arb_data_range[1] # Use attribute for max points
        dense = interpolate_sparse_to_dense(np.linspace(0,len(interp_v_array),len(interp_v_array)), interp_v_array, total_points=n_points)

        # Create the arbitrary waveform in the AWG's volatile memory
        self.awg.create_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE", data=dense)
        
        # Configure the AWG output using the specific methods
        invert = self.amplitude < 0
        polarity = "INV" if invert else "NORM"
        
        self.awg.set_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE")
        # Vpp = amplitude*2
        self.awg.set_amplitude(channel=int(self.voltage_channel), amplitude=abs(self.amplitude) * 2)
        self.awg.set_offset(channel=int(self.voltage_channel), offset=self.offset)
        self.awg.set_frequency(channel=int(self.voltage_channel), frequency=self.frequency)
        self.awg.set_polarity(channel=int(self.voltage_channel), polarity=polarity)

class ThreePulsePund(DiscreteWaveform):
    """
    PUND (Positive-Up-Negative-Down) pulse measurement system.
    
    Implements 3-pulse sequence for ferroelectric capacitor characterization:
    Reset + Positive (P) + Up (U) (arbitrary polarity) pulses with delay intervals.
    Measures difference in switching currents between P and U pulse responses to
    calculate remanent polarization.

    Attributes:
        :type (str): Measurement type identifier ('3pulsepund')
        :reset_amp (float): Reset pulse amplitude (V)
        :p_u_amp (float): Measurement pulse amplitude (V)
        :reset_width (float): Reset pulse duration (s)
        :p_u_width (float): Measurement pulse duration (s)
    """
    mtype = "3pulsepund"

    def __init__(self, awg=None, osc=None, v_div=0.1,
                 reset_amp=1, reset_width=1e-3, reset_delay=1e-3,
                 p_u_amp=1, p_u_width=1e-3, p_u_delay=1e-3,
                 offset=0, voltage_channel:str='1', area=1e-5, time_offset=1e-8,
                 show_plots=False, save_plots=True, auto_timeshift=True,
                 save_dir=r'\\scratch'):
        """Initialize PUND pulse parameters.

        Args:
            :reset_amp: Reset pulse amplitude (V)
            :reset_width: Reset pulse duration (s)
            :reset_delay: Post-reset delay (s)
            :p_u_amp: Measurement pulse amplitude (V)
            :p_u_width: Measurement pulse duration (s)
            :p_u_delay: Inter-pulse delay (s)
            :area: Capacitor area for polarization calc (m²)
            :time_offset: Manual trigger-capture time alignment (s)
            :show_plots: Show matplotlib plots post analysis?
            :save_plots: Save analysis plots to disk?
            :auto_timeshift: Try to automatically determine t0 of captured waveform - t0 of trigger waveform?
        """
        self.reset_amp = reset_amp
        self.reset_width = reset_width
        self.reset_delay = reset_delay
        self.p_u_amp = p_u_amp
        self.p_u_width = p_u_width
        self.p_u_delay = p_u_delay
        self.offset = offset
        self.area = area
        self.voltage_channel = voltage_channel
        self.time_offset = time_offset
        self.show_plots = show_plots
        self.save_plots = save_plots
        self.auto_timeshift = auto_timeshift
        self.length = (reset_width+(reset_delay)+(2*p_u_width)+(2*p_u_delay))
        super().__init__(awg, osc, v_div, voltage_channel, save_dir)

    def _update_notes(self):
        self.notes = str(self.reset_amp).replace('.', 'p')+'Vres_'+str(self.p_u_amp).replace('.', 'p')+'Vpu'

    def analyze(self):
        """
        Analyze PUND data to calculate switching polarization.
        
        Processes current transients, integrates charge, and calculates
        switched charge values. Generates time-domain and polarization plots.
        """
        if self.data is not None:
            process_raw_3pp(self.filename, show_plots=self.show_plots, save_plots=self.save_plots, auto_timeshift=self.auto_timeshift)
            print(f"Analysis succeeded, updated {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")

    def configure_awg(self):
        """
        Generate PUND pulse waveform for AWG output.
        
        Constructs pulse sequence with specified amplitudes and timing.
        Automatically scales pulses to AWG voltage range.
        """
        # calculate time steps for voltage trace
        times = [0, self.reset_width, self.reset_delay, self.p_u_width, self.p_u_delay, self.p_u_width, self.p_u_delay,]
        sum_times = [sum(times[:i+1]) for i, t in enumerate(times)]
        # calculate full amplitude of pulse profile (Vpp)
        amplitude = abs(self.reset_amp) + abs(self.p_u_amp)
        
        polarity = np.sign(self.p_u_amp)

        # specify sparse t and v coordinates which define PUND pulse train
        # The fractional amplitudes are calculated within interpolate_sparse_to_dense if needed,
        # but here we build the final shape before scaling to DAC values.
        frac_reset_amp = self.reset_amp/amplitude
        frac_p_u_amp = self.p_u_amp/amplitude

        sparse_t = np.array([sum_times[0], sum_times[1], sum_times[1], sum_times[2], sum_times[2], sum_times[3], sum_times[3],
                                sum_times[4], sum_times[4], sum_times[5], sum_times[5], sum_times[6],])
        sparse_v = np.array([-abs(frac_reset_amp), -abs(frac_reset_amp), 0, 0, abs(frac_p_u_amp), abs(frac_p_u_amp), 0, 0,
                             abs(frac_p_u_amp), abs(frac_p_u_amp), 0, 0,]) * polarity
        
        n_points = self.awg.arb_data_range[1] # n points to use is max

        # densify the array
        dense_v = interpolate_sparse_to_dense(sparse_t, sparse_v, total_points=n_points)
        
        # write to awg
        self.awg.create_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE", data=dense_v)
        
        # Configure the AWG output using the specific methods
        self.awg.set_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE")
        self.awg.set_offset(channel=int(self.voltage_channel), offset=self.offset)
        self.awg.set_amplitude(channel=int(self.voltage_channel), amplitude=abs(amplitude))
        self.awg.set_frequency(channel=int(self.voltage_channel), frequency=1/self.length)
        print("AWG configured for a PUND pulse.")