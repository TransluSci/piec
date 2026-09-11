"""
AMR (Anisotropic Magnetoresistance) and MagnetoTransport measurement module.

Standardized for Checkpoint 24b of MEASUREMENT_STANDARDIZATION_PLAN.md:
- MagnetoTransport base lifecycle imported from ._magneto_transport_base;
- AMR subclasses MagnetoTransport with shared BaseMeasurement lifecycle;
- Target API and schema: schema 'amr', version 1;
- Plain lowercase columns: ['angle', 'field', 'x', 'y'] with canonical units
  {'angle': 'deg', 'field': 'Oe', 'x': 'V', 'y': 'V'};
- Zero instrument I/O in __init__;
- Setup profile composition (AMRSetupProfile) with FieldSource, FieldReader,
  TransportReadout, OrientationController;
- Lock-in settings preservation by default (readout_configuration='preserve');
- Mandatory declared excitation shutdown policy before energizing;
- Attempt-all safe shutdown with connection retention on SafetyStatus.UNSAFE;
- Repaired AMR-ANGLE-001: exact angle tracking without extra endpoint motor step;
- Fully removed _LegacyMagnetoTransport.
"""

from __future__ import annotations

import math
from pathlib import Path
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import numpy as np
import pandas as pd

from piec.measurement.contracts import (
    HardwareSafetyError,
    MeasurementSnapshot,
    ReservationToken,
    RunRequest,
    RunState,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
)
from ._magneto_transport_base import MagnetoTransport

if TYPE_CHECKING:
    from piec.measurement.adapters.amr import AMRSetupProfile


