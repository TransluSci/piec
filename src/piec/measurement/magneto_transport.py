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

import json
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

from piec.measurement.base import BaseMeasurement
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
from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.dmm.dmm import DMM
from piec.drivers.lockin.lockin import Lockin
from piec.drivers.stepper_motor.stepper_motor import Stepper
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.drivers.awg.awg import Awg

from piec.measurement.adapters.amr import (
    AMRSetupProfile,
    SampleExcitation,
    convert_steps_to_angle,
    convert_angle_to_steps,
    convert_field_to_voltage,
    convert_voltage_to_field,
)


class TuningStatus:
    """Result of an interactive excitation test or tuning check."""

    def __init__(
        self,
        x: float,
        y: float,
        voltage: float,
        resistance: Optional[float],
        overloaded: bool,
        active_settings: Dict[str, Any],
    ):
        self.x = float(x)
        self.y = float(y)
        self.voltage = float(voltage)
        self.resistance = float(resistance) if resistance is not None else None
        self.overloaded = bool(overloaded)
        self.active_settings = dict(active_settings)

    def __repr__(self) -> str:
        r_str = f"{self.resistance:.3f} Ohm" if self.resistance is not None else "N/A"
        return (
            f"TuningStatus(x={self.x:.6e} V, y={self.y:.6e} V, "
            f"resistance={r_str}, overloaded={self.overloaded}, active_settings={self.active_settings})"
        )


