"""Level-2 input/output contract for Anisotropic Magnetoresistance (AMR) samples."""
from piec.simulation.sample import Sample


class AMRMaterial(Sample):
    """Level-2 contract interface for AMR and magneto-transport samples.

    Defines the bare-minimum stimulus-to-response contract mapping applied
    sense current, orientation angle, and magnetic field to terminal voltage.
    """

    def apply_current(self, i=1e-6, angle=0.0, field=0.0):
        """Apply current ``i`` (A) at ``(angle, field)`` (deg, Oe) and return voltage in Volts."""
