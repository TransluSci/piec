"""A small stateful magnetic material model, independent of instruments."""

from __future__ import annotations

from typing import Any, Optional, Sequence
import numpy as np

from piec.simulation.contracts import FieldResponsiveMaterialContract


class HystereticMagneticMaterial(FieldResponsiveMaterialContract):
    """Qualitative hysteresis using an ensemble of symmetric switching domains.

    Each domain switches up at its positive threshold and down at its negative
    threshold, retaining its state between them. This produces major loops,
    remanence, and history-dependent partial reversals. It is a demonstration
    model, not a quantitative micromagnetic or magnet power-supply model.

    All field parameters must use the same units as the supplied field.
    Magnetization is normalized to [-1, 1]. Optical gain and voltage offset
    belong to the simulated detector/setup, not this material.
    """

    def __init__(
        self,
        coercive_field: float = 50.0,
        switching_width: float = 10.0,
        domains: int = 201,
        seed: Optional[int] = None,
        start_time: float = 0.0,
    ) -> None:
        super().__init__(seed=seed, start_time=start_time)
        if not np.isfinite(coercive_field) or coercive_field <= 0:
            raise ValueError("coercive_field must be positive and finite")
        if not np.isfinite(switching_width) or not 0 <= switching_width < coercive_field:
            raise ValueError("switching_width must be nonnegative and below coercive_field")
        if isinstance(domains, bool) or not isinstance(domains, (int, np.integer)) or domains < 1:
            raise ValueError("domains must be a positive integer")
        self._thresholds = np.linspace(
            coercive_field - switching_width, coercive_field + switching_width, domains
        ) if domains > 1 else np.array([coercive_field])
        self._current_field = 0.0
        self.reset()

    def reset(self, polarity: int = -1, seed: Optional[int] = None, **kwargs: Any) -> None:
        """Start at zero field with all domains in the chosen magnetic state."""
        if polarity not in (-1, 1):
            raise ValueError("polarity must be -1 or 1")
        self._states = np.full(len(self._thresholds), polarity, dtype=float)
        self._current_field = 0.0
        self._timebase.reset(start_time=kwargs.get("start_time", 0.0))
        effective_seed = seed if seed is not None else self._initial_seed
        self.seed(effective_seed)

    @property
    def current_field(self) -> float:
        return self._current_field

    @current_field.setter
    def current_field(self, value: float) -> None:
        self._current_field = float(value)

    @property
    def magnetization(self) -> float:
        return float(np.mean(self._states))

    def apply_field(self, field: float, time: Optional[float] = None) -> float:
        """Apply one field value in Oe and return the resulting magnetization."""
        if not np.isscalar(field) or not np.isfinite(field):
            raise ValueError("field must be a finite scalar")
        if time is not None:
            self._timebase.set_time(time)
        self.current_field = float(field)
        self._states[field >= self._thresholds] = 1.0
        self._states[field <= -self._thresholds] = -1.0
        return self.magnetization

    def response(
        self,
        fields: Sequence[float],
        times: Optional[Sequence[float]] = None,
    ) -> np.ndarray:
        """Apply an ordered field history, preserving state between calls."""
        fields_arr = np.asarray(fields, dtype=float)
        if fields_arr.ndim != 1 or not np.isfinite(fields_arr).all():
            raise ValueError("fields must be a finite one-dimensional sequence")
        if times is not None:
            times_arr = np.asarray(times, dtype=float)
            if times_arr.shape != fields_arr.shape:
                raise ValueError("times and fields must have matching shapes")
            return np.array([self.apply_field(f, time=t) for f, t in zip(fields_arr, times_arr)])
        return np.array([self.apply_field(field) for field in fields_arr])
