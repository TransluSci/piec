"""
Simulation model for a magnetic sample, used for generating synthetic magneto-transport data.
"""

from __future__ import annotations

from typing import Any, Optional
import numpy as np

from piec.simulation.contracts import AngleDependentResistanceContract


class MagneticSample(AngleDependentResistanceContract):
    """
    Simulation model for a magnetic sample, used for generating synthetic magneto-transport data.
    """

    def __init__(
        self,
        r_base: float = 100.0,
        amr_ratio: float = 0.02,
        phi_offset: float = 0.0,
        seed: Optional[int] = None,
        start_time: float = 0.0,
    ) -> None:
        """
        Initialize the magnetic sample.

        Args:
            r_base: Base resistance in Ohms.
            amr_ratio: (R_par - R_perp) / R_perp.
            phi_offset: Angle offset in degrees.
            seed: Optional random seed for deterministic noise.
            start_time: Initial simulation time in seconds.
        """
        super().__init__(seed=seed, start_time=start_time)
        if not all(np.isfinite(v) for v in (r_base, amr_ratio, phi_offset)) or r_base <= 0 or amr_ratio <= -1:
            raise ValueError("sample parameters must be finite with positive resistance")
        self.r_base = float(r_base)
        self.amr_ratio = float(amr_ratio)
        self.phi_offset = float(phi_offset)
        self._current_angle = 0.0  # degrees
        self._current_field = 0.0  # Oe
        self.name = "virtual_magnetic_sample"

    @property
    def current_angle(self) -> float:
        """Current orientation angle in degrees."""
        return self._current_angle

    @current_angle.setter
    def current_angle(self, value: float) -> None:
        self._current_angle = float(value)

    @property
    def current_field(self) -> float:
        """Current applied magnetic field in Oe."""
        return self._current_field

    @current_field.setter
    def current_field(self, value: float) -> None:
        self._current_field = float(value)

    def reset(self, seed: Optional[int] = None, **kwargs: Any) -> None:
        """Reset angle, field, timebase, and random number generator."""
        self._current_angle = 0.0
        self._current_field = 0.0
        self._timebase.reset(start_time=kwargs.get("start_time", self._initial_time))
        effective_seed = seed if seed is not None else self._initial_seed
        self.seed(effective_seed)

    def get_resistance(
        self,
        angle: Optional[float] = None,
        field: Optional[float] = None,
        time: Optional[float] = None,
    ) -> float:
        """
        Calculate resistance based on commanded angle and field.
        Simplified AMR model: R = R_perp + (R_par - R_perp) * cos^2(theta - phi)

        Args:
            angle: Angle in degrees. Uses current_angle if None.
            field: Field in Oe. Uses current_field if None.
            time: Optional simulation timestamp in seconds.

        Returns:
            float: Simulated resistance in Ohms.
        """
        if not all(np.isfinite(v) for v in (angle if angle is not None else self.current_angle, field if field is not None else self.current_field)):
            raise ValueError("angle and field must be finite")
        if time is not None:
            self._timebase.set_time(time)
        theta_val = angle if angle is not None else self._current_angle
        theta = np.radians(theta_val)
        phi = np.radians(self.phi_offset)

        # Simple AMR cos^2 dependence
        r_perp = self.r_base
        r_par = self.r_base * (1.0 + self.amr_ratio)

        resistance = r_perp + (r_par - r_perp) * (np.cos(theta - phi) ** 2)

        # Deterministic noise from seeded RNG
        noise = float(self._rng.normal(0.0, self.r_base * 0.0001))
        return float(resistance + noise)

    def get_voltage_response(
        self,
        excitation_current: float,
        angle: Optional[float] = None,
        field: Optional[float] = None,
        time: Optional[float] = None,
    ) -> tuple[float, float]:
        """
        Simulate a lock-in voltage response in Volts.

        Returns:
            Tuple (X, Y) in V for an ideal resistive sample in phase with the reference.
        """
        if not np.isfinite(excitation_current):
            raise ValueError("excitation_current must be finite and specified in A")
        r = self.get_resistance(angle=angle, field=field, time=time)
        return (r * float(excitation_current), 0.0)
