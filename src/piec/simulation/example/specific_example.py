"""Level-3 example simulation model implementing the ExampleSample contract."""
import numpy as np
from .example import ExampleSample


class SpecificExampleSample(ExampleSample):
    """Concrete Level-3 simulation model using scalar and dictionary parameters.

    Demonstrates a simple linear conductance + offset model where arbitrary
    model-specific parameters are resolved from ``parameter_dict`` with scalar
    defaults while fulfilling the unified ``Sample`` / ``ExampleSample``
    physical I/O interface.
    """

    def __init__(
        self,
        conductance=1e-3,
        offset_current=0.0,
        *,
        parameter_dict=None,
        name="specific_example_sample",
    ):
        """Initialize model parameters; dictionary values override scalar arguments."""
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.conductance = float(self.parameter_dict.setdefault("conductance", conductance))
        self.offset_current = float(self.parameter_dict.setdefault("offset_current", offset_current))
        self.output_voltage = np.array([])
        self.t = np.array([])

    def set_voltage(self, v):
        """Apply DC voltage ``v`` (V) and update ``I = G * V + I0``."""
        self._voltage = float(v)
        self._current = self.conductance * self._voltage + self.offset_current

    def set_current(self, i):
        """Apply DC current ``i`` (A) and update ``V = (I - I0) / G``."""
        self._current = float(i)
        self._voltage = (self._current - self.offset_current) / self.conductance

    def get_voltage(self):
        """Return terminal voltage in Volts."""
        return float(self._voltage)

    def get_current(self):
        """Return terminal current in Amperes."""
        return float(self._current)

    def apply_waveform(self, v, t):
        """Record the applied voltage waveform ``v(t)`` after ``prep_points``."""
        p = getattr(self, "prep_points", 0)
        self.output_voltage = np.array(v[p:])
        self.t = np.array(t[p:]) - (t[p] if len(t) > p else 0.0)

    def get_waveform(self):
        """Return ``(output_voltage_V, time_s)`` from the last applied waveform."""
        return self.output_voltage, self.t