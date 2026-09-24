"""
This is an outline for what the rf_source.py file should be like.

A rf source is defined as an instrument that has the typical features one expects a rf source to have
"""
import warnings

from ..instrument import Instrument

#note still a WIP
class RFSource(Instrument):
    """
    All rf sources must be able to generate an RF signal

    Instrument-management methods follow the shared contract in Instrument.
    """
    # Class attributes for parameter restrictions
    channel = [1]
    frequency = (None, None)
    power = (None, None)
    modulation = ['AM', 'FM', 'PM', 'PULSE']

    #Core RF output functions
    def set_frequency(self, frequency):
        """
        Sets the frequency of the RF output
        """
    def set_power(self, power):
        """
        Sets the output power of the RF source
        """
    def output(self, channel, on=True):
        """
        Turns the RF output on or off for the specified channel
        """
    #basic modulation functions
    def set_modulation(self, modulation_type):
        """
        Sets the modulation type for the RF output (e.g., AM, FM, PM)
        """
    def enable_modulation(self, on=True):
        """
        Enables or disables modulation for the RF output
        """
    #for AM
    def set_am_depth(self, depth):
        """
        Sets the modulation depth for AM modulation (0 to 100%)
        """
    def set_am_frequency(self, frequency):
        """
        Sets the modulation frequency for AM modulation
        """
    #for FM
    def set_fm_deviation(self, deviation):
        """
        Sets the frequency deviation for FM modulation
        """
    def set_fm_frequency(self, frequency):
        """
        Sets the modulation frequency for FM modulation
        """
    #for PM
    def set_pulse_width(self, width):
        """
        Sets the pulse width for PM modulation
        """
    def set_pulse_period(self, period):
        """
        Sets the pulse period for PM modulation
        """
    #frequnecy referecnce control
    def set_reference_source(self, source):
        """
        Sets the reference source for the RF output (internal, external, etc.)
        """
    #basic sweep functions
    def set_sweep_start_frequency(self, frequency):
        """
        Sets the start frequency for a frequency sweep
        """
    def set_sweep_stop_frequency(self, frequency):
        """
        Sets the stop frequency for a frequency sweep
        """
    def set_sweep_points(self, points):
        """
        Sets the number of points for a frequency sweep
        """
    def output_sweep(self, on=True):
        """
        Turns the frequency sweep on or off
        """
    def set_sweep_mode(self, mode):
        """
        Sets the sweep mode (e.g., linear, logarithmic)
        """

def __getattr__(name):
    """Provide the historical class name with a deprecation warning."""
    if name == "RF_source":
        warnings.warn(
            "RF_source is deprecated; use RFSource instead. The legacy name "
            "will remain supported through PIEC version 1.5.",
            DeprecationWarning,
            stacklevel=2,
        )
        return RFSource
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
