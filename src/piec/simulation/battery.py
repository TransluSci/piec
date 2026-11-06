"""Small, deterministic battery model for virtual current-source experiments."""

import math

from .sample import Sample


class Battery(Sample):
    """Coulomb-counting battery with linear open-circuit voltage and series R.

    Positive current charges the cell. Capacity is in Ah, voltages in V,
    resistance in ohms, and state of charge is a fraction in [0, 1]. Dictionary
    parameters override scalar defaults, following the other sample models.
    This is a demonstration model, without chemistry, aging, or thermal effects.
    Reads do not evolve the sample; call ``advance_time`` explicitly.
    """

    def __init__(self, capacity_ah=0.001, voltage_empty=3.0, voltage_full=4.2,
                 resistance=1.0, initial_soc=0.2, *, parameter_dict=None,
                 name='virtual_battery'):
        super().__init__(parameter_dict=parameter_dict, name=name)
        for key, value in dict(capacity_ah=capacity_ah, voltage_empty=voltage_empty,
                               voltage_full=voltage_full, resistance=resistance,
                               initial_soc=initial_soc).items():
            value = float(self.parameter_dict.setdefault(key, value))
            if not math.isfinite(value):
                raise ValueError(f'{key} must be finite')
            setattr(self, key, value)
        if self.capacity_ah <= 0 or self.resistance <= 0:
            raise ValueError('capacity_ah and resistance must be positive')
        if self.voltage_empty >= self.voltage_full:
            raise ValueError('voltage_empty must be below voltage_full')
        if not 0 <= self.initial_soc <= 1:
            raise ValueError('initial_soc must be between 0 and 1')
        self.soc = self.initial_soc

    @property
    def open_circuit_voltage(self):
        """Open-circuit voltage (V) at the present state of charge."""
        return self.voltage_empty + self.soc * (self.voltage_full - self.voltage_empty)

    def advance_time(self, current, seconds):
        """Apply constant ``current`` (A) for ``seconds`` (s), clamping SOC.

        No wall-clock waiting occurs. At empty/full SOC the voltage saturates;
        experiments must use voltage cutoffs and a timeout for unreachable limits.
        """
        if not math.isfinite(current) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('current must be finite and seconds finite and nonnegative')
        self.soc = min(1.0, max(0.0, self.soc + current * seconds / (3600 * self.capacity_ah)))

    def current_response(self, i, t):
        """Return instantaneous terminal voltage (V) and unchanged time coordinate.

        Like other samples, this accepts scalar or NumPy-array inputs. Time is
        a coordinate only; ``advance_time`` controls this model's evolution.
        """
        return self.open_circuit_voltage + i * self.resistance, t

    def voltage_response(self, v, t):
        """Return instantaneous current (A) at voltage ``v`` and time coordinate."""
        return (v - self.open_circuit_voltage) / self.resistance, t
