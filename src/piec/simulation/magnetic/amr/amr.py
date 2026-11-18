"""Level-2 input/output contract for Anisotropic Magnetoresistance (AMR) samples."""
from piec.simulation.sample import Sample


class AMRMaterial(Sample):
    """Level-2 contract interface for AMR and magneto-transport samples.

    Defines the stimulus inputs (applied magnetic field and orientation
    angle) and electrical transport outputs (resistance and terminal voltage)
    used by virtual calibrators, stepper motors, DMMs, and lock-in amplifiers.
    """

    def __init__(self, parameter_dict=None, name="amr_material"):
        super().__init__(parameter_dict=parameter_dict, name=name)

    def set_field(self, field):
        """Apply magnetic field in Oe."""
        raise NotImplementedError

    def get_field(self):
        """Return the current applied magnetic field in Oe."""
        raise NotImplementedError

    def set_angle(self, angle):
        """Set the sample orientation angle in degrees."""
        raise NotImplementedError

    def get_resistance(self, angle=None, field=None):
        """Return simulated electrical resistance in Ohms at ``(angle, field)``."""
        raise NotImplementedError

    def get_voltage(self):
        """Return terminal voltage in Volts."""
        raise NotImplementedError