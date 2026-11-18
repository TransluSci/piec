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
            self.sample.state[mode] = float(value)
            self.sample.state['field'] = float(value) * 10000.0
        return super().set_output(value, mode=mode, **kwargs)

    def output(self, on=True):
        """Enable or disable calibrator main output."""
        self._output_enabled = bool(on)
        self.state['output_on'] = self._output_enabled
        if self.sample is not None:
            mode = self.state['mode']
            active = self.state[mode] if self._output_enabled else 0.0
            self.sample.state[mode] = float(active)
            self.sample.state['field'] = float(active) * 10000.0
