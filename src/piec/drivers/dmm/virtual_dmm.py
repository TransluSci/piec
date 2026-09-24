from piec.drivers.dmm.dmm import DMM
from piec.drivers.virtual_instrument import VirtualInstrument


class VirtualDMM(VirtualInstrument, DMM):
    """Virtual DMM with configurable state and an optional voltage reader."""

    def __init__(self, address="VIRTUAL", voltage_reader=None, **kwargs):
        super().__init__(address=address, **kwargs)
        self.state = {
            "sense_func": "VOLT",
            "coupling": "DC",
            "sense_mode": "2W",
            "sense_range": None,
            "autorange": True,
            "integration_time": 1.0,
        }
        self._voltage_reader = None
        self.set_voltage_reader(voltage_reader)

    def idn(self):
        return "Virtual DMM"

    def set_voltage_reader(self, voltage_reader):
        """Inject a no-argument callable representing the connected voltage."""
        if voltage_reader is not None and not callable(voltage_reader):
            raise TypeError("voltage_reader must be callable or None")
        self._voltage_reader = voltage_reader

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
        if self._voltage_reader is not None:
            return float(self._voltage_reader())
        if self.mag_sample:
            # In AMR.set_field, actual_field = actual_voltage * self.voltage_callibration
            # So actual_voltage should be field / voltage_callibration.
            # We don't have voltage_callibration here, but we can assume the ratio.
            # Or just return current_field / 10000.0
            return self.mag_sample.current_field / 10000.0
        return 0.0015

    def quick_read(self):
        return self.get_voltage(ac=self.state["coupling"] == "AC")

    def reset(self):
        voltage_reader = self._voltage_reader
        self.__init__(voltage_reader=voltage_reader)

    def clear(self):
        return None

    def get_state(self):
        return self.state.copy()
