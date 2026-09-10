"""
AMR setup-role adapters standardizing field, orientation, and transport electrical readout.

In accordance with Section 9.5 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- FieldSource: Commands electromagnet field through linear, FieldCalibration table, or native modes.
- FieldReader: Reads sensor/gaussmeter with absolute + relative tolerance checks across positive, zero, and negative fields.
- TransportReadout: Standardizes lock-in excitation and X/Y acquisition. Preserves manual front-panel settings by default (readout_configuration='preserve').
- OrientationController: Converts commanded angles to steps, manages direction, and tracks stage orientation.
- AMRSetupProfile: Composite profile binding all four roles into a single coherent interface with attempt-all safing.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import warnings

import numpy as np

from piec.analysis.field_calibration import FieldCalibration
from piec.measurement.magneto_transport import (
    convert_angle_to_steps,
    convert_steps_to_angle,
    convert_field_to_voltage,
    convert_voltage_to_field,
)


class FieldSource:
    """
    AMR setup adapter wrapping the magnetic field source (e.g. DC Calibrator or power supply).

    Supports:
    - Linear factor calibration: voltage = field / calibration (default 10000.0 Oe/V).
    - FieldCalibration table: output_at_field(field).
    - Native field mode: calibration='native' (direct set_field call on instrument).
    """

    def __init__(
        self,
        instrument: Any,
        calibration: Union[float, FieldCalibration, str] = 10000.0,
        field_range: Optional[Tuple[float, float]] = None,
        output_range: Optional[Tuple[float, float]] = None,
        field_unit: str = "Oe",
        output_unit: str = "V",
        name: str = "calibrator",
    ):
        if instrument is None:
            raise ValueError("instrument must not be None")
        self.instrument = instrument
        self.field_unit = str(field_unit)
        self.output_unit = str(output_unit)
        self.name = str(name)

        if isinstance(calibration, (int, float)):
            cal_f = float(calibration)
            if not math.isfinite(cal_f) or cal_f <= 0:
                raise ValueError(f"calibration factor must be a positive finite float, got {calibration!r}")
            self.calibration: Union[float, FieldCalibration, str] = cal_f
            self.mode = "linear"
        elif isinstance(calibration, FieldCalibration):
            self.calibration = calibration
            self.mode = "table"
            self.field_unit = calibration.field_unit
            self.output_unit = calibration.output_unit
        elif isinstance(calibration, str) and calibration.lower() == "native":
            self.calibration = "native"
            self.mode = "native"
        else:
            raise TypeError(
                f"calibration must be a positive float, FieldCalibration instance, or 'native', got {type(calibration).__name__}"
            )

        if field_range is not None:
            if len(field_range) != 2 or field_range[0] > field_range[1]:
                raise ValueError(f"field_range must be (min_field, max_field), got {field_range!r}")
            self.field_range: Optional[Tuple[float, float]] = (float(field_range[0]), float(field_range[1]))
        else:
            self.field_range = None

        if output_range is not None:
            if len(output_range) != 2 or output_range[0] > output_range[1]:
                raise ValueError(f"output_range must be (min_output, max_output), got {output_range!r}")
            self.output_range: Optional[Tuple[float, float]] = (float(output_range[0]), float(output_range[1]))
        else:
            self.output_range = None

        self.commanded_field: Optional[float] = None
        self.current_output: Optional[float] = None

    def compute_output(self, field: float) -> float:
        """Compute the control output for the requested magnetic field."""
        field_f = float(field)
        if not math.isfinite(field_f):
            raise ValueError(f"field must be finite, got {field!r}")

        if self.field_range is not None:
            if field_f < self.field_range[0] or field_f > self.field_range[1]:
                raise ValueError(
                    f"Requested field {field_f} {self.field_unit} is outside field_range {self.field_range}"
                )

        if self.mode == "linear":
            output_val = convert_field_to_voltage(field_f, float(self.calibration))
        elif self.mode == "table":
            assert isinstance(self.calibration, FieldCalibration)
            output_val = float(self.calibration.output_at_field(field_f))
        elif self.mode == "native":
            output_val = field_f
        else:
            raise RuntimeError(f"Unknown FieldSource mode: {self.mode}")

        if self.output_range is not None:
            if output_val < self.output_range[0] or output_val > self.output_range[1]:
                raise ValueError(
                    f"Computed output {output_val} {self.output_unit} is outside output_range {self.output_range}"
                )

        return output_val

    def set_field(self, field: float) -> float:
        """Set the magnetic field on the underlying instrument."""
        output_val = self.compute_output(field)
        if self.mode == "native":
            if hasattr(self.instrument, "set_field"):
                self.instrument.set_field(output_val)
            elif hasattr(self.instrument, "set_output"):
                self.instrument.set_output(output_val)
            else:
                raise AttributeError(f"Instrument {self.instrument!r} has neither set_field nor set_output")
        else:
            if hasattr(self.instrument, "set_output"):
                self.instrument.set_output(output_val)
            elif hasattr(self.instrument, "set_field"):
                self.instrument.set_field(output_val)
            else:
                raise AttributeError(f"Instrument {self.instrument!r} does not have set_output")

        self.commanded_field = float(field)
        self.current_output = output_val
        return self.commanded_field

    def safe_shutdown(self) -> None:
        """
        De-energize the magnetic field source to 0 V/zero output.

        Preserves open connection to the instrument (does NOT close connection).
        Attempts all de-energization steps (voltage zeroing, output disable) and
        raises if any error occurs.
        """
        errors = []
        try:
            if hasattr(self.instrument, "set_output"):
                self.instrument.set_output(0.0)
            elif hasattr(self.instrument, "set_field"):
                self.instrument.set_field(0.0)
        except Exception as exc:
            errors.append(exc)

        output_fn = getattr(self.instrument, "output", None)
        if callable(output_fn):
            try:
                output_fn(on=False)
            except TypeError:
                try:
                    output_fn(False)
                except Exception as exc:
                    errors.append(exc)
            except Exception as exc:
                errors.append(exc)

        self.commanded_field = 0.0
        self.current_output = 0.0

        if errors:
            raise RuntimeError(f"FieldSource safe_shutdown encountered errors: {errors}")

    def de_energize(self) -> None:
        """Alias for safe_shutdown."""
        self.safe_shutdown()


class FieldReader:
    """
    AMR setup adapter for reading the actual magnetic field via sensor or gaussmeter.

    Supports:
    - Linear factor calibration: field = voltage * calibration (default 10000.0 Oe/V).
    - FieldCalibration table: field = calibration.field_at_output(voltage).
    - Native field mode: calibration='native' (reads get_field directly).
    """

    def __init__(
        self,
        instrument: Any,
        calibration: Union[float, FieldCalibration, str] = 10000.0,
        field_unit: str = "Oe",
        sensor_unit: str = "V",
        absolute_tolerance: float = 1.0,
        relative_tolerance: float = 0.1,
        mismatch_policy: str = "warn",
        name: str = "dmm",
    ):
        if instrument is None:
            raise ValueError("instrument must not be None")
        self.instrument = instrument
        self.field_unit = str(field_unit)
        self.sensor_unit = str(sensor_unit)
        self.name = str(name)

        if isinstance(calibration, (int, float)):
            cal_f = float(calibration)
            if not math.isfinite(cal_f) or cal_f <= 0:
                raise ValueError(f"calibration factor must be a positive finite float, got {calibration!r}")
            self.calibration: Union[float, FieldCalibration, str] = cal_f
            self.mode = "linear"
        elif isinstance(calibration, FieldCalibration):
            self.calibration = calibration
            self.mode = "table"
            self.field_unit = calibration.field_unit
            self.sensor_unit = calibration.output_unit
        elif isinstance(calibration, str) and calibration.lower() == "native":
            self.calibration = "native"
            self.mode = "native"
        else:
            raise TypeError(
                f"calibration must be a positive float, FieldCalibration instance, or 'native', got {type(calibration).__name__}"
            )

        if absolute_tolerance < 0:
            raise ValueError(f"absolute_tolerance must be non-negative, got {absolute_tolerance!r}")
        if relative_tolerance < 0:
            raise ValueError(f"relative_tolerance must be non-negative, got {relative_tolerance!r}")
        self.absolute_tolerance = float(absolute_tolerance)
        self.relative_tolerance = float(relative_tolerance)

        policy = str(mismatch_policy).lower()
        if policy not in ("warn", "raise"):
            raise ValueError(f"mismatch_policy must be 'warn' or 'raise', got {mismatch_policy!r}")
        self.mismatch_policy = policy

        self.last_measured_field: Optional[float] = None
        self.last_read_time: Optional[float] = None

    def read_field(self) -> Tuple[float, float]:
        """
        Read measured field from the sensor instrument.

        Returns:
            Tuple[float, float]: (measured_field, timestamp)
        """
        if self.mode == "native":
            if hasattr(self.instrument, "get_field"):
                raw = self.instrument.get_field()
            elif hasattr(self.instrument, "get_voltage"):
                raw = self.instrument.get_voltage()
            else:
                raise AttributeError(f"Instrument {self.instrument!r} has neither get_field nor get_voltage")
            field_val = float(raw)
        else:
            if hasattr(self.instrument, "get_voltage"):
                v_raw = self.instrument.get_voltage()
            elif hasattr(self.instrument, "get_field"):
                v_raw = self.instrument.get_field()
            else:
                raise AttributeError(f"Instrument {self.instrument!r} does not have get_voltage")

            v = float(v_raw)
            if not math.isfinite(v):
                raise ValueError(f"Sensor voltage is non-finite: {v!r}")

            if self.mode == "linear":
                field_val = convert_voltage_to_field(v, float(self.calibration))
            elif self.mode == "table":
                assert isinstance(self.calibration, FieldCalibration)
                field_val = float(self.calibration.field_at_output(v))
            else:
                raise RuntimeError(f"Unknown FieldReader mode: {self.mode}")

        if not math.isfinite(field_val):
            raise ValueError(f"Measured field is non-finite: {field_val!r}")

        read_time = time.time()
        self.last_measured_field = field_val
        self.last_read_time = read_time
        return field_val, read_time

    def verify_field(self, target_field: float, actual_field: Optional[float] = None) -> bool:
        """
        Verify that measured field is within tolerance of target field.

        Valid across positive, zero, and negative fields:
            abs(actual - target) <= absolute_tolerance + relative_tolerance * abs(target)
        """
        if actual_field is None:
            actual_field, _ = self.read_field()

        target_f = float(target_field)
        actual_f = float(actual_field)
        if not math.isfinite(target_f) or not math.isfinite(actual_f):
            raise ValueError(f"target_field and actual_field must be finite: target={target_field!r}, actual={actual_field!r}")

        tol = self.absolute_tolerance + self.relative_tolerance * abs(target_f)
        diff = abs(actual_f - target_f)

        if diff > tol:
            msg = (
                f"Field mismatch: target {target_f} {self.field_unit}, "
                f"measured {actual_f} {self.field_unit} (difference {diff:.3f} exceeds tolerance {tol:.3f})"
            )
            if self.mismatch_policy == "raise":
                raise RuntimeError(msg)
            else:
                warnings.warn(msg, UserWarning, stacklevel=2)
                return False
        return True


class TransportReadout:
    """
    AMR setup adapter for transport electrical readout (e.g. Lock-in amplifier).

    In accordance with Section 9.5 of MEASUREMENT_STANDARDIZATION_PLAN.md:
    - readout_configuration='preserve' (default): strictly NO initialize(), reset(),
      clear(), autorange, or parameter writes sent to the lock-in. Preserves manual
      front-panel settings chosen by the lab operator!
    - readout_configuration='configure': sends validated parameter writes to lockin.
    - signal_mode='lockin_xy': reads in-phase X and quadrature Y in Volts.
    """

    def __init__(
        self,
        instrument: Any,
        readout_configuration: str = "preserve",
        signal_mode: str = "lockin_xy",
        excitation_source: str = "internal",
        amplitude: float = 1.0,
        frequency: float = 10.0,
        sensitivity: str = "50uv/pa",
        input_configuration: str = "a-b",
        measure_time: float = 1.0,
        sample_interval: float = 0.1,
        name: str = "lockin",
    ):
        if instrument is None:
            raise ValueError("instrument must not be None")
        self.instrument = instrument

        cfg = str(readout_configuration).lower()
        if cfg not in ("preserve", "configure"):
            raise ValueError(f"readout_configuration must be 'preserve' or 'configure', got {readout_configuration!r}")
        self.readout_configuration = cfg

        sig = str(signal_mode).lower()
        if sig != "lockin_xy":
            raise ValueError(f"Unsupported signal_mode {signal_mode!r}; currently only 'lockin_xy' is supported")
        self.signal_mode = sig

        exc = str(excitation_source).lower()
        if exc not in ("internal", "external"):
            raise ValueError(f"excitation_source must be 'internal' or 'external', got {excitation_source!r}")
        self.excitation_source = exc

        self.amplitude = float(amplitude)
        self.frequency = float(frequency)
        self.sensitivity = str(sensitivity)
        self.input_configuration = str(input_configuration)
        self.measure_time = float(measure_time)
        self.sample_interval = float(sample_interval)
        self.name = str(name)

    def configure(self) -> None:
        """
        Configure the lockin amplifier according to readout_configuration policy.

        When 'preserve': NO commands are sent! Manual operator front panel settings are kept.
        When 'configure': Writes validated settings.
        """
        if self.readout_configuration == "preserve":
            # Confirmed lab workflow: NEVER overwrite manual settings!
            return

        # Automated configuration mode:
        if self.excitation_source == "internal":
            init_fn = getattr(self.instrument, "initialize", None)
            if callable(init_fn):
                init_fn()
            cfg_ref = getattr(self.instrument, "configure_reference", None)
            if callable(cfg_ref):
                cfg_ref(voltage=self.amplitude, frequency=self.frequency)

        cfg_inp = getattr(self.instrument, "configure_input", None)
        if callable(cfg_inp):
            cfg_inp(input_configuration=self.input_configuration)

        cfg_gain = getattr(self.instrument, "configure_gain_filters", None)
        if callable(cfg_gain):
            cfg_gain(sensitivity=self.sensitivity)

    def read_signals(self) -> Dict[str, float]:
        """
        Read a single (X, Y) acquisition from the lock-in amplifier.

        Returns:
            Dict[str, float]: {'x': float, 'y': float} in Volts.
        """
        if hasattr(self.instrument, "get_X_Y"):
            res = self.instrument.get_X_Y()
        elif hasattr(self.instrument, "get_xy"):
            res = self.instrument.get_xy()
        elif hasattr(self.instrument, "get_data"):
            res = self.instrument.get_data()
        else:
            raise AttributeError(f"Instrument {self.instrument!r} does not have get_X_Y method")

        if isinstance(res, (tuple, list)) and len(res) >= 2:
            x, y = res[0], res[1]
        elif isinstance(res, dict) and "x" in res and "y" in res:
            x, y = res["x"], res["y"]
        else:
            raise TypeError(f"Unexpected return format from lockin: {type(res).__name__}")

        x_f = float(x)
        y_f = float(y)
        if not math.isfinite(x_f) or not math.isfinite(y_f):
            raise ValueError(f"Lock-in signals contain non-finite values: X={x!r}, Y={y!r}")

        return {"x": x_f, "y": y_f}

    def average_signals(
        self,
        measure_time: Optional[float] = None,
        sample_interval: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Acquire and average signals over the specified measure_time.
        """
        duration = self.measure_time if measure_time is None else float(measure_time)
        dt = self.sample_interval if sample_interval is None else float(sample_interval)

        if duration <= 0 or dt <= 0:
            return self.read_signals()

        x_list = []
        y_list = []
        start_time = time.monotonic()
        while True:
            sig = self.read_signals()
            x_list.append(sig["x"])
            y_list.append(sig["y"])
            elapsed = time.monotonic() - start_time
            if elapsed >= duration - 1e-9:
                break
            time.sleep(min(dt, max(0.0, duration - elapsed)))

        return {"x": float(np.mean(x_list)), "y": float(np.mean(y_list))}

    def safe_shutdown(self) -> None:
        """
        Safing for electrical readout.

        When configured automatically with internal excitation, sets oscillator amplitude to 0.
        When preserving manual configuration, leaves excitation alone.
        Preserves connection open (does NOT close connection).
        """
        if self.readout_configuration == "configure" and self.excitation_source == "internal":
            cfg_ref = getattr(self.instrument, "configure_reference", None)
            if callable(cfg_ref):
                try:
                    cfg_ref(voltage=0.0)
                except Exception:
                    pass


