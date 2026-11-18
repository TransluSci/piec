"""Level-2 input/output contract for ferroelectric capacitor samples."""
from piec.simulation.sample import Sample


class FerroelectricMaterial(Sample):
    """Level-2 contract interface for ferroelectric capacitor samples.

    Defines the bare-minimum stimulus-to-response contract for ferroelectric
    models (e.g., ``LandauFerroelectric``).
    """

    def apply_voltage(self, v, t=0.0):
        """Apply voltage ``v`` (V) over time ``t`` (s) and return current in Amperes."""
