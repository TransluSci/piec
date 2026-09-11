from piec.drivers.lockin.lockin import Lockin
from piec.drivers.virtual_instrument import VirtualInstrument

class VirtualLockin(VirtualInstrument, Lockin):
    """
    Virtual version of a Lock-in that returns data based on a shared magnetic sample.
    """
    def __init__(self, address="VIRTUAL", *, excitation_current=1e-6, **kwargs):
        """The fallback simulated circuit declares a 1 uA drive; this is not a measured current."""
        import math
        if not math.isfinite(excitation_current):
            raise ValueError("excitation_current must be finite")
        self.excitation_current = float(excitation_current)
        super().__init__(address=address, **kwargs)

    def idn(self):
        return "Virtual Lock-in"

    def initialize(self):
        """Mock initialize from Scpi."""
        pass
    
    def configure_reference(self, **kwargs): pass
    def configure_input(self, **kwargs): pass
    def configure_gain_filters(self, **kwargs): pass

    def quick_read(self) -> tuple[float, float]:
        """
        Simulation of SNAP? 1,2
        """
        if hasattr(self, 'mag_sample') and self.mag_sample:
            return self.mag_sample.get_voltage_response(excitation_current=self.excitation_current)
        return (0.0001, 0.0002)

    def read_data(self) -> dict[str, float]:
        """
        Simulation of SNAP? 1,2,3,4
        """
        x, y = self.quick_read()
        r = (x**2 + y**2)**0.5
        theta = 0.0 # simplified
        return {'X': x, 'Y': y, 'R': r, 'Theta': theta}

    def get_X(self) -> float:
        x, _ = self.quick_read()
        return x

    def get_Y(self) -> float:
        _, y = self.quick_read()
        return y
