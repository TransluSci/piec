"""
Role-specific simulation contracts, units, reset protocols, and deterministic time/RNG.

Fulfills Checkpoint 27 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Role-specific simulation contracts declaring explicit physical units;
- Deterministic timebase and RNG seeding protocols ensuring reproducible simulation;
- Two-terminal electrical load contract supporting voltage-source and current-source modes,
  compliance limits, time, state, and deterministic noise;
- Standard concrete electrical loads (ResistorLoad, DiodeLoad, CapacitiveLoad);
- Field-responsive material contract for magnetic simulation;
- Angle-dependent resistance contract for magneto-transport / AMR simulation;
- Waveform-responsive material contract for dynamic dielectric / ferroelectric simulation;
- Generic virtual hook protocols for driver-level dependency injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union

import numpy as np


# ============================================================================
# 1. Operating Modes and Response Data Structures
# ============================================================================

class LoadMode(str, Enum):
    """Operating mode of the source connected to a two-terminal electrical load."""

    VOLTAGE_SOURCE = "VOLTAGE_SOURCE"
    CURRENT_SOURCE = "CURRENT_SOURCE"


@dataclass(frozen=True)
class LoadResponse:
    """
    Immutable electrical response from an electrical load.

    All physical quantities use standard SI units:
    - voltage: Volts (V)
    - current: Amperes (A)
    - resistance: Ohms (Ohm)
    - time: Seconds (s)
    """

    voltage: float
    current: float
    compliance_tripped: bool
    time: float = 0.0
    resistance: float = float("nan")
    state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.voltage):
            raise ValueError(f"voltage must be finite, got {self.voltage}")
        if not math.isfinite(self.current):
            raise ValueError(f"current must be finite, got {self.current}")
        if not math.isfinite(self.time):
            raise ValueError(f"time must be finite, got {self.time}")


class VoltageResponse(float):
    """
    Simulated lock-in dual-channel voltage response (X, Y) in Volts.

    Subclasses float so legacy callers doing float(v) or arithmetic operations receive
    the in-phase X component directly, while callers unpacking as a tuple (x, y = v)
    or indexing (v[0], v[1]) receive both X and Y channels.
    """

    x: float
    y: float

    def __new__(cls, x: float, y: Optional[float] = None) -> VoltageResponse:
        x_val = float(x)
        y_val = float(y) if y is not None else x_val / 10.0
        val = super().__new__(cls, x_val)
        val.x = x_val
        val.y = y_val
        return val

    def __iter__(self):
        yield self.x
        yield self.y

    def __getitem__(self, idx: int) -> float:
        return (self.x, self.y)[idx]

    def __len__(self) -> int:
        return 2

    def __repr__(self) -> str:
        return f"VoltageResponse(x={self.x:.6e}, y={self.y:.6e})"


# ============================================================================
# 2. Deterministic Timebase and Simulation Role Base
# ============================================================================

class DeterministicTimebase:
    """
    Deterministic simulated clock independent of system wall-clock time.

    Enables reproducible multi-instrument simulation, time stepping, and resets.
    """

    def __init__(self, start_time: float = 0.0) -> None:
        if not math.isfinite(start_time) or start_time < 0.0:
            raise ValueError("start_time must be a finite non-negative number")
        self._current_time = float(start_time)

    @property
    def current_time(self) -> float:
        """Current simulated time in seconds."""
        return self._current_time

    def advance(self, delta_t: float) -> float:
        """
        Advance the simulation clock by delta_t seconds and return the new time.

        Args:
            delta_t: Time step in seconds (must be finite and non-negative).
        """
        if not math.isfinite(delta_t) or delta_t < 0.0:
            raise ValueError("delta_t must be a finite non-negative number")
        self._current_time += float(delta_t)
        return self._current_time

    def set_time(self, time: float) -> None:
        """Explicitly set the simulation time in seconds."""
        if not math.isfinite(time) or time < 0.0:
            raise ValueError("time must be a finite non-negative number")
        self._current_time = float(time)

    def reset(self, start_time: float = 0.0) -> None:
        """Reset the simulation clock to the specified start time."""
        self.set_time(start_time)


class SimulationRole(ABC):
    """
    Base contract for all simulated materials, loads, and role-specific models.

    Every simulation role:
    1. Declares immutable canonical physical units for all input/output quantities.
    2. Implements a reset() protocol that restores baseline state without cross-talk.
    3. Provides deterministic timebase and RNG seeding for reproducible results.
    """

    def __init__(self, seed: Optional[int] = None, start_time: float = 0.0) -> None:
        self._timebase = DeterministicTimebase(start_time=start_time)
        self._initial_seed = seed
        self._rng = np.random.default_rng(seed)

    @property
    @abstractmethod
    def declared_units(self) -> Mapping[str, str]:
        """Immutable mapping of quantity names to their standard physical unit strings."""
        raise NotImplementedError

    @abstractmethod
    def reset(self, seed: Optional[int] = None, **kwargs: Any) -> None:
        """
        Reset the simulation role to its pristine initial state.

        Args:
            seed: Optional new seed for random number generation. If None,
                  re-seeds using the initial seed.
            **kwargs: Role-specific reset parameters.
        """
        raise NotImplementedError

    @property
    def timebase(self) -> DeterministicTimebase:
        """Deterministic simulation timebase."""
        return self._timebase

    @property
    def rng(self) -> np.random.Generator:
        """Deterministic NumPy random number generator."""
        return self._rng

    def seed(self, seed: Optional[int]) -> None:
        """Re-seed the internal random number generator."""
        self._initial_seed = seed
        self._rng = np.random.default_rng(seed)


# ============================================================================
# 3. Two-Terminal Electrical Load Contract
# ============================================================================

class ElectricalLoadContract(SimulationRole, ABC):
    """
    Contract for two-terminal electrical loads.

    Supports:
    - Voltage-source operation (applies voltage V, measures current I with current compliance);
    - Current-source operation (forces current I, measures voltage V with voltage compliance);
    - Compliance limits, state tracking, and deterministic time/RNG;
    - Canonical declared units: {'voltage': 'V', 'current': 'A', 'resistance': 'Ohm', 'time': 's'}.
    """

    _UNITS: Mapping[str, str] = MappingProxyType({
        "voltage": "V",
        "current": "A",
        "resistance": "Ohm",
        "time": "s",
    })

    @property
    def declared_units(self) -> Mapping[str, str]:
        return self._UNITS

    @abstractmethod
    def evaluate(
        self,
        mode: LoadMode,
        stimulus: float,
        compliance: float,
        time: Optional[float] = None,
    ) -> LoadResponse:
        """
        Evaluate load response under voltage-source or current-source excitation.

        Args:
            mode: Operating mode (LoadMode.VOLTAGE_SOURCE or LoadMode.CURRENT_SOURCE).
            stimulus: Applied voltage in V (if VOLTAGE_SOURCE) or current in A (if CURRENT_SOURCE).
            compliance: Current limit in A (if VOLTAGE_SOURCE) or voltage limit in V (if CURRENT_SOURCE).
                        Must be strictly positive.
            time: Optional timestamp in seconds. If None, uses internal timebase.

        Returns:
            LoadResponse containing terminal voltage, current, compliance flag, and apparent resistance.
        """
        raise NotImplementedError

    def source_voltage(
        self,
        voltage: float,
        compliance_current: float = 1.05,
        time: Optional[float] = None,
    ) -> LoadResponse:
        """Convenience method for voltage-source operation."""
        return self.evaluate(LoadMode.VOLTAGE_SOURCE, voltage, compliance_current, time=time)

    def source_current(
        self,
        current: float,
        compliance_voltage: float = 210.0,
        time: Optional[float] = None,
    ) -> LoadResponse:
        """Convenience method for current-source operation."""
        return self.evaluate(LoadMode.CURRENT_SOURCE, current, compliance_voltage, time=time)

    def _validate_inputs(self, stimulus: float, compliance: float) -> None:
        """Validate stimulus and compliance values."""
        if not math.isfinite(stimulus):
            raise ValueError(f"stimulus must be finite, got {stimulus}")
        if not math.isfinite(compliance) or compliance <= 0.0:
            raise ValueError(f"compliance must be a finite positive number, got {compliance}")


# ============================================================================
# 4. Standard Concrete Electrical Loads
# ============================================================================

class ResistorLoad(ElectricalLoadContract):
    """
    Simulated linear resistor load with optional noise and temperature coefficient.

    Ohm's Law:
        V = I * R
        I = V / R
    """

    def __init__(
        self,
        resistance: float = 1000.0,
        noise_std: float = 0.0,
        temp_coeff: float = 0.0,
        nominal_temp: float = 300.0,
        seed: Optional[int] = None,
        start_time: float = 0.0,
    ) -> None:
        super().__init__(seed=seed, start_time=start_time)
        if not math.isfinite(resistance) or resistance <= 0.0:
            raise ValueError(f"resistance must be a positive finite number, got {resistance}")
        if not math.isfinite(noise_std) or noise_std < 0.0:
            raise ValueError(f"noise_std must be non-negative, got {noise_std}")
        self._nominal_resistance = float(resistance)
        self._noise_std = float(noise_std)
        self._temp_coeff = float(temp_coeff)
        self._nominal_temp = float(nominal_temp)
        self._current_temp = float(nominal_temp)

    @property
    def nominal_resistance(self) -> float:
        """Base resistance in Ohms at nominal temperature."""
        return self._nominal_resistance

    @property
    def effective_resistance(self) -> float:
        """Current effective resistance in Ohms accounting for temperature."""
        delta_t = self._current_temp - self._nominal_temp
        return self._nominal_resistance * (1.0 + self._temp_coeff * delta_t)

    def set_temperature(self, temp_k: float) -> None:
        """Set device temperature in Kelvin."""
        if not math.isfinite(temp_k) or temp_k <= 0.0:
            raise ValueError(f"temperature must be positive, got {temp_k}")
        self._current_temp = float(temp_k)

    def reset(self, seed: Optional[int] = None, **kwargs: Any) -> None:
        """Reset temperature, timebase, and RNG."""
        self._current_temp = self._nominal_temp
        self._timebase.reset(start_time=kwargs.get("start_time", 0.0))
        effective_seed = seed if seed is not None else self._initial_seed
        self.seed(effective_seed)

    def evaluate(
        self,
        mode: LoadMode,
        stimulus: float,
        compliance: float,
        time: Optional[float] = None,
    ) -> LoadResponse:
        self._validate_inputs(stimulus, compliance)
        t = self._timebase.current_time if time is None else float(time)
        r = self.effective_resistance

        if mode == LoadMode.VOLTAGE_SOURCE:
            v_target = stimulus
            i_ideal = v_target / r
            noise = float(self._rng.normal(0.0, self._noise_std)) if self._noise_std > 0.0 else 0.0
            i_actual = i_ideal + noise

            # Current compliance check
            compliance_tripped = abs(i_actual) >= compliance
            if compliance_tripped:
                i_actual = math.copysign(compliance, i_actual)
                v_actual = i_actual * r
            else:
                v_actual = v_target

            apparent_r = v_actual / i_actual if i_actual != 0.0 else r
            return LoadResponse(
                voltage=v_actual,
                current=i_actual,
                compliance_tripped=compliance_tripped,
                time=t,
                resistance=apparent_r,
                state={"temperature_k": self._current_temp},
            )

        elif mode == LoadMode.CURRENT_SOURCE:
            i_target = stimulus
            v_ideal = i_target * r
            noise = float(self._rng.normal(0.0, self._noise_std * r)) if self._noise_std > 0.0 else 0.0
            v_actual = v_ideal + noise

            # Voltage compliance check
            compliance_tripped = abs(v_actual) >= compliance
            if compliance_tripped:
                v_actual = math.copysign(compliance, v_actual)
                i_actual = v_actual / r
            else:
                i_actual = i_target

            apparent_r = v_actual / i_actual if i_actual != 0.0 else r
            return LoadResponse(
                voltage=v_actual,
                current=i_actual,
                compliance_tripped=compliance_tripped,
                time=t,
                resistance=apparent_r,
                state={"temperature_k": self._current_temp},
            )
        else:
            raise ValueError(f"unsupported load mode: {mode}")


class DiodeLoad(ElectricalLoadContract):
    """
    Simulated p-n junction diode using the Shockley diode equation:

        I = I_s * (exp((V - I * R_s) / (n * V_T)) - 1)

    Supports forward bias, reverse saturation (-I_s), series resistance,
    and both voltage-source and current-source compliance.
    """

    K_B = 1.380649e-23  # J/K
    Q_E = 1.602176634e-19  # C

    def __init__(
        self,
        is_sat: float = 1e-12,
        n: float = 1.0,
        r_series: float = 0.0,
        temp_k: float = 300.0,
        noise_std: float = 0.0,
        seed: Optional[int] = None,
        start_time: float = 0.0,
    ) -> None:
        super().__init__(seed=seed, start_time=start_time)
        if not math.isfinite(is_sat) or is_sat <= 0.0:
            raise ValueError(f"is_sat must be a positive finite number, got {is_sat}")
        if not math.isfinite(n) or n <= 0.0:
            raise ValueError(f"ideality factor n must be positive, got {n}")
        if not math.isfinite(r_series) or r_series < 0.0:
            raise ValueError(f"r_series must be non-negative, got {r_series}")
        if not math.isfinite(temp_k) or temp_k <= 0.0:
            raise ValueError(f"temp_k must be positive, got {temp_k}")

        self._is_sat = float(is_sat)
        self._n = float(n)
        self._r_series = float(r_series)
        self._temp_k = float(temp_k)
        self._noise_std = float(noise_std)
        self._vt = (self.K_B * self._temp_k) / self.Q_E

    @property
    def thermal_voltage(self) -> float:
        """Thermal voltage V_T = k_B * T / q in Volts."""
        return self._vt

    def reset(self, seed: Optional[int] = None, **kwargs: Any) -> None:
        self._timebase.reset(start_time=kwargs.get("start_time", 0.0))
        effective_seed = seed if seed is not None else self._initial_seed
        self.seed(effective_seed)

    def _current_from_voltage(self, v_applied: float) -> float:
        """Solve for current given applied voltage across diode + series resistance."""
        nvt = self._n * self._vt
        if self._r_series == 0.0:
            arg = min(v_applied / nvt, 40.0)
            return float(self._is_sat * np.expm1(arg))

        # Newton-Raphson iteration for non-zero series resistance
        i = 0.0
        for _ in range(20):
            vd = v_applied - i * self._r_series
            arg = min(vd / nvt, 40.0)
            f = i - self._is_sat * float(np.expm1(arg))
            df = 1.0 + (self._is_sat * self._r_series / nvt) * math.exp(arg)
            delta = f / df
            i -= delta
            if abs(delta) < 1e-12:
                break
        return i

    def _voltage_from_current(self, i_applied: float) -> float:
        """Compute terminal voltage given forward or reverse current."""
        nvt = self._n * self._vt
        # If current is below or equal to -I_s, clamp to deep reverse
        if i_applied <= -self._is_sat:
            return -100.0  # Large reverse voltage
        ratio = i_applied / self._is_sat
        vd = nvt * math.log1p(ratio)
        return vd + i_applied * self._r_series

    def evaluate(
        self,
        mode: LoadMode,
        stimulus: float,
        compliance: float,
        time: Optional[float] = None,
    ) -> LoadResponse:
        self._validate_inputs(stimulus, compliance)
        t = self._timebase.current_time if time is None else float(time)

        if mode == LoadMode.VOLTAGE_SOURCE:
            v_target = stimulus
            i_ideal = self._current_from_voltage(v_target)
            noise = float(self._rng.normal(0.0, self._noise_std)) if self._noise_std > 0.0 else 0.0
            i_actual = i_ideal + noise

            compliance_tripped = abs(i_actual) >= compliance
            if compliance_tripped:
                i_actual = math.copysign(compliance, i_actual)
                v_actual = self._voltage_from_current(i_actual)
            else:
                v_actual = v_target

            apparent_r = v_actual / i_actual if i_actual != 0.0 else float("inf")
            return LoadResponse(
                voltage=v_actual,
                current=i_actual,
                compliance_tripped=compliance_tripped,
                time=t,
                resistance=apparent_r,
                state={"temperature_k": self._temp_k},
            )

        elif mode == LoadMode.CURRENT_SOURCE:
            i_target = stimulus
            v_ideal = self._voltage_from_current(i_target)
            noise = float(self._rng.normal(0.0, self._noise_std * 100.0)) if self._noise_std > 0.0 else 0.0
            v_actual = v_ideal + noise

            compliance_tripped = abs(v_actual) >= compliance
            if compliance_tripped:
                v_actual = math.copysign(compliance, v_actual)
                i_actual = self._current_from_voltage(v_actual)
            else:
                i_actual = i_target

            apparent_r = v_actual / i_actual if i_actual != 0.0 else float("inf")
            return LoadResponse(
                voltage=v_actual,
                current=i_actual,
                compliance_tripped=compliance_tripped,
                time=t,
                resistance=apparent_r,
                state={"temperature_k": self._temp_k},
            )
        else:
            raise ValueError(f"unsupported load mode: {mode}")


class CapacitiveLoad(ElectricalLoadContract):
    """
    Simulated stateful capacitive load tracking stored charge Q and voltage over time.

    Current-voltage relationship:
        I(t) = C * dV/dt + V / R_leak
        V(t) = V(t_0) + (1/C) * integral(I(t) dt)
    """

    def __init__(
        self,
        capacitance: float = 1e-9,
        leakage_resistance: float = 1e9,
        initial_voltage: float = 0.0,
        seed: Optional[int] = None,
        start_time: float = 0.0,
    ) -> None:
        super().__init__(seed=seed, start_time=start_time)
        if not math.isfinite(capacitance) or capacitance <= 0.0:
            raise ValueError(f"capacitance must be positive, got {capacitance}")
        if not math.isfinite(leakage_resistance) or leakage_resistance <= 0.0:
            raise ValueError(f"leakage_resistance must be positive, got {leakage_resistance}")
        self._c = float(capacitance)
        self._r_leak = float(leakage_resistance)
        self._initial_voltage = float(initial_voltage)
        self._voltage = float(initial_voltage)
        self._last_time = float(start_time)

    @property
    def capacitance(self) -> float:
        """Capacitance in Farads."""
        return self._c

    @property
    def stored_charge(self) -> float:
        """Stored charge Q = C * V in Coulombs."""
        return self._c * self._voltage

    def reset(self, seed: Optional[int] = None, **kwargs: Any) -> None:
        start_t = kwargs.get("start_time", 0.0)
        self._timebase.reset(start_time=start_t)
        self._voltage = self._initial_voltage
        self._last_time = float(start_t)
        effective_seed = seed if seed is not None else self._initial_seed
        self.seed(effective_seed)

    def evaluate(
        self,
        mode: LoadMode,
        stimulus: float,
        compliance: float,
        time: Optional[float] = None,
    ) -> LoadResponse:
        self._validate_inputs(stimulus, compliance)
        t = self._timebase.current_time if time is None else float(time)
        dt = max(t - self._last_time, 1e-9)

        if mode == LoadMode.VOLTAGE_SOURCE:
            v_target = stimulus
            dv = v_target - self._voltage
            i_cap = self._c * (dv / dt)
            i_leak = v_target / self._r_leak
            i_total = i_cap + i_leak

            compliance_tripped = abs(i_total) >= compliance
            if compliance_tripped:
                i_actual = math.copysign(compliance, i_total)
                # Capacitor voltage charges as far as compliant current permits
                dv_permitted = (i_actual - i_leak) * (dt / self._c)
                self._voltage += dv_permitted
            else:
                i_actual = i_total
                self._voltage = v_target

            self._last_time = t
            apparent_r = self._voltage / i_actual if i_actual != 0.0 else float("inf")
            return LoadResponse(
                voltage=self._voltage,
                current=i_actual,
                compliance_tripped=compliance_tripped,
                time=t,
                resistance=apparent_r,
                state={"charge_coulombs": self.stored_charge},
            )

        elif mode == LoadMode.CURRENT_SOURCE:
            i_target = stimulus
            i_leak = self._voltage / self._r_leak
            dv = (i_target - i_leak) * (dt / self._c)
            v_new = self._voltage + dv

            compliance_tripped = abs(v_new) >= compliance
            if compliance_tripped:
                self._voltage = math.copysign(compliance, v_new)
                i_actual = self._voltage / self._r_leak
            else:
                self._voltage = v_new
                i_actual = i_target

            self._last_time = t
            apparent_r = self._voltage / i_actual if i_actual != 0.0 else float("inf")
            return LoadResponse(
                voltage=self._voltage,
                current=i_actual,
                compliance_tripped=compliance_tripped,
                time=t,
                resistance=apparent_r,
                state={"charge_coulombs": self.stored_charge},
            )
        else:
            raise ValueError(f"unsupported load mode: {mode}")


# ============================================================================
# 5. Field-Responsive Material Contract
# ============================================================================

class FieldResponsiveMaterialContract(SimulationRole, ABC):
    """
    Contract for simulated materials responding to an applied magnetic field.

    Canonical declared units:
    - field: Oersteds (Oe)
    - magnetization: Dimensionless normalized [-1, 1] or emu/cm^3
    - time: Seconds (s)
    """

    _UNITS: Mapping[str, str] = MappingProxyType({
        "field": "Oe",
        "magnetization": "dimensionless",
        "time": "s",
    })

    @property
    def declared_units(self) -> Mapping[str, str]:
        return self._UNITS

    @abstractmethod
    def apply_field(self, field: float, time: Optional[float] = None) -> float:
        """
        Apply one magnetic field value in Oe and return resulting magnetization.
        """
        raise NotImplementedError

    @abstractmethod
    def response(
        self,
        fields: Sequence[float],
        times: Optional[Sequence[float]] = None,
    ) -> np.ndarray:
        """
        Apply an ordered field history and return resulting magnetization array.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def current_field(self) -> float:
        """Current magnetic field in Oe."""
        raise NotImplementedError

    @property
    @abstractmethod
    def magnetization(self) -> float:
        """Current magnetization."""
        raise NotImplementedError