class OrientationController:
    """
    AMR setup adapter for rotating the sample stage (e.g. Stepper motor / Arduino).

    Tracks commanded angle, converts delta angles to steps with residual-step awareness,
    and observes settling time.
    """

    def __init__(
        self,
        instrument: Any,
        steps_per_revolution: int = 200,
        angle_limits: Optional[Tuple[float, float]] = None,
        settling_time: float = 0.0,
        cw_direction: int = 1,
        ccw_direction: int = 0,
        name: str = "stepper",
    ):
        if instrument is None:
            raise ValueError("instrument must not be None")
        self.instrument = instrument

        if not isinstance(steps_per_revolution, (int, np.integer)) or steps_per_revolution <= 0:
            raise ValueError(f"steps_per_revolution must be a positive integer, got {steps_per_revolution!r}")
        self.steps_per_revolution = int(steps_per_revolution)

        if angle_limits is not None:
            if len(angle_limits) != 2 or angle_limits[0] > angle_limits[1]:
                raise ValueError(f"angle_limits must be (min_angle, max_angle), got {angle_limits!r}")
            self.angle_limits: Optional[Tuple[float, float]] = (float(angle_limits[0]), float(angle_limits[1]))
        else:
            self.angle_limits = None

        self.settling_time = max(0.0, float(settling_time))
        self.cw_direction = int(cw_direction)
        self.ccw_direction = int(ccw_direction)
        self.name = str(name)

        self.current_angle: float = 0.0
        self.total_steps_moved: int = 0

    def move_to_angle(self, target_angle: float) -> float:
        """
        Move stepper motor to target angle in degrees.

        Returns:
            float: Updated actual commanded angle.
        """
        target_f = float(target_angle)
        if not math.isfinite(target_f):
            raise ValueError(f"target_angle must be finite, got {target_angle!r}")

        if self.angle_limits is not None:
            if target_f < self.angle_limits[0] or target_f > self.angle_limits[1]:
                raise ValueError(
                    f"target_angle {target_f} is outside angle_limits {self.angle_limits}"
                )

        delta_angle = target_f - self.current_angle
        # Compute steps needed
        steps = convert_angle_to_steps(delta_angle, self.steps_per_revolution)
        if steps != 0:
            direction = self.cw_direction if steps > 0 else self.ccw_direction
            num_steps = abs(steps)
            if hasattr(self.instrument, "step"):
                self.instrument.step(num_steps, direction)
            else:
                raise AttributeError(f"Instrument {self.instrument!r} does not have step method")

            actual_delta = convert_steps_to_angle(steps, self.steps_per_revolution)
            self.current_angle += actual_delta
            self.total_steps_moved += steps

        if self.settling_time > 0:
            time.sleep(self.settling_time)

        return self.current_angle

    def step_relative(self, delta_angle: float) -> float:
        """Move stepper motor by a relative angle delta."""
        return self.move_to_angle(self.current_angle + delta_angle)

    def set_zero(self, angle: float = 0.0) -> None:
        """Reset internal angle tracking to zero or declared value."""
        self.current_angle = float(angle)
        set_zero_fn = getattr(self.instrument, "set_zero", None)
        if callable(set_zero_fn):
            set_zero_fn()

    def safe_shutdown(self) -> None:
        """Halt motion if supported. Preserves connection open."""
        halt_fn = getattr(self.instrument, "halt", None) or getattr(self.instrument, "stop", None)
        if callable(halt_fn):
            try:
                halt_fn()
            except Exception:
                pass


