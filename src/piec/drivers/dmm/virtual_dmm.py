from piec.drivers.dmm.dmm import DMM
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualDMM(VirtualInstrument, DMM):
    """Virtual DMM with configurable state measuring ``VirtualInstrument.sample``."""

    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
        self.state = {
            "sense_func": "VOLT",
            "coupling": "DC",
            "sense_mode": "2W",
            "sense_range": None,
            "autorange": True,
            "integration_time": 1.0,
        }

    def idn(self):
        return "Virtual DMM"

    def set_sense_function(self, sense_func):
        sense_func = str(sense_func).upper()
        if sense_func not in self.sense_func:
            raise ValueError(f"unsupported sense function {sense_func!r}")
        self.state["sense_func"] = sense_func

    def set_measurement_coupling(self, coupling):
        coupling = str(coupling).upper()
        if coupling not in self.coupling:
            raise ValueError(f"unsupported measurement coupling {coupling!r}")
        self.state["coupling"] = coupling

    def set_sense_mode(self, sense_mode):
        sense_mode = str(sense_mode).upper()
        if sense_mode not in self.sense_mode:
            raise ValueError(f"unsupported sense mode {sense_mode!r}")
        self.state["sense_mode"] = sense_mode

    def set_sense_range(self, range_val=None, auto=True):
        if not auto and range_val is None:
            raise ValueError("range_val is required when autorange is disabled")
        self.state["sense_range"] = None if auto else float(range_val)
        self.state["autorange"] = bool(auto)

    def set_integration_time(self, nplc=1):
        nplc = float(nplc)
        if nplc <= 0:
            raise ValueError("nplc must be positive")
        self.state["integration_time"] = nplc

    def get_voltage(self, ac=False):
        self.state["sense_func"] = "VOLT"
        self.state["coupling"] = "AC" if ac else "DC"
        if self.sample is not None:
            return float(self.sample.get_voltage())
        return 0.0015

    def quick_read(self):
        return self.get_voltage(ac=self.state["coupling"] == "AC")

    def reset(self):
        self.__init__()

    def clear(self):
        return None

    def get_state(self):
        return self.state.copy()