class AMR(MagnetoTransport):
    """
    Performs the AMR (Anisotropic Magnetoresistance) angular sweep measurement.

    Standardized on the BaseMeasurement lifecycle and MagnetoTransport base.
    Rotates the sample angle, measures electrical transport signals (in-phase x,
    quadrature y), and preserves manual lock-in settings by default.
    """

    mtype = "amr"
    measurement_schema = "amr"
    measurement_schema_version = 1
    supports_pause = True
    ordered_columns: Tuple[str, ...] = ("angle", "field", "x", "y")
    column_units = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
    raw_column_units = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}

    def __init__(
        self,
        dmm: Any = None,
        calibrator: Any = None,
        stepper: Any = None,
        lockin: Any = None,
        *,
        field: float = 100.0,
        angle_step: float = 15.0,
        total_angle: float = 360.0,
        start_angle: float = 0.0,
        amplitude: float = 1.0,
        frequency: float = 10.0,
        measure_time: float = 1.0,
        sensitivity: str = "50uv/pa",
        settling_time: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        voltage_calibration: float = 10000.0,
        profile: Optional[AMRSetupProfile] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        readout_configuration: Optional[str] = None,
        excitation_source: str = "internal",
        shutdown_handler: Optional[Callable[[], None]] = None,
        external_source_owner: Optional[str] = None,
        field_settling_time: float = 0.0,
        record_field_readback: bool = False,
        raw_window_points: int = 100,
    ) -> None:
        """
        Initialize AMR measurement without performing hardware I/O.
        """
        self.angle_step = float(angle_step)
        if not math.isfinite(self.angle_step) or self.angle_step == 0:
            raise ValueError(f"angle_step must be a nonzero finite number, got {angle_step!r}")

        self.start_angle = float(start_angle)
        if not math.isfinite(self.start_angle):
            raise ValueError(f"start_angle must be finite, got {start_angle!r}")

        self.total_angle = float(total_angle)
        if not math.isfinite(self.total_angle) or (self.total_angle - self.start_angle) * self.angle_step < 0:
            raise ValueError(f"total_angle must be finite and follow the angle_step direction, got {total_angle!r}")

        self.amplitude = float(amplitude)
        if not math.isfinite(self.amplitude) or self.amplitude <= 0:
            raise ValueError(f"amplitude must be a positive finite number, got {amplitude!r}")

        self.frequency = float(frequency)
        if not math.isfinite(self.frequency) or self.frequency <= 0:
            raise ValueError(f"frequency must be a positive finite number, got {frequency!r}")

        self.measure_time = float(measure_time)
        if not math.isfinite(self.measure_time) or self.measure_time < 0:
            raise ValueError(f"measure_time must be non-negative and finite, got {measure_time!r}")

        self.sensitivity = str(sensitivity)

        self.settling_time = float(settling_time)
        if not math.isfinite(self.settling_time) or self.settling_time < 0:
            raise ValueError(f"settling_time must be non-negative and finite, got {settling_time!r}")

        if type(record_field_readback) is not bool:
            raise ValueError("record_field_readback must be bool")
        self.record_field_readback = record_field_readback
        if type(raw_window_points) is not int or raw_window_points <= 0:
            raise ValueError("raw_window_points must be a positive integer")
        self.raw_window_points = raw_window_points

        if profile is None and calibrator is not None and stepper is not None and lockin is not None:
            from .adapters.amr import AMRSetupProfile

            profile = AMRSetupProfile.from_instruments(
                dmm=dmm,
                calibrator=calibrator,
                arduino=stepper,
                lockin=lockin,
                field_calibration=float(voltage_calibration),
                reader_calibration=float(voltage_calibration) if dmm is not None else None,
                readout_configuration=readout_configuration or "preserve",
                excitation_source=excitation_source,
                amplitude=self.amplitude,
                frequency=self.frequency,
                sensitivity=self.sensitivity,
                settling_time=0.0,
                shutdown_handler=shutdown_handler,
                external_source_owner=external_source_owner,
            )
            dmm = calibrator = stepper = lockin = shutdown_handler = external_source_owner = None

        info: Dict[str, Any] = dict(metadata or {})
        field_val = float(field)
        unit = profile.field_source.field_unit if profile else "Oe"
        info.update(
            angle_step=self.angle_step,
            start_angle=self.start_angle,
            angle_basis="commanded_quantized",
            total_angle=self.total_angle,
            field=field_val,
            field_unit=unit,
            frequency=self.frequency,
            amplitude=self.amplitude,
        )

        super().__init__(
            dmm=dmm,
            calibrator=calibrator,
            stepper=stepper,
            lockin=lockin,
            field=field_val,
            output_dir=output_dir,
            profile=profile,
            voltage_calibration=voltage_calibration,
            metadata=info,
            readout_configuration=readout_configuration,
            excitation_source=excitation_source,
            shutdown_handler=shutdown_handler,
            external_source_owner=external_source_owner,
            field_settling_time=field_settling_time,
        )

        self.measurement_metadata.update(
            amplitude=self.transport_readout.amplitude if self.transport_readout else self.amplitude,
            frequency=self.transport_readout.frequency if self.transport_readout else self.frequency,
            measure_time=self.measure_time,
        )

        # AMR primary schema uses 4 canonical columns unless field readback columns are explicitly requested
        if not self.record_field_readback:
            canonical_units = {"angle": "deg", "field": unit, "x": "V", "y": "V"}
            self.column_units = canonical_units
            self.raw_column_units = canonical_units
            self.ordered_columns = ("angle", "field", "x", "y")

    def _compute_angles(self) -> List[float]:
        """Requested angles including the exact final endpoint, in either direction."""
        count = abs((self.total_angle - self.start_angle) / self.angle_step)
        if not math.isfinite(count) or count > 1_000_000:
            raise ValueError("Sweep exceeds one million intervals")
        angles = [self.start_angle + i * self.angle_step for i in range(math.floor(count) + 1)]
        if math.isclose(angles[-1], self.total_angle, rel_tol=0, abs_tol=1e-10):
            angles[-1] = self.total_angle
        else:
            angles.append(self.total_angle)
        return angles

    def _validate_options(self, options):
        super()._validate_options(options)
        # Validate every quantized move before excitation/field configuration.
        current = self.orientation_controller.current_angle
        for target in self._compute_angles():
            _, current = self.orientation_controller.plan_move(target, current)

    def _measure_signals(self) -> Dict[str, float]:
        """Measure lock-in signals, averaging over measure_time with cooperative pause/stop."""
        duration = self.measure_time
        dt = 0.1
        if self._coordinator.is_stop_requested:
            return {}
        if duration <= 0:
            return self.transport_readout.read_signals()

        x_list: List[float] = []
        y_list: List[float] = []
        start_time = time.monotonic()
        while not self._coordinator.is_stop_requested:
            sig = self.transport_readout.read_signals()
            x_list.append(sig["x"])
            y_list.append(sig["y"])
            elapsed = time.monotonic() - start_time
            if elapsed >= duration - 1e-9:
                break
            if not self._wait(min(dt, max(0.001, duration - elapsed)), pause=True):
                break

        if not x_list or self._coordinator.is_stop_requested:
            return {}
        return {"x": float(np.mean(x_list)), "y": float(np.mean(y_list))}

    def _capture_data(
        self,
        request: RunRequest,
        on_update: Optional[Callable[[Any], None]] = None,
    ) -> pd.DataFrame:
        """
        Acquire AMR angular sweep data.

        Rotates the stepper motor to each commanded angle, pauses/settles,
        measures lock-in transport response, verifies magnetic field, and
        emits bounded live snapshots. No extra motor movement occurs after the final angle.
        """
        if self.profile is None:
            raise ValueError("AMR requires instruments or profile to execute")

        angles = self._compute_angles()
        total_steps = len(angles)
        rows: List[Dict[str, Any]] = []

        for step_idx, target_angle in enumerate(angles):
            # Check stop/pause before moving
            if self._coordinator.is_stop_requested:
                break
            if not self._wait(pause=True):
                break

            # Rotate stepper motor to exact target angle
            self.orientation_controller.move_to_angle(target_angle, settle=False)

            # Settle post-motion
            if not self._wait(max(self.settling_time, self.orientation_controller.settling_time), pause=True):
                break

            # Check stop/pause before measuring
            if not self._wait(pause=True):
                break

            signals = self._measure_signals()
            if self._coordinator.is_stop_requested or not signals:
                break

            row: Dict[str, Any] = {
                "angle": float(self.orientation_controller.current_angle),
                "field": float(self.field),
                "x": float(signals["x"]),
                "y": float(signals["y"]),
            }

            if self.record_field_readback and self.field_reader:
                measured, _ = self.field_reader.read_field()
                self.field_reader.verify_field(self.field, measured)
                row.update(
                    field_measured=float(measured),
                    field_time=float(time.monotonic() - self._field_time_origin),
                )
            elif self.field_reader:
                # Field verification is performed even when readback columns are not recorded
                measured, _ = self.field_reader.read_field()
                self.field_reader.verify_field(self.field, measured)

            if self._coordinator.is_stop_requested:
                break
            rows.append(row)

            # Update in-progress views and emit snapshot
            current_df = pd.DataFrame(rows, columns=self.ordered_columns)
            self._raw_data = current_df.copy()
            self._data = current_df.copy()
            snapshot = self.publish_snapshot(
                views={"raw_window": current_df.tail(self.raw_window_points)},
                completed_steps=step_idx + 1,
                total_steps=total_steps,
            )
            if on_update:
                on_update(snapshot)

        result_df = pd.DataFrame(rows, columns=self.ordered_columns)
        self._raw_data = result_df.copy()
        self._data = result_df.copy()
        return result_df