class MagnetoTransport(BaseMeasurement):
    """Acquire a transport point using a declared setup and shared execution ownership.

    Constructors do no I/O. Use run_experiment or a session for hardware work.
    Field units come from the setup; readback remains separate from commanded field.
    The excitation shutdown handler is mandatory before any execution.
    Pause acts before acquisition, retains the field, and is woken by Stop.
    """
    mtype = "magneto_transport"
    measurement_schema = "amr"
    measurement_schema_version = 1
    supports_pause = True
    ordered_columns = ("angle", "field", "x", "y")
    column_units = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
    raw_column_units = column_units

    def __init__(
        self,
        dmm: Optional[DMM] = None,
        calibrator: Optional[Union[DCCalibrator, Sourcemeter]] = None,
        stepper: Optional[Stepper] = None,
        lockin: Optional[Lockin] = None,
        *,
        field=0.0,
        output_dir=None,
        profile=None,
        voltage_calibration=10000.0,
        metadata=None,
        readout_configuration=None,
        excitation_source="internal",
        shutdown_handler=None,
        external_source_owner=None,
        field_settling_time=0.0,
        readout: Optional[Union[Lockin, DMM]] = None,
        current_source: Optional[Union[Sourcemeter, Awg]] = None,
        field_source: Optional[Union[DCCalibrator, Sourcemeter]] = None,
        field_reader: Optional[DMM] = None,
        current: float = 1e-4,
        compliance: float = 2.0,
    ):
        self.field = float(field)
        self.voltage_calibration = float(voltage_calibration)
        self.field_settling_time = float(field_settling_time)
        if not math.isfinite(self.field):
            raise ValueError("field must be a finite number")
        if not math.isfinite(self.voltage_calibration) or self.voltage_calibration <= 0:
            raise ValueError("voltage_calibration must be a positive finite number")
        if not math.isfinite(self.field_settling_time) or self.field_settling_time < 0:
            raise ValueError("field_settling_time must be non-negative and finite")

        eff_field_source = field_source if field_source is not None else calibrator
        eff_stepper = stepper
        eff_readout = readout if readout is not None else lockin
        if eff_readout is None and current_source is not None and dmm is not None:
            eff_readout = dmm
        eff_field_reader = field_reader if field_reader is not None else (dmm if (dmm is not None and dmm is not eff_readout) else None)

        if profile is not None:
            if not isinstance(profile, AMRSetupProfile):
                raise TypeError("profile must be an AMRSetupProfile")
            if any(value is not None for value in (dmm, calibrator, stepper, lockin, shutdown_handler, external_source_owner, current_source, readout, field_source, field_reader)):
                raise ValueError("Supply a profile or individual instruments/settings, not both")
        elif eff_field_source is not None and eff_stepper is not None and eff_readout is not None:
            profile = AMRSetupProfile.from_instruments(
                dmm=dmm,
                calibrator=calibrator,
                arduino=stepper,
                lockin=lockin,
                field_source=eff_field_source,
                readout=eff_readout,
                current_source=current_source,
                field_reader=eff_field_reader,
                current=current,
                compliance=compliance,
                field_calibration=self.voltage_calibration,
                reader_calibration=self.voltage_calibration if eff_field_reader is not None else None,
                readout_configuration=readout_configuration or "preserve",
                excitation_source="external" if current_source is not None else excitation_source,
                shutdown_handler=shutdown_handler,
                external_source_owner=external_source_owner,
            )
        self._profile = profile
        self.dmm = profile.field_reader.instrument if profile and profile.field_reader else (dmm if dmm is not eff_readout else None)
        self.calibrator = profile.field_source.instrument if profile else eff_field_source
        self.stepper = profile.orientation_controller.instrument if profile else eff_stepper
        self.lockin = profile.transport_readout.instrument if profile and isinstance(profile.transport_readout.instrument, Lockin) else (lockin if isinstance(lockin, Lockin) else None)
        self._readout_inst = profile.transport_readout.instrument if profile else eff_readout
        self._current_source_inst = profile.sample_excitation.instrument if profile and profile.sample_excitation else current_source
        self.readout_configuration = self._policy(readout_configuration if readout_configuration is not None
            else profile.transport_readout.readout_configuration if profile else "preserve")
        unit = profile.field_source.field_unit if profile else "Oe"
        units = {"angle": "deg", "field": unit, "x": "V", "y": "V"}
        if profile and profile.field_reader:
            units.update(field_measured=profile.field_reader.field_unit, field_time="s")
        self.ordered_columns = tuple(units)
        info = dict(metadata or {})
        sig_mode = profile.transport_readout.signal_mode if profile else "lockin_xy"
        info.update(field=self.field, field_basis="commanded", signal_mode=sig_mode)
        if profile:
            source = profile.field_source
            info.update(field_source_mode=source.mode, field_source_name=source.name,
                        source_output_unit=source.output_unit,
                        excitation_source=profile.transport_readout.excitation_source,
                        excitation_settings_provenance="user_declared_unverified")
            if source.mode == "linear":
                info["field_source_scale"] = source.calibration
            elif source.mode == "table":
                info["field_source_calibration_json"] = json.dumps(source.calibration.to_dict(), separators=(",", ":"))
            if profile.transport_readout.external_source_owner:
                info["external_source_owner"] = profile.transport_readout.external_source_owner
            if profile.field_reader:
                info.update(field_reader_name=profile.field_reader.name,
                            field_reader_mode=profile.field_reader.mode,
                            field_absolute_tolerance=profile.field_reader.absolute_tolerance,
                            field_relative_tolerance=profile.field_reader.relative_tolerance,
                            field_mismatch_policy=profile.field_reader.mismatch_policy)
                reader = profile.field_reader
                if reader.mode == "linear":
                    info["field_reader_scale"] = reader.calibration
                elif reader.mode == "table":
                    info["field_reader_calibration_json"] = json.dumps(reader.calibration.to_dict(), separators=(",", ":"))
        super().__init__(output_dir=output_dir, measurement_schema="amr",
                         column_units=units, raw_column_units=units, metadata=info)

    @staticmethod
    def _policy(value):
        if value not in ("preserve", "configure"):
            raise ValueError("readout_configuration must be 'preserve' or 'configure'")
        return value

    @property
    def profile(self):
        return self._profile

    @property
    def field_source(self):
        return self.profile.field_source if self.profile else None

    @property
    def field_reader(self):
        return self.profile.field_reader if self.profile else None

    @property
    def transport_readout(self):
        return self.profile.transport_readout if self.profile else None

    @property
    def sample_excitation(self):
        return self.profile.sample_excitation if self.profile else None

    @property
    def current_source(self):
        return self.sample_excitation.instrument if (self.sample_excitation and self.sample_excitation.source_type == "external") else self._current_source_inst

    @property
    def readout(self):
        return self.profile.transport_readout.instrument if self.profile else self._readout_inst

    @property
    def orientation_controller(self):
        return self.profile.orientation_controller if self.profile else None

    @property
    def metadata(self):
        return self.measurement_metadata

    def test_excitation(
        self,
        current: Optional[float] = None,
        amplitude: Optional[float] = None,
        frequency: Optional[float] = None,
        duration: float = 0.2,
    ) -> TuningStatus:
        """
        Safely test excitation and read live response without running a sweep.
        Leaves hardware safely de-energized upon exit.
        """
        if self.profile is None or self.sample_excitation is None:
            raise ValueError("Instruments or profile required to test excitation")

        if current is not None:
            self.sample_excitation.current = float(current)
        if amplitude is not None:
            self.sample_excitation.amplitude = float(amplitude)
        if frequency is not None:
            self.sample_excitation.frequency = float(frequency)

        try:
            self.sample_excitation.configure()
            if duration > 0:
                time.sleep(duration)
            signals = self.transport_readout.read_signals()
            x = float(signals.get("x", 0.0))
            y = float(signals.get("y", 0.0))
            v = float(signals.get("voltage", math.hypot(x, y)))
            overloaded = self.transport_readout.check_overload()
            active_settings = self.transport_readout.get_active_settings()

            eff_current = self.sample_excitation.current if self.sample_excitation.source_type == "external" else None
            resistance = (v / eff_current) if (eff_current is not None and eff_current != 0) else None

            return TuningStatus(
                x=x,
                y=y,
                voltage=v,
                resistance=resistance,
                overloaded=overloaded,
                active_settings=active_settings,
            )
        finally:
            self.sample_excitation.safe_shutdown()

    def auto_gain(self) -> Optional[str]:
        """Trigger auto-gain on the lock-in amplifier and return resulting sensitivity."""
        if self.profile and self.transport_readout:
            new_sens = self.transport_readout.auto_gain()
            if new_sens:
                self.measurement_metadata["sensitivity"] = new_sens
            return new_sens
        return None

    def _validate_options(self, options):
        super()._validate_options(options)
        opts = options or {}
        unknown = set(opts) - {"configure_lockin", "readout_configuration"}
        if unknown:
            raise ValueError(f"Unknown option: {', '.join(sorted(unknown))}")
        if "configure_lockin" in opts and type(opts["configure_lockin"]) is not bool:
            raise ValueError("configure_lockin must be bool")
        if "readout_configuration" in opts:
            self._policy(opts["readout_configuration"])
        if "configure_lockin" in opts and "readout_configuration" in opts:
            raise ValueError("Specify only one readout configuration option")
        if self.profile is None:
            raise ValueError("MagnetoTransport requires instruments or profile to execute")
        if not callable(self.transport_readout.shutdown_handler):
            raise HardwareSafetyError("Excitation shutdown handler required before energizing, but none declared")
        # Validate the entire field command before lock-in settings can energize excitation.
        self.field_source.compute_output(self.field)

    def _wait(self, duration=0.0, *, pause=False):
        deadline = time.monotonic() + duration
        while not self._coordinator.is_stop_requested:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not (pause and self._coordinator.is_pause_requested):
                return True
            time.sleep(min(.02, max(0.001, remaining)) if remaining > 0 else .02)
        return False

    def _configure_instruments(self, request):
        self._validate_options(request.options)
        self._field_time_origin = time.monotonic()
        for index, instrument in enumerate(self.profile.unique_instruments()):
            if self._coordinator.is_stop_requested:
                return
            identify = getattr(instrument, "idn", None)
            if callable(identify):
                self.measurement_metadata[f"instrument_{index}"] = str(identify())
        opts = request.options or {}
        policy = opts.get("readout_configuration", self.readout_configuration)
        if "configure_lockin" in opts:
            policy = "configure" if opts["configure_lockin"] else "preserve"
        self.measurement_metadata["readout_configuration"] = policy
        if self._coordinator.is_stop_requested:
            return

        # Configure excitation
        if self.sample_excitation:
            self.sample_excitation.configure()

        saved = self.transport_readout.readout_configuration
        try:
            self.transport_readout.readout_configuration = policy
            self.transport_readout.configure()
            if policy != "preserve":
                active = self.transport_readout.get_active_settings()
                for k, v in active.items():
                    self.measurement_metadata[f"active_{k}"] = v
                if "sensitivity" in active and "sensitivity" not in self.measurement_metadata:
                    self.measurement_metadata["sensitivity"] = active["sensitivity"]
        finally:
            self.transport_readout.readout_configuration = saved
        if self._coordinator.is_stop_requested:
            return
        self.field_source.set_field(self.field)
        if not self._wait(self.field_settling_time):
            return
        if self.field_reader:
            self.field_reader.verify_field(self.field)  # Errors and fail-policy mismatches propagate.

    def _capture_data(self, request, on_update=None):
        if not self._wait(pause=True):
            return pd.DataFrame(columns=self.ordered_columns)
        row = {"angle": float(self.orientation_controller.current_angle), "field": self.field}
        if self.field_reader:
            measured, _ = self.field_reader.read_field()
            self.field_reader.verify_field(self.field, measured)
            row.update(field_measured=measured, field_time=time.monotonic() - self._field_time_origin)
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=self.ordered_columns)
        row.update(self.transport_readout.read_signals())
        frame = pd.DataFrame([row], columns=self.ordered_columns)
        self._raw_data = frame.copy()
        self._data = frame.copy()
        snapshot = self.publish_snapshot(views={"raw": frame}, completed_steps=1, total_steps=1)
        if on_update:
            on_update(snapshot)
        return frame

    def _safe_shutdown(self, recorder):
        if self.profile:
            for name, role in (("field_source", self.field_source),
                               ("sample_excitation", self.sample_excitation),
                               ("orientation_controller", self.orientation_controller),
                               ("transport_readout", self.transport_readout)):
                if role is not None:
                    recorder.record_action(name=name + "_shutdown", action_fn=role.safe_shutdown)
        return recorder.build_report()


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
        dmm: Optional[DMM] = None,
        calibrator: Optional[Union[DCCalibrator, Sourcemeter]] = None,
        stepper: Optional[Stepper] = None,
        lockin: Optional[Lockin] = None,
        *,
        field: float = 100.0,
        angle_step: float = 15.0,
        total_angle: float = 360.0,
        start_angle: float = 0.0,
        amplitude: float = 1.0,
        frequency: float = 10.0,
        measure_time: float = 1.0,
        sensitivity: Optional[str] = "50uv/pa",
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
        readout: Optional[Union[Lockin, DMM]] = None,
        current_source: Optional[Union[Sourcemeter, Awg]] = None,
        field_source: Optional[Union[DCCalibrator, Sourcemeter]] = None,
        field_reader: Optional[DMM] = None,
        current: float = 1e-4,
        compliance: float = 2.0,
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

        self.sensitivity = str(sensitivity) if sensitivity is not None else None

        self.settling_time = float(settling_time)
        if not math.isfinite(self.settling_time) or self.settling_time < 0:
            raise ValueError(f"settling_time must be non-negative and finite, got {settling_time!r}")

        if type(record_field_readback) is not bool:
            raise ValueError("record_field_readback must be bool")
        self.record_field_readback = record_field_readback
        if type(raw_window_points) is not int or raw_window_points <= 0:
            raise ValueError("raw_window_points must be a positive integer")
        self.raw_window_points = raw_window_points

        eff_field_source = field_source if field_source is not None else calibrator
        eff_stepper = stepper
        eff_readout = readout if readout is not None else lockin
        if eff_readout is None and current_source is not None and dmm is not None:
            eff_readout = dmm
        eff_field_reader = field_reader if field_reader is not None else (dmm if (dmm is not None and dmm is not eff_readout) else None)

        if profile is None and eff_field_source is not None and eff_stepper is not None and eff_readout is not None:
            from .adapters.amr import AMRSetupProfile

            profile = AMRSetupProfile.from_instruments(
                dmm=dmm,
                calibrator=calibrator,
                arduino=stepper,
                lockin=lockin,
                field_source=eff_field_source,
                readout=eff_readout,
                current_source=current_source,
                field_reader=eff_field_reader,
                current=current,
                compliance=compliance,
                field_calibration=float(voltage_calibration),
                reader_calibration=float(voltage_calibration) if eff_field_reader is not None else None,
                readout_configuration=readout_configuration or "preserve",
                excitation_source="external" if current_source is not None else excitation_source,
                amplitude=self.amplitude,
                frequency=self.frequency,
                sensitivity=self.sensitivity or "50uv/pa",
                settling_time=0.0,
                shutdown_handler=shutdown_handler,
                external_source_owner=external_source_owner,
            )
            dmm = calibrator = stepper = lockin = shutdown_handler = external_source_owner = current_source = readout = field_source = field_reader = None

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
            readout=readout,
            current_source=current_source,
            field_source=field_source,
            field_reader=field_reader,
            current=current,
            compliance=compliance,
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


__all__ = [
    "MagnetoTransport",
    "AMR",
    "convert_steps_to_angle",
    "convert_angle_to_steps",
    "convert_field_to_voltage",
    "convert_voltage_to_field",
]
