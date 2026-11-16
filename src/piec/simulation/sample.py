"""Level-1 foundation for all simulated samples."""
import numpy as np


class Sample:
    """Level-1 base class providing sample metadata and universal physical I/O.

    Every simulated sample inherits from ``Sample``. Level 1 defines the
    common stimulus inputs (``set_voltage``, ``set_current``, ``set_field``,
    ``set_angle``, ``apply_waveform``) and response observables
    (``get_voltage``, ``get_current``, ``get_resistance``, ``get_field``,
    ``get_angle``, ``get_waveform``) with baseline state tracking so any
    virtual instrument can interact with any sample without category-specific
    special cases.
    """

    def __init__(self, parameter_dict=None, name=None):
        self.name = name
        self.parameter_dict = {} if parameter_dict is None else parameter_dict
        self._voltage = 0.0
        self._current = 0.0
        self._field = 0.0
        self._angle = 0.0
        self.prep_points = 0
        self._waveform_v = np.array([])
        self._waveform_t = np.array([])

    @property
    def current_field(self):
        """Applied magnetic field in Oe."""
        return self.get_field()

    @current_field.setter
    def current_field(self, value):
        self.set_field(value)

    @property
    def current_angle(self):
        """Sample orientation angle in degrees."""
        return self.get_angle()

    @current_angle.setter
    def current_angle(self, value):
        self.set_angle(value)

    def set_voltage(self, v):
        """Apply a DC voltage stimulus in Volts."""
        self._voltage = float(v)

    def set_current(self, i):
        """Apply a DC current stimulus in Amperes."""
        self._current = float(i)

    def set_field(self, field):
        """Apply a magnetic field stimulus in Oersted (Oe)."""
        self._field = float(field)

    def set_angle(self, angle):
        """Set the sample orientation angle in degrees."""
        self._angle = float(angle)

    def apply_waveform(self, v, t):
        """Apply a voltage waveform ``v(t)`` (V) over time ``t`` (s)."""
        p = getattr(self, 'prep_points', 0)
        self._waveform_v = np.asarray(v[p:], dtype=float)
        self._waveform_t = np.asarray(t[p:], dtype=float) - (float(t[p]) if len(t) > p else 0.0)

    def get_voltage(self):
        """Return the measured terminal/detector voltage in Volts."""
        return float(self._voltage)

    def get_current(self):
        """Return the measured terminal current in Amperes."""
        return float(self._current)

    def get_resistance(self, angle=None, field=None):
        """Return the electrical resistance in Ohms."""
        if self._current != 0:
            return float(self._voltage / self._current)
        return 0.0

    def get_field(self):
        """Return the applied magnetic field in Oersted (Oe)."""
        return float(self._field)

    def get_angle(self):
        """Return the sample orientation angle in degrees."""
        return float(self._angle)

    def get_waveform(self):
        """Return ``(voltage_V, time_s)`` arrays from the last applied waveform."""
        return self._waveform_v, self._waveform_t