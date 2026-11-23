"""Manufacturer-independent magnetic-field source interface."""
from ..instrument import Instrument, optional


class FieldController(Instrument):
    """A source that accepts field setpoints in Oe."""

    field = None  # Model-specific (min, max) or dependent on field_range {field_range: (min, max)} setpoints in Oe
    #optional
    field_range = [None]  # max value of selected range in Oe, or None if single range setting


    def set_field(self, field):
        """Set the magnetic-field target in Oe."""
        raise NotImplementedError

    @optional
    def set_range(self, field_range):
        """Select a supported output range."""