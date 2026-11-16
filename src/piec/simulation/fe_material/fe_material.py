"""Level-2 input/output contract for ferroelectric capacitor samples."""
from piec.simulation.sample import Sample


class FerroelectricMaterial(Sample):
    """Level-2 contract interface for ferroelectric capacitor samples.

    Defines the standardized stimulus inputs and response outputs used by
    virtual AWGs, oscilloscopes, and sourcemeters without implementing device
    physics. Level-3 models (e.g., ``LandauFerroelectric``) implement these
    public methods directly.
    """

    def __init__(self, parameter_dict=None, name=None):
        super().__init__(parameter_dict=parameter_dict, name=name)

    def apply_waveform(self, v, t):
        """Apply a voltage waveform ``v(t)`` (V) over time ``t`` (s) across the sample."""
        raise NotImplementedError

    def get_waveform(self):
        """Return ``(output_voltage_V, time_s)`` measured across the series sense resistor."""
        raise NotImplementedError

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
        """Return leakage current in Amperes."""
        raise NotImplementedError