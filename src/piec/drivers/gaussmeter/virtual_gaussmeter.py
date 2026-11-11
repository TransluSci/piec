"""Field readout from PIEC's shared magnetic sample."""
from ..virtual_instrument import VirtualInstrument
from .gaussmeter import Gaussmeter


class VirtualGaussmeter(VirtualInstrument, Gaussmeter):
    AI_STATUS = 'generated'
    HARDWARE_TESTED = False

    def idn(self):
        return 'PIEC Virtual Gaussmeter'

    def get_field(self, channel=1):
        """Return one signed float in Oe for the selected channel.

        Drivers reporting flux density should convert it to the equivalent
        applied field in air.
        """
        if channel not in self.channel:
            raise ValueError(f'Unavailable gaussmeter channel: {channel}')
        return float(self.mag_sample.current_field)
