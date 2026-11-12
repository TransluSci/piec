"""Level-2 skeleton for two-terminal resistive samples."""
from piec.simulation.sample import Sample


class ResistiveMaterial(Sample):
    """Base interface for resistive samples measured by sourcemeters or scopes.

    Level-3 subclasses implement specific I-V models (e.g., Ohmic, diode,
    space-charge-limited) while preserving the same input/output methods.
    """
    resistance = None

    def __init__(self, parameter_dict=None, name="resistive_material"):
        super().__init__(parameter_dict=parameter_dict, name=name)

    def voltage_response(self, v, t=0.0):
        """Return (current_A, time_s) for an applied voltage v (V) at time t (s)."""
        return v, t

    def current_response(self, i, t=0.0):
        """Return (voltage_V, time_s) for an applied current i (A) at time t (s)."""
        return i, t

    def apply_waveform(self, v, t):
        """Apply a voltage waveform v(t) across the sample for scope readout."""

    def get_voltage_response(self):
        """Return (output_voltage_V, time_s) recorded from the last waveform."""
