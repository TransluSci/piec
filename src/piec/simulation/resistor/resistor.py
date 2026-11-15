"""Level-2 input/output contract for two-terminal resistive samples."""
import numpy as np
from piec.simulation.sample import Sample


class ResistiveMaterial(Sample):
    """Base interface for resistive samples measured by sourcemeters or scopes.

    Defines only the standardized inputs (applied voltage/current/waveform) and
    outputs (current, voltage, and time in SI units). Level-3 subclasses
    implement specific I-V physics (e.g., OhmicResistor, SimpleDiode) via
    ``_compute_current`` and ``_compute_voltage``.
    """

    def __init__(self, parameter_dict=None, name="resistive_material"):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.output_voltage = np.array([])
        self.t = np.array([])
        self.prep_points = 0

    def _compute_current(self, v, t=0.0):
        """Model hook: return current (A) for applied voltage v (V)."""
        return v

    def _compute_voltage(self, i, t=0.0):
        """Model hook: return voltage (V) for applied current i (A)."""
        return i

    def voltage_response(self, v, t=0.0):
        """Return (current_A, time_s) for an applied voltage v (V) at time t (s)."""
        return self._compute_current(v, t), t

    def current_response(self, i, t=0.0):
        """Return (voltage_V, time_s) for an applied current i (A) at time t (s)."""
        return self._compute_voltage(i, t), t

    def apply_waveform(self, v, t):
        """Apply a voltage waveform v(t) across the sample for scope readout."""
        p = getattr(self, 'prep_points', 0)
        self.output_voltage = np.array(v[p:])
        self.t = np.array(t[p:]) - (t[p] if len(t) > p else 0.0)

    def get_voltage_response(self):
        """Return (output_voltage_V, time_s) recorded from the last waveform."""
        return self.output_voltage, self.t
