from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.virtual_instrument import VirtualInstrument

class VirtualCalibrator(VirtualInstrument, DCCalibrator):
    """
    Virtual version of a Calibrator that updates shared magnetic sample field.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
        self.state = {
            'voltage': 0.0,
            'current': 0.0,
            'mode': 'voltage',
            'output_on': False,
        }

    def idn(self):
        return "Virtual Calibrator"

    def set_voltage(self, voltage):
        self.state['voltage'] = voltage
        return self.set_output(voltage, mode="voltage")

    def set_current(self, current):
        self.state['current'] = current
        return self.set_output(current, mode="current")

    def set_output(self, value, mode="voltage", **kwargs):
        self.state[mode] = value
        self.state['mode'] = mode
        if self.sample is not None:
            if mode == "voltage":
                self.sample.set_voltage(value)
            elif mode == "current":
                self.sample.set_current(value)
        return super().set_output(value, mode=mode, **kwargs)

    def output(self, on=True):
        """Enable or disable calibrator main output."""
        self._output_enabled = bool(on)
        self.state['output_on'] = self._output_enabled
        if self.sample is not None:
            if not self._output_enabled:
                if self.state['mode'] == "current":
                    self.sample.set_current(0.0)
                else:
                    self.sample.set_voltage(0.0)
            elif self.state['mode'] == "current":
                self.sample.set_current(self.state['current'])
            else:
                self.sample.set_voltage(self.state['voltage'])
