"""Level-2 input/output contract for hysteretic magnetic samples."""
import numpy as np
from piec.simulation.sample import Sample


class HystereticMagneticMaterial(Sample):
    """Base interface for hysteretic ferromagnetic samples under applied field.

    Defines only the input/output contract: an applied magnetic field in Oe
    updates the normalized magnetization ``M/Ms`` in ``[-1, 1]`` and produces
    a simulated MOKE optical detector voltage in Volts. Level-3 subclasses
    implement the specific hysteresis physics (e.g., ``ArctanMOKE``).
    """

    def __init__(self, parameter_dict=None, name="hysteretic_magnetic_material"):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self._current_field = 0.0
        self._magnetization = 0.0

    @property
    def current_field(self):
        """Applied magnetic field in Oe."""
        return self._current_field

    @current_field.setter
    def current_field(self, field):
        self.set_field(field)

    def _update_magnetization(self, new_field, prev_field):
        """Model hook: return updated normalized magnetization in [-1, 1]."""
        return self._magnetization

    def _compute_moke_voltage(self):
        """Model hook: return simulated MOKE optical detector voltage in Volts."""
        return float(self._magnetization)

    def set_field(self, field):
        """Apply magnetic field in Oe and advance the hysteretic sample state."""
        value = float(field)
        if not np.isfinite(value):
            raise ValueError('Field must be finite')
        updated = float(self._update_magnetization(value, self._current_field))
        self._magnetization = float(np.clip(updated, -1.0, 1.0))
        self._current_field = value

    def get_magnetization(self):
        """Return normalized magnetization M/Ms in [-1, 1]."""
        return float(self._magnetization)

    def get_moke_voltage(self):
        """Return simulated MOKE optical detector voltage in Volts."""
        return float(self._compute_moke_voltage())
