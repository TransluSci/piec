from piec.drivers.dmm.dmm import DMM
from piec.drivers.virtual_instrument import VirtualInstrument

class VirtualDMM(VirtualInstrument, DMM):
    """
    Virtual version of a DMM.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        VirtualInstrument.__init__(self, address=address)
        DMM.__init__(self, address=address, **kwargs)

    def idn(self):
        return "Virtual DMM"

    def get_voltage(self, ac=False):
        if hasattr(self, 'mag_sample') and self.mag_sample:
            # In AMR.set_field, actual_field = actual_voltage * self.voltage_callibration
            # So actual_voltage should be field / voltage_callibration.
            # We don't have voltage_callibration here, but we can assume the ratio.
            # Or just return current_field / 10000.0
            return self.mag_sample.current_field / 10000.0
        return 0.0015