# ============================================================================
# 6. Angle-Dependent Resistance Contract (Magneto-Transport / AMR)
# ============================================================================

class AngleDependentResistanceContract(SimulationRole, ABC):
    """
    Contract for simulated magneto-transport / anisotropic magnetoresistance materials.

    Canonical declared units:
    - angle: Degrees (deg)
    - field: Oersteds (Oe)
    - resistance: Ohms (Ohm)
    - x: Volts (V)
    - y: Volts (V)
    - time: Seconds (s)
    """

    _UNITS: Mapping[str, str] = MappingProxyType({
        "angle": "deg",
        "field": "Oe",
        "resistance": "Ohm",
        "x": "V",
        "y": "V",
        "time": "s",
    })

    @property
    def declared_units(self) -> Mapping[str, str]:
        return self._UNITS

    @abstractmethod
    def get_resistance(
        self,
        angle: Optional[float] = None,
        field: Optional[float] = None,
        time: Optional[float] = None,
    ) -> float:
        """
        Calculate sample resistance in Ohms for commanded angle and field.
        """
        raise NotImplementedError

    @abstractmethod
    def get_voltage_response(
        self,
        excitation_current: float = 1e-3,
        angle: Optional[float] = None,
        field: Optional[float] = None,
        time: Optional[float] = None,
    ) -> Union[VoltageResponse, Tuple[float, float]]:
        """
        Simulate lock-in amplifier (X, Y) dual-channel response in Volts.

        Args:
            excitation_current: Sample excitation current in Amperes.
            angle: Angle in degrees.
            field: Field in Oe.
            time: Simulated timestamp in seconds.

        Returns:
            Tuple of (X, Y) voltages in Volts.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def current_angle(self) -> float:
        """Current orientation angle in degrees."""
        raise NotImplementedError

    @property
    @abstractmethod
    def current_field(self) -> float:
        """Current applied magnetic field in Oe."""
        raise NotImplementedError


# ============================================================================
# 7. Waveform-Responsive Material Contract (Dielectric / Ferroelectric)
# ============================================================================

class WaveformResponsiveMaterialContract(SimulationRole, ABC):
    """
    Contract for dynamic materials responding to time-varying voltage waveforms.

    Canonical declared units:
    - voltage: Volts (V)
    - time: Seconds (s)
    - current: Amperes (A)
    - polarization: Microcoulombs per square centimeter (uC/cm^2)
    """

    _UNITS: Mapping[str, str] = MappingProxyType({
        "voltage": "V",
        "time": "s",
        "current": "A",
        "polarization": "uC/cm^2",
    })

    @property
    def declared_units(self) -> Mapping[str, str]:
        return self._UNITS

    @abstractmethod
    def apply_waveform(self, v: Sequence[float], t: Sequence[float]) -> None:
        """
        Apply an excitation voltage waveform v(t) and compute material response.
        """
        raise NotImplementedError

    @abstractmethod
    def get_voltage_response(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Return the response voltage across the sense load and corresponding time array.

        Returns:
            Tuple of (voltage_array, time_array) in standard SI units (V, s).
        """
        raise NotImplementedError


# ============================================================================
# 8. Virtual Driver Hook Protocols (Dependency Injection)
# ============================================================================

DmmVoltageReaderHook = Callable[[], float]
LockinTransportHook = Callable[[], Tuple[float, float]]
ScopeChannelHook = Callable[[int], Tuple[np.ndarray, np.ndarray]]
CalibratorFieldHook = Callable[[float], None]
StepperAngleHook = Callable[[float], None]
