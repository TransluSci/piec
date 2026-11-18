"""Level-2 input/output contract for Magneto-Optic Kerr Effect (MOKE) samples."""
from piec.simulation.sample import Sample


class MOKEMaterial(Sample):
    """Level-2 contract interface for MOKE samples.

    Defines the stimulus inputs (applied magnetic field) and optical
    response outputs (magnetization and photodetector voltage) used by
    virtual field controllers, gaussmeters, and DMMs.
    """

    def __init__(self, parameter_dict=None, name="moke_material"):
        super().__init__(parameter_dict=parameter_dict, name=name)

    def set_field(self, field):
        """Apply magnetic field in Oe and advance the magnetic state."""
        raise NotImplementedError

    def get_field(self):
        """Return the current applied magnetic field in Oe."""
        raise NotImplementedError

    def get_magnetization(self):
        """Return normalized magnetization ``M / Ms`` in ``[-1, 1]``."""
        raise NotImplementedError

    def get_voltage(self):
        """Return simulated MOKE photodetector voltage in Volts."""
        raise NotImplementedError