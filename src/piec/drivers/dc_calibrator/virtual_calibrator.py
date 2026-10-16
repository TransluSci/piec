from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.virtual_instrument import VirtualInstrument

class VirtualCalibrator(VirtualInstrument, DCCalibrator):
    """
    Virtual version of a Calibrator that updates shared magnetic sample field.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
        self.voltage_callibration = kwargs.get('voltage_callibration', 10000.0)
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
        if mode == "voltage" and hasattr(self, 'mag_sample') and self.mag_sample:
            self.mag_sample.current_field = value * self.voltage_callibration
        return super().set_output(value, mode=mode, **kwargs)

    def output(self, on=True):
        """Enable or disable calibrator main output."""
        self._output_enabled = bool(on)
        self.state['output_on'] = self._output_enabled
        if not self._output_enabled and hasattr(self, 'mag_sample') and self.mag_sample:
            self.mag_sample.current_field = 0.0
