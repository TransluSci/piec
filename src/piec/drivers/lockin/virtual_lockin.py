from piec.drivers.lockin.lockin import Lockin
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualLockin(VirtualInstrument, Lockin):
    """
    Virtual version of a Lock-in that returns data based on a shared magnetic sample.
    """

    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
        self.state = {
            'amplitude': 1.0,
            'reference_source': 'INT',
            'frequency': 1000.0,
            'harmonic': 1,
            'phase': 0.0,
            'input_configuration': 'A',
            'input_coupling': 'AC',
            'sensitivity': 1.0,
            'notch_filter': 0,
            'time_constant': 0.1,
            'filter_slope': 12,
        }

    def idn(self):
        return "Virtual Lock-in"

    def set_amplitude(self, amplitude):
        self.state['amplitude'] = amplitude

    def set_reference_source(self, reference_source):
        self.state['reference_source'] = reference_source

    def set_reference_frequency(self, frequency):
        self.state['frequency'] = frequency

    def set_harmonic(self, harmonic):
        self.state['harmonic'] = harmonic

    def set_phase(self, phase):
        self.state['phase'] = phase

    def set_input_configuration(self, configuration):
        self.state['input_configuration'] = configuration

    def set_input_coupling(self, coupling):
        self.state['input_coupling'] = coupling

    def set_sensitivity(self, sensitivity):
        self.state['sensitivity'] = sensitivity

    def set_notch_filter(self, notch_filter):
        self.state['notch_filter'] = notch_filter

    def set_time_constant(self, time_constant):
        self.state['time_constant'] = time_constant

    def set_filter_slope(self, filter_slope):
        self.state['filter_slope'] = filter_slope

    def auto_gain(self):
        self.state['sensitivity'] = 0.1

    def auto_phase(self):
        self.state['phase'] = 0.0

    def read_data(self) -> dict[str, float]:
        """Simulation of SNAP? 1,2,3,4"""
        if self.sample is not None:
            x = float(self.sample.get_resistance()) * 1e-6
            y = x / 10.0
        else:
            x, y = 0.0001, 0.0002
        r = (x**2 + y**2)**0.5
        theta = float(self.state.get('phase', 0.0))
        return {'X': x, 'Y': y, 'R': r, 'Theta': theta}

    def get_X(self) -> float:
        return self.read_data()['X']

    def get_Y(self) -> float:
        return self.read_data()['Y']

    def get_R(self) -> float:
        return self.read_data()['R']

    def get_theta(self) -> float:
        return self.read_data()['Theta']
