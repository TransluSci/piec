from .lockin import Lockin
from ..scpi import Scpi

"""
Fully AI generated, untested atm. Minor corrections on import statements.
"""
class SRS830(Lockin, Scpi):
    """
    Driver for the Stanford Research Systems SR830 DSP Lock-In Amplifier.

    This driver is based on the SR830 manual and inherits from a generic
    Lockin and SCPI class.
    """

    # Class attributes populated from the SR830 manual
    
    # The SR830 is a single-channel instrument in the context of signal input.
    channel = [1]
    
    # Reference source can be internal or external (FMOD command, page 5-4)
    reference_source = ['internal', 'external']
    
    # Internal reference frequency range (FREQ command, page 5-4)
    frequency = (0.001, 102000.0)
    
    # Detection harmonic range (HARM command, page 5-4)
    harmonic = (1, 19999)
    
    # Reference phase shift range (PHAS command, page 5-4)
    phase = (-180.0, 180.0)
    
    # Input configuration options (ISRC command, page 5-5)
    input_configuration = ['A', 'A-B', 'I (1M)', 'I (100M)']
    
    # Input coupling options (ICPL command, page 5-5)
    input_coupling = ['AC', 'DC']
    
    # Discrete sensitivity values in Volts (SENS command, page 5-6)
    sensitivity = [
        2e-9, 5e-9, 10e-9, 20e-9, 50e-9, 100e-9, 200e-9, 500e-9,
        1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6,
        1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 100e-3, 200e-3, 500e-3, 1.0
    ]
    
    # Line notch filter options (ILIN command, page 5-5)
    notch_filter = ['out', 'line', '2x_line', 'both']
    
    # Discrete time constant values in seconds (OFLT command, page 5-6)
    time_constant = [
        10e-6, 30e-6, 100e-6, 300e-6, 1e-3, 3e-3, 10e-3, 30e-3, 100e-3,
        300e-3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1e3, 3e3, 10e3, 30e3
    ]
    
    # Low-pass filter slope options in dB/octave (OFSL command, page 5-6)
    filter_slope = [6, 12, 18, 24]


    def set_reference_source(self, reference_source):
        """
        Sets the reference source for the lockin. (FMOD command, page 5-4)

        Args:
            reference_source (str): The source of the reference signal ('internal' or 'external').
        """
        source_map = {'internal': 1, 'external': 0}
        if reference_source not in source_map:
            raise ValueError(f"Invalid reference source. Must be one of {list(source_map.keys())}")
        self.write(f"FMOD {source_map[reference_source]}")
    
    def set_reference_frequency(self, frequency):
        """
        Sets the reference frequency for the lockin (if internal reference). (FREQ command, page 5-4)

        Args:
            frequency (float): The frequency in Hz.
        """
        if not self.frequency[0] <= frequency <= self.frequency[1]:
             raise ValueError(f"Frequency out of range. Must be between {self.frequency[0]} and {self.frequency[1]} Hz.")
        self.write(f"FREQ {frequency}")

    def set_harmonic(self, harmonic):
        """
        Sets the detection harmonic for the lockin. (HARM command, page 5-4)

        Args:
            harmonic (int): The harmonic number to lock onto.
        """
        if not self.harmonic[0] <= harmonic <= self.harmonic[1]:
            raise ValueError(f"Harmonic out of range. Must be between {self.harmonic[0]} and {self.harmonic[1]}.")
        self.write(f"HARM {harmonic}")

    def set_phase(self, phase):
        """
        Sets the reference phase for the lockin. (PHAS command, page 5-4)

        Args:
            phase (float): The phase offset in degrees.
        """
        if not self.phase[0] <= phase <= self.phase[1]:
             raise ValueError(f"Phase out of range. Must be between {self.phase[0]} and {self.phase[1]} degrees.")
        self.write(f"PHAS {phase}")

    def set_input_configuration(self, configuration):
        """
        Sets the input configuration for the lockin. (ISRC command, page 5-5)

        Args:
            configuration (str): The input configuration type ('A', 'A-B', etc.).
        """
        config_map = {'A': 0, 'A-B': 1, 'I (1M)': 2, 'I (100M)': 3}
        if configuration not in config_map:
            raise ValueError(f"Invalid input configuration. Must be one of {list(config_map.keys())}")
        self.write(f"ISRC {config_map[configuration]}")

    def set_input_coupling(self, coupling):
        """
        Sets the input coupling for the lockin. (ICPL command, page 5-5)

        Args:
            coupling (str): The input coupling type ('AC' or 'DC').
        """
        coupling_map = {'AC': 0, 'DC': 1}
        if coupling not in coupling_map:
            raise ValueError(f"Invalid input coupling. Must be one of {list(coupling_map.keys())}")
        self.write(f"ICPL {coupling_map[coupling]}")

    def set_sensitivity(self, sensitivity_value):
        """
        Sets the sensitivity for the lockin. (SENS command, page 5-6)

        Args:
            sensitivity_value (float): The sensitivity level in Volts/Amp.
        """
        try:
            index = self.sensitivity.index(sensitivity_value)
            self.write(f"SENS {index}")
        except ValueError:
            raise ValueError(f"Invalid sensitivity value. Please choose from the available list: {self.sensitivity}")

    def set_notch_filter(self, notch_filter):
        """
        Sets the line notch filter for the lockin. (ILIN command, page 5-5)

        Args:
            notch_filter (str): The notch filter setting ('out', 'line', '2x_line', 'both').
        """
        filter_map = {'out': 0, 'line': 1, '2x_line': 2, 'both': 3}
        if notch_filter not in filter_map:
             raise ValueError(f"Invalid notch filter setting. Must be one of {list(filter_map.keys())}")
        self.write(f"ILIN {filter_map[notch_filter]}")

    def set_time_constant(self, time_constant_value):
        """
        Sets the time constant for the lockin's low-pass filter. (OFLT command, page 5-6)

        Args:
            time_constant_value (float): The time constant value in seconds.
        """
        try:
            index = self.time_constant.index(time_constant_value)
            self.write(f"OFLT {index}")
        except ValueError:
            raise ValueError(f"Invalid time constant. Please choose from the available list: {self.time_constant}")

    def set_filter_slope(self, filter_slope_value):
        """
        Sets the filter slope for the lockin. (OFSL command, page 5-6)

        Args:
            filter_slope_value (int): The slope of the filter in dB/octave (6, 12, 18, 24).
        """
        slope_map = {6: 0, 12: 1, 18: 2, 24: 3}
        if filter_slope_value not in slope_map:
            raise ValueError(f"Invalid filter slope. Must be one of {list(slope_map.keys())}")
        self.write(f"OFSL {slope_map[filter_slope_value]}")

    def quick_read(self):
        """
        Quickly reads the default data (X and Y). (SNAP? command, page 5-15)

        Returns:
            tuple: (X, Y) data from the lockin as floats.
        """
        response = self.query("SNAP? 1,2")
        values = [float(v) for v in response.strip().split(',')]
        return tuple(values)

    def read_data(self):
        """
        Reads the primary lockin data: X, Y, R, and Theta. (SNAP? command, page 5-15)

        Returns:
            dict: A dictionary with keys 'X', 'Y', 'R', and 'Theta'.
        """
        response = self.query("SNAP? 1,2,3,4")
        values = [float(v) for v in response.strip().split(',')]
        return {'X': values[0], 'Y': values[1], 'R': values[2], 'Theta': values[3]}

    def get_X(self):
        """
        Reads the X (in-phase) component. (OUTP? 1, page 5-15)

        Returns:
            float: The X data from the lockin.
        """
        return float(self.query("OUTP? 1"))

    def get_Y(self):
        """
        Reads the Y (quadrature) component. (OUTP? 2, page 5-15)

        Returns:
            float: The Y data from the lockin.
        """
        return float(self.query("OUTP? 2"))

    def get_R(self):
        """
        Reads the R (magnitude) data. (OUTP? 3, page 5-15)

        Returns:
            float: The R data from the lockin.
        """
        return float(self.query("OUTP? 3"))

    def get_theta(self):
        """
        Reads the Theta (phase) data. (OUTP? 4, page 5-15)

        Returns:
            float: The Theta data from the lockin.
        """
        return float(self.query("OUTP? 4"))

    def auto_gain(self):
        """
        Performs the Auto Gain function to set sensitivity. (AGAN command, page 5-11)
        """
        self.write("AGAN")

    def auto_phase(self):
        """
        Performs the Auto Phase function to set the reference phase to zero. (APHS command, page 5-11)
        """
        self.write("APHS")