class AMRSetupProfile:
    """
    Composite setup profile coordinating the four AMR setup roles.

    Bindings:
    - field_source: FieldSource
    - field_reader: Optional[FieldReader]
    - transport_readout: TransportReadout
    - orientation_controller: OrientationController
    """

    def __init__(
        self,
        field_source: FieldSource,
        field_reader: Optional[FieldReader],
        transport_readout: TransportReadout,
        orientation_controller: OrientationController,
        name: str = "amr_profile",
    ):
        if not isinstance(field_source, FieldSource):
            raise TypeError(f"field_source must be a FieldSource, got {type(field_source).__name__}")
        if field_reader is not None and not isinstance(field_reader, FieldReader):
            raise TypeError(f"field_reader must be FieldReader or None, got {type(field_reader).__name__}")
        if not isinstance(transport_readout, TransportReadout):
            raise TypeError(f"transport_readout must be a TransportReadout, got {type(transport_readout).__name__}")
        if not isinstance(orientation_controller, OrientationController):
            raise TypeError(f"orientation_controller must be an OrientationController, got {type(orientation_controller).__name__}")

        self.field_source = field_source
        self.field_reader = field_reader
        self.transport_readout = transport_readout
        self.orientation_controller = orientation_controller
        self.name = str(name)

    @classmethod
    def from_instruments(
        cls,
        dmm: Any = None,
        calibrator: Any = None,
        arduino: Any = None,
        lockin: Any = None,
        *,
        field_calibration: Union[float, FieldCalibration, str] = 10000.0,
        reader_calibration: Union[float, FieldCalibration, str, None] = 10000.0,
        steps_per_revolution: int = 200,
        readout_configuration: str = "preserve",
        excitation_source: str = "internal",
        amplitude: float = 1.0,
        frequency: float = 10.0,
        sensitivity: str = "50uv/pa",
        input_configuration: str = "a-b",
        settling_time: float = 0.0,
        absolute_tolerance: float = 1.0,
        relative_tolerance: float = 0.1,
        mismatch_policy: str = "warn",
        field_range: Optional[Tuple[float, float]] = None,
        output_range: Optional[Tuple[float, float]] = None,
        angle_limits: Optional[Tuple[float, float]] = None,
        name: str = "working_lab_amr",
    ) -> AMRSetupProfile:
        """
        Build an AMRSetupProfile from the four standard lab instruments.
        """
        if calibrator is None:
            raise ValueError("calibrator must not be None for AMRSetupProfile")
        if arduino is None:
            raise ValueError("arduino/stepper must not be None for AMRSetupProfile")
        if lockin is None:
            raise ValueError("lockin must not be None for AMRSetupProfile")

        source = FieldSource(
            instrument=calibrator,
            calibration=field_calibration,
            field_range=field_range,
            output_range=output_range,
            name="calibrator",
        )

        reader = None
        if dmm is not None and reader_calibration is not None:
            reader = FieldReader(
                instrument=dmm,
                calibration=reader_calibration,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                mismatch_policy=mismatch_policy,
                name="dmm",
            )

        readout = TransportReadout(
            instrument=lockin,
            readout_configuration=readout_configuration,
            excitation_source=excitation_source,
            amplitude=amplitude,
            frequency=frequency,
            sensitivity=sensitivity,
            input_configuration=input_configuration,
            name="lockin",
        )

        orientation = OrientationController(
            instrument=arduino,
            steps_per_revolution=steps_per_revolution,
            angle_limits=angle_limits,
            settling_time=settling_time,
            name="stepper",
        )

        return cls(
            field_source=source,
            field_reader=reader,
            transport_readout=readout,
            orientation_controller=orientation,
            name=name,
        )

    def unique_instruments(self) -> List[Any]:
        """Return list of distinct instrument objects used in this profile."""
        insts = [
            self.field_source.instrument,
            self.transport_readout.instrument,
            self.orientation_controller.instrument,
        ]
        if self.field_reader is not None:
            insts.append(self.field_reader.instrument)

        unique = []
        for inst in insts:
            if inst is not None and not any(inst is existing for existing in unique):
                unique.append(inst)
        return unique

    def safe_shutdown(self) -> Dict[str, Any]:
        """
        Attempt-all safing across all unique roles and instruments.

        Does NOT close connections.
        """
        results = {}
        for role_name, role_obj in (
            ("field_source", self.field_source),
            ("transport_readout", self.transport_readout),
            ("orientation_controller", self.orientation_controller),
        ):
            try:
                role_obj.safe_shutdown()
                results[role_name] = "safe"
            except Exception as exc:
                results[role_name] = f"error: {exc}"

        return results
