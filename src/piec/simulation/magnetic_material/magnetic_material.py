"""Level-2 skeleton for magnetic samples used in MOKE and magneto-transport."""
from piec.simulation.sample import Sample


class MagneticMaterial(Sample):
    """Base interface for ferromagnetic samples under applied field and angle.

    Level-3 subclasses implement specific hysteresis and magneto-transport
    models (e.g., ArctanMOKE, Stoner-Wohlfarth) while exposing a uniform
    contract to VirtualFieldController, VirtualGaussmeter, VirtualDMM,
    VirtualStepper, and VirtualLockin.
    """
    coercivity = None
    switching_width = None
    bias = None
    r_base = None
    amr_ratio = None
    phi_offset = None

    def __init__(self, parameter_dict=None, name="virtual_magnetic_sample"):
        super().__init__(parameter_dict=parameter_dict, name=name)
        self.current_angle = 0.0
        self._current_field = 0.0

    @property
    def current_field(self):
        """Applied magnetic field in Oe."""
        return self._current_field

    @current_field.setter
    def current_field(self, field):
        self.set_field(field)

    def set_field(self, field):
        """Update the applied magnetic field in Oe and advance sample state."""
        self._current_field = float(field)

    def get_magnetization(self):
        """Return normalized magnetization M/Ms in [-1, 1] along the probed axis."""

    def get_moke_voltage(self):
        """Return simulated MOKE optical detector voltage in Volts."""

    def get_resistance(self, angle=None, field=None):
        """Return simulated electrical resistance in Ohms at (angle, field)."""

    def get_voltage_response(self, current_v=1.0):
        """Return simulated lock-in voltage response in Volts."""
