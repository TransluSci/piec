from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.virtual_instrument import VirtualInstrument

class VirtualCalibrator(VirtualInstrument, DCCalibrator):
    """
    Virtual version of a Calibrator that updates shared magnetic sample field.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
        self.voltage_callibration = kwargs.get('voltage_callibration', 10000.0)

    def idn(self):
        return "Virtual Calibrator"

    def set_voltage(self, voltage):
        return self.set_output(voltage, mode="voltage")

    def set_output(self, value, mode="voltage", **kwargs):
        # Update shared magnetic sample field
        if mode == "voltage" and hasattr(self, 'mag_sample') and self.mag_sample:
            self.mag_sample.current_field = value * self.voltage_callibration
        
        return super().set_output(value, mode=mode, **kwargs)
