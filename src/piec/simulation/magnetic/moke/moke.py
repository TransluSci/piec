"""Level-2 input/output contract for Magneto-Optic Kerr Effect (MOKE) samples."""
from piec.simulation.sample import Sample


class MOKEMaterial(Sample):
    """Level-2 contract interface for MOKE samples.

    Defines the bare-minimum stimulus-to-response contract mapping applied
    magnetic field to photodetector voltage.
    """

    def apply_field(self, field):
        """Apply magnetic field ``field`` (Oe) and return photodetector voltage in Volts."""
