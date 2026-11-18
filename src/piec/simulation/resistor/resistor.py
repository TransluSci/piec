"""Level-2 input/output contract for two-terminal resistive samples."""
from piec.simulation.sample import Sample


class ResistiveMaterial(Sample):
    """Level-2 contract interface for two-terminal resistive samples.

    Defines the required electrical stimulus and response contract without
    implementing device physics. Level-3 models (e.g., ``OhmicResistor``,
    ``SimpleDiode``) implement these methods directly.
    """

    def __init__(self, parameter_dict=None, name="resistive_material"):
        super().__init__(parameter_dict=parameter_dict, name=name)

    def set_voltage(self, v):
        """Apply DC voltage ``v`` (V) and update sample state."""
        raise NotImplementedError

    def set_current(self, i):
        """Apply DC current ``i`` (A) and update sample state."""
        raise NotImplementedError

    def get_voltage(self):
        """Return terminal voltage in Volts."""
        raise NotImplementedError

    def get_current(self):
        """Return terminal current in Amperes."""
        raise NotImplementedError

    def get_resistance(self, angle=None, field=None):
        """Return sample resistance in Ohms."""
        raise NotImplementedError

    def voltage_response(self, v, t=0.0):
        """Return ``(current_A, time_s)`` for an applied voltage ``v`` (V)."""
        raise NotImplementedError

    def current_response(self, i, t=0.0):
        """Return ``(voltage_V, time_s)`` for an applied current ``i`` (A)."""
        raise NotImplementedError

    def apply_waveform(self, v, t):
        """Apply voltage waveform ``v(t)`` (V) over time ``t`` (s)."""
        raise NotImplementedError

    def get_waveform(self):
        """Return ``(output_voltage_V, time_s)`` recorded from the last applied waveform."""
        raise NotImplementedError