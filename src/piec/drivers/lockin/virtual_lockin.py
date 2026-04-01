from piec.drivers.lockin.lockin import Lockin
from piec.drivers.virtual_instrument import VirtualInstrument

class VirtualLockin(VirtualInstrument, Lockin):
    """
    Virtual version of a Lock-in that returns data based on a shared magnetic sample.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        VirtualInstrument.__init__(self, address=address)
        Lockin.__init__(self, address=address, **kwargs)

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
            v = self.mag_sample.get_voltage_response()
            # Return X=v, Y=v/10 for semi-legit look
            return (float(v), float(v/10))
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