# ----------------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------------

def convert_steps_to_angle(steps: int, steps_per_revolution: int = 200) -> float:
    """Helper function to convert steps to an angle in degrees."""
    if not isinstance(steps_per_revolution, (int, np.integer)) or steps_per_revolution <= 0:
        raise ValueError(f"steps_per_revolution must be a positive integer, got {steps_per_revolution!r}")
    return float(steps) * 360.0 / float(steps_per_revolution)


def convert_angle_to_steps(angle: float, steps_per_revolution: int = 200) -> int:
    """Helper function to convert an angle in degrees to steps."""
    if not isinstance(steps_per_revolution, (int, np.integer)) or steps_per_revolution <= 0:
        raise ValueError(f"steps_per_revolution must be a positive integer, got {steps_per_revolution!r}")
    angle_f = float(angle)
    if not math.isfinite(angle_f):
        raise ValueError(f"angle must be a finite number, got {angle!r}")
    return int(round(angle_f * float(steps_per_revolution) / 360.0))


def convert_field_to_voltage(field: float, voltage_calibration: float = 10000.0) -> float:
    """
    Convert magnetic field in Oe to calibrator control voltage in V.
    Default calibration is 10000.0 Oe/V (0.01 V for 100 Oe).
    """
    field_f = float(field)
    if not math.isfinite(field_f):
        raise ValueError(f"field must be a finite number, got {field!r}")
    cal_f = float(voltage_calibration)
    if not math.isfinite(cal_f) or cal_f <= 0:
        raise ValueError(f"voltage_calibration must be a positive finite number, got {voltage_calibration!r}")
    return field_f / cal_f


def convert_voltage_to_field(voltage: float, voltage_calibration: float = 10000.0) -> float:
    """
    Convert sensor / calibrator voltage in V to magnetic field in Oe.
    Default calibration is 10000.0 Oe/V (100 Oe for 0.01 V).
    """
    v_f = float(voltage)
    if not math.isfinite(v_f):
        raise ValueError(f"voltage must be a finite number, got {voltage!r}")
    cal_f = float(voltage_calibration)
    if not math.isfinite(cal_f) or cal_f <= 0:
        raise ValueError(f"voltage_calibration must be a positive finite number, got {voltage_calibration!r}")
    return v_f * cal_f


__all__ = [
    "MagnetoTransport",
    "AMR",
    "convert_steps_to_angle",
    "convert_angle_to_steps",
    "convert_field_to_voltage",
    "convert_voltage_to_field",
]
