"""Virtual field source acting on PIEC's shared magnetic sample."""
import numpy as np

from ..virtual_instrument import VirtualInstrument
from .field_controller import FieldController


class VirtualFieldController(VirtualInstrument, FieldController):
    AI_STATUS = 'generated'
    HARDWARE_TESTED = False
    field = (-10000.0, 10000.0)

    def idn(self):
        return 'PIEC Virtual Field Controller'

    def set_field(self, field):
        """Set the magnetic-field target in Oe."""
        value = float(field)
        if not np.isfinite(value) or not self.field[0] <= value <= self.field[1]:
            raise ValueError('Requested field exceeds virtual field limits')
        update = getattr(type(self.mag_sample), 'set_field', None)
        if update is None:
            self.mag_sample.current_field = value
        else:
            self.mag_sample.set_field(value)

    def reset(self):
        self.set_field(0.0)
        super().reset()
