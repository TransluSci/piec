"""Level-2 input/output contract for two-terminal resistive and I-V samples."""
from piec.simulation.sample import Sample


class ResistiveMaterial(Sample):
    """Level-2 contract interface for two-terminal I-V samples.

    Defines the bare-minimum stimulus-to-response methods for resistive and
    nonlinear I-V devices (e.g., ``OhmicResistor``, ``SimpleDiode``). Both
    methods accept either scalar DC values or 1D waveform arrays.
    """

    def apply_voltage(self, v, t=0.0):
        """Apply voltage ``v`` (V) at time ``t`` (s) and return current in Amperes."""

    def apply_current(self, i, t=0.0):
        """Apply current ``i`` (A) at time ``t`` (s) and return voltage in Volts."""
