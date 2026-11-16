"""Level-2 contract template for simulated samples."""
from piec.simulation.sample import Sample


class ExampleSample(Sample):
    """Template Level-2 contract interface for a simulated sample category.

    Level-2 classes declare the category's required public methods (overriding
    the Level-1 ``Sample`` methods relevant to this experiment type) with
    ``raise NotImplementedError`` stubs and no physics implementation.
    """

    def __init__(self, parameter_dict=None, name="example_sample"):
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

    def apply_waveform(self, v, t):
        """Apply a voltage waveform ``v(t)`` (V) over time ``t`` (s)."""
        raise NotImplementedError

    def get_waveform(self):
        """Return ``(output_voltage_V, time_s)`` recorded from the last applied waveform."""
        raise NotImplementedError