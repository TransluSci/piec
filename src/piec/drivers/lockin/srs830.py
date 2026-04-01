"""
Driver for the Stanford Research Systems SR830 DSP Lock-In Amplifier.

This class inherits from the base Lockin class and SCPI class
and fills in the instrument-specific attributes and methods based
on the SR830 manual.
"""
import re
from .lockin import Lockin
from ..scpi import Scpi

class SRS830(Lockin, Scpi):
    """
    Driver for the SRS830 Lock-In Amplifier.
    
    Implements the methods defined in the parent Lockin class
    using SR830-specific SCPI commands.
    """

    AUTODETECT_ID = "SR830"
    channel = [1]
    input_coupling = ["AC", "DC"]
    reference_source = ["internal", "external"]
    frequency = {
        'reference_source': {
            'internal': (0.001, 102000.0),
            'external': (0.001, 102000.0)
        }
    }
    harmonic = (1, 19999)
    phase = (-360.0, 729.99)
    input_configuration = ["A", "A-B", "I (1M)", "I (100M)"]

    _sensitivity_v = [
        2e-9, 5e-9, 10e-9, 20e-9, 50e-9, 100e-9, 200e-9, 500e-9,
        1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6, 200e-6, 500e-6,
        1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3, 100e-3, 200e-3, 500e-3, 1.0
    ]
    _sensitivity_i = [
        2e-15, 5e-15, 10e-15, 20e-15, 50e-15, 100e-15, 200e-15, 500e-15,
        1e-12, 2e-12, 5e-12, 10e-12, 20e-12, 50e-12, 100e-12, 200e-12, 500e-12,
        1e-9, 2e-9, 5e-9, 10e-9, 20e-9, 50e-9, 100e-9, 200e-9, 500e-9, 1e-6
    ]
    
    sensitivity = {
        'input_configuration': {
            "A": _sensitivity_v,
            "A-B": _sensitivity_v,
            "I (1M)": _sensitivity_i,
            "I (100M)": _sensitivity_i
        }
    }
    notch_filter = ["Out", "Line", "2xLine", "Both"]
    time_constant = [
        10e-6, 30e-6, 100e-6, 300e-6,
        1e-3, 3e-3, 10e-3, 30e-3, 100e-3, 300e-3,
        1.0, 3.0, 10.0, 30.0,
        100.0, 300.0,
        1e3, 3e3, 10e3, 30e3
    ]
    filter_slope = [6, 12, 18, 24]

    def __init__(self, *args, **kwargs):
        """
        Initializes the SR830 driver.
        """
        super().__init__(*args, **kwargs)
        
        try:
            config_idx = int(self.instrument.query("ISRC?"))
            self._current_input_config = self.input_configuration[config_idx]
        except Exception:
            self._current_input_config = "A" # Default
            print("Warning: Could not query initial input config. Defaulting to 'A'.")

        # Create maps for convenient string-to-int conversion
        self._ref_src_map = {s.lower(): i for i, s in enumerate(self.reference_source, 0)}
        self._ref_src_map_inv = {i: s for s, i in self._ref_src_map.items()}
        
        self._in_config_map = {s.lower(): i for i, s in enumerate(self.input_configuration, 0)}
        self._in_config_map_inv = {i: s for s, i in self._in_config_map.items()}

        self._in_couple_map = {s.lower(): i for i, s in enumerate(self.input_coupling, 0)}
        self._in_couple_map_inv = {i: s for s, i in self._in_couple_map.items()}

        self._notch_map = {s.lower(): i for i, s in enumerate(self.notch_filter, 0)}
        self._notch_map_inv = {i: s for s, i in self._notch_map.items()}

        self._slope_map = {val: i for i, val in enumerate(self.filter_slope, 0)}
        self._slope_map_inv = {i: val for val, i in self._slope_map.items()}

        self._tc_map = {val: i for i, val in enumerate(self.time_constant, 0)}
        self._tc_map_inv = {i: val for val, i in self._tc_map.items()}

        self._sens_v_map = {val: i for i, val in enumerate(self._sensitivity_v, 0)}
        self._sens_i_map = {val: i for i, val in enumerate(self._sensitivity_i, 0)}

    def set_amplitude(self, amplitude: float):
        """
        Sets the sine out amplitude.
        SCPI Command: SLVL {f}
        """
        self.instrument.write(f"SLVL {amplitude}")

    def set_reference_source(self, reference_source: str):
        """
        Sets the reference source for the lockin.
        SCPI Command: FMOD {i}
        """
        ref_str = reference_source.lower().strip()
        if ref_str not in self._ref_src_map:
            raise ValueError(f"Invalid reference_source. Must be one of: {self.reference_source}")
        
        i = self._ref_src_map[ref_str]
        self.instrument.write(f"FMOD {i}")

    def set_reference_frequency(self, frequency: float):
        """
        Sets the reference frequency for the lockin.
        SCPI Command: FREQ {f}
        """
        min_f, max_f = self.frequency['reference_source']['internal']
        if not (min_f <= frequency <= max_f):
            raise ValueError(f"Frequency {frequency} Hz out of range ({min_f} Hz to {max_f} Hz)")
        self.instrument.write(f"FREQ {frequency}")

    def set_harmonic(self, harmonic: int):
        """
        Sets the detection harmonic.
        SCPI Command: HARM {i}
        """
        min_h, max_h = self.harmonic
        if not (min_h <= harmonic <= max_h):
             raise ValueError(f"Harmonic {harmonic} out of range ({min_h} to {max_h})")
        self.instrument.write(f"HARM {harmonic}")

    def set_phase(self, phase: float):
        """
        Sets the reference phase shift.
        SCPI Command: PHAS {x}
        """
        self.instrument.write(f"PHAS {phase}")

    def set_input_configuration(self, configuration: str):
        """
        Sets the input configuration (A, A-B, I (1M), I (100M)).
        SCPI Command: ISRC {i}
        """
        config_str = configuration.lower().strip()
        if config_str not in self._in_config_map:
            raise ValueError(f"Invalid configuration '{configuration}'. Must be one of: {self.input_configuration}")
        
        i = self._in_config_map[config_str]
        self.instrument.write(f"ISRC {i}")
        # Keep internal state consistent with the actual mapping
        self._current_input_config = self.input_configuration[i]

    def set_input_coupling(self, coupling: str):
        """
        Sets the input coupling (AC or DC).
        SCPI Command: ICPL {i}
        """
        coup_str = coupling.lower().strip()
        if coup_str not in self._in_couple_map:
            raise ValueError(f"Invalid coupling. Must be one of: {self.input_coupling}")
        i = self._in_couple_map[coup_str]
        self.instrument.write(f"ICPL {i}")

    def set_sensitivity(self, sensitivity):
        """
        Sets the sensitivity. Supports float values or strings (e.g., '50uv/pa').
        SCPI Command: SENS {i}
        """
        if isinstance(sensitivity, str):
            sensitivity = self._convert_sensitivity(sensitivity)

        if self._current_input_config.startswith("I"):
            sens_map = self._sens_i_map
            valid_vals = self._sensitivity_i
        else:
            sens_map = self._sens_v_map
            valid_vals = self._sensitivity_v
            
        # Robust key matching for float sensitivity
        closest_key = min(sens_map.keys(), key=lambda k: abs(k - sensitivity))
        if abs(closest_key - sensitivity) / (closest_key or 1) > 1e-4:
            raise ValueError(f"Invalid sensitivity {sensitivity}. Valid values: {valid_vals}")
        
        i = sens_map[closest_key]
        self.instrument.write(f"SENS {i}")

    def _convert_sensitivity(self, sens_str):
        """
        Converts sensitivity strings (e.g., '50uv/pa') to float.
        """
        sens_str = sens_str.lower().strip()
        if sens_str == 'auto':
            return 'auto'
        
        match = re.match(r'([0-9.]+)([a-z/]+)', sens_str)
        if not match:
            raise ValueError(f"Could not parse sensitivity string: {sens_str}")
        
        num = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {
            'nv': 1e-9, 'uv': 1e-6, 'mv': 1e-3, 'v': 1.0,
            'fa': 1e-15, 'pa': 1e-12, 'na': 1e-9, 'ua': 1e-6, 'ma': 1e-3, 'a': 1.0
        }
        
        prefix_match = re.match(r'[a-z]+', unit)
        if not prefix_match:
             raise ValueError(f"Unknown unit format: {unit}")
        
        prefix = prefix_match.group(0)
        if prefix in multipliers:
            return num * multipliers[prefix]
        
        raise ValueError(f"Unknown unit prefix: {prefix}")

    def set_notch_filter(self, notch_filter: str):
        """
        Sets the line notch filter mode.
        SCPI Command: ILIN {i}
        """
        notch_str = notch_filter.lower().strip()
        if notch_str not in self._notch_map:
            raise ValueError(f"Invalid notch_filter. Must be one of: {self.notch_filter}")
        i = self._notch_map[notch_str]
        self.instrument.write(f"ILIN {i}")

    def set_time_constant(self, time_constant: float):
        """
        Sets the low pass filter time constant.
        SCPI Command: OFLT {i}
        """
        if time_constant not in self._tc_map:
            raise ValueError(f"Invalid time_constant. Must be one of: {self.time_constant}")
        i = self._tc_map[time_constant]
        self.instrument.write(f"OFLT {i}")

    def set_filter_slope(self, filter_slope: int):
        """
        Sets the low pass filter slope.
        SCPI Command: OFSL {i}
        """
        if filter_slope not in self._slope_map:
            raise ValueError(f"Invalid filter_slope. Must be one of: {self.filter_slope}")
        i = self._slope_map[filter_slope]
        self.instrument.write(f"OFSL {i}")

    def quick_read(self) -> tuple[float, float]:
        """
        Quick read (X, Y).
        SCPI Command: SNAP? 1,2
        """
        response = self.instrument.query("SNAP? 1,2")
        x_str, y_str = response.split(',')
        return (float(x_str), float(y_str))

    def read_data(self) -> dict[str, float]:
        """
        Reads X, Y, R, and Theta.
        SCPI Command: SNAP? 1,2,3,4
        """
        response = self.instrument.query("SNAP? 1,2,3,4")
        x_str, y_str, r_str, t_str = response.split(',')
        return {'X': float(x_str), 'Y': float(y_str), 'R': float(r_str), 'Theta': float(t_str)}

    def get_X(self) -> float:
        return float(self.instrument.query("OUTP? 1"))

    def get_Y(self) -> float:
        return float(self.instrument.query("OUTP? 2"))

    def get_R(self) -> float:
        return float(self.instrument.query("OUTP? 3"))

    def get_theta(self) -> float:
        return float(self.instrument.query("OUTP? 4"))

    def auto_gain(self):
        self.instrument.write("AGAN")

    def auto_phase(self):
        self.instrument.write("APHS")