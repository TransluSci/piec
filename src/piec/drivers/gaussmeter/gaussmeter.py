"""Common interface for magnetic-field readout."""
from ..instrument import Instrument, optional


class Gaussmeter(Instrument):
    """Read the signed field along a probe's measurement axis."""

    channel = [1]
    #optional
    field_range = [None]  # max value of selected range in Oe, or None if single range setting


    def get_field(self, channel=1):
        """Return one signed float in Oe for the selected channel.

        Drivers reporting flux density should convert it to the equivalent
        applied field in air.
        """
        raise NotImplementedError

    @optional
    def set_range(self, field_range, channel=1):
        """Select a supported readout range for the selected channel."""
