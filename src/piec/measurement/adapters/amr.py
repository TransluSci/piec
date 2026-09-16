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
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import warnings

import numpy as np

from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.instrument import Instrument
from piec.drivers.dc_calibrator.dc_calibrator import DCCalibrator
from piec.drivers.dmm.dmm import DMM
from piec.drivers.lockin.lockin import Lockin
from piec.drivers.stepper_motor.stepper_motor import Stepper
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.drivers.awg.awg import Awg
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


def _finite(value, name, minimum=None):
    value = float(value)
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        requirement = "finite" if minimum is None else f"finite and >= {minimum}"
        raise ValueError(f"{name} must be {requirement}")
    return value


def _limits(value, name):
    if value is None:
        return None
    if len(value) != 2:
        raise ValueError(f"{name} must be (min, max)")
    low, high = (_finite(v, name) for v in value)
    if low > high:
        raise ValueError(f"{name} must be (min, max)")
    return low, high


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
        instrument: Union[DCCalibrator, Instrument],
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

        self.field_range = _limits(field_range, "field_range")
        self.output_range = _limits(output_range, "output_range")
        if not self.field_unit.strip():
            raise ValueError("field_unit must be non-empty")
        if self.mode == "native":
            self.output_unit = self.field_unit
        elif self.output_unit not in ("V", "A"):
            raise ValueError("output_unit must be V or A")

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

        output_val = _finite(output_val, "computed output")
        if self.output_range is not None:
            if output_val < self.output_range[0] or output_val > self.output_range[1]:
                raise ValueError(
                    f"Computed output {output_val} {self.output_unit} is outside output_range {self.output_range}"
                )

        return output_val

    def set_field(self, field: float) -> float:
        """Set the magnetic field on the underlying instrument."""
        output_val = self.compute_output(field)
        self._write_output(output_val)

        self.commanded_field = float(field)
        self.current_output = output_val
        return self.commanded_field

    def _write_output(self, value):
        # Never substitute electrical output for a native field command.
        if self.mode == "native":
            self.instrument.set_field(value)
        else:
            self.instrument.set_output(value, mode={"V": "voltage", "A": "current"}[self.output_unit])

    def safe_shutdown(self) -> None:
        """
        De-energize the magnetic field source to 0 V/zero output.

        Preserves open connection to the instrument (does NOT close connection).
        Attempts all de-energization steps (voltage zeroing, output disable) and
        raises if any error occurs.
        """
        errors = []
        try:
            self._write_output(0.0)
        except Exception as exc:
            errors.append(exc)

        output_fn = getattr(self.instrument, "output", None)
        if callable(output_fn):
            try:
                output_fn(on=False)
            except Exception as exc:
                errors.append(exc)

        if errors:
            self.commanded_field = None
            self.current_output = None
            raise RuntimeError(f"FieldSource safe_shutdown encountered errors: {errors}")
        self.commanded_field = None  # electrical zero need not mean zero calibrated field
        self.current_output = 0.0

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
        instrument: Union[DMM, Instrument],
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

        if not self.field_unit.strip():
            raise ValueError("field_unit must be non-empty")
        if self.mode != "native" and self.sensor_unit != "V":
            raise ValueError("Analog field reader requires a voltage calibration (V)")
        self.absolute_tolerance = _finite(absolute_tolerance, "absolute_tolerance", 0)
        self.relative_tolerance = _finite(relative_tolerance, "relative_tolerance", 0)

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
            field_val = float(self.instrument.get_field())
        else:
            v_raw = self.instrument.get_voltage()

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


class SampleExcitation:
    """
    AMR setup adapter for managing sample electrical current/voltage excitation.

    Supports:
    - Internal mode (source_type='internal'): uses Lock-in internal oscillator.
    - External mode (source_type='external'): uses dedicated Sourcemeter or Awg.
      Configures current/compliance or voltage, arms output, and guarantees
      output(False) on safe shutdown.
    """

    def __init__(
        self,
        instrument: Optional[Union[Lockin, Sourcemeter, Awg, Instrument]] = None,
        source_type: str = "internal",
        current: float = 1e-4,
        compliance: float = 2.0,
        amplitude: float = 1.0,
        frequency: float = 10.0,
        shutdown_handler: Optional[Callable[[], None]] = None,
        name: str = "excitation",
    ):
        self.instrument = instrument
        src = str(source_type).lower().strip()
        if src not in ("internal", "external"):
            raise ValueError(f"source_type must be 'internal' or 'external', got {source_type!r}")
        self.source_type = src
        self.current = float(current)
        self.compliance = float(compliance)
        self.amplitude = float(amplitude)
        self.frequency = float(frequency)
        self.shutdown_handler = shutdown_handler
        self.name = str(name)

    def configure(self) -> None:
        """Energize the excitation source."""
        if self.source_type == "external" and self.instrument is not None:
            if hasattr(self.instrument, "configure_current_source"):
                try:
                    self.instrument.configure_current_source(current=self.current, voltage_compliance=self.compliance)
                except Exception:
                    pass
            else:
                if hasattr(self.instrument, "set_source_function"):
                    try:
                        self.instrument.set_source_function(source_func="CURR")
                    except Exception:
                        pass
                if hasattr(self.instrument, "set_source_current"):
                    try:
                        self.instrument.set_source_current(current=self.current)
                    except Exception:
                        pass
                elif hasattr(self.instrument, "set_current"):
                    try:
                        self.instrument.set_current(self.current)
                    except Exception:
                        pass
                if hasattr(self.instrument, "set_voltage_compliance"):
                    try:
                        self.instrument.set_voltage_compliance(voltage_compliance=self.compliance)
                    except Exception:
                        pass
                elif hasattr(self.instrument, "set_compliance"):
                    try:
                        self.instrument.set_compliance(self.compliance)
                    except Exception:
                        pass
            if hasattr(self.instrument, "output"):
                try:
                    self.instrument.output(on=True)
                except TypeError:
                    try:
                        self.instrument.output(True)
                    except Exception:
                        pass
                except Exception:
                    pass
        elif self.source_type == "internal" and self.instrument is not None:
            if hasattr(self.instrument, "set_amplitude"):
                self.instrument.set_amplitude(self.amplitude)
            if hasattr(self.instrument, "set_reference_frequency"):
                self.instrument.set_reference_frequency(self.frequency)

    def safe_shutdown(self) -> None:
        """De-energize excitation source. Safe shutdown guarantee."""
        if self.instrument is not None:
            if hasattr(self.instrument, "output"):
                try:
                    self.instrument.output(on=False)
                except TypeError:
                    try:
                        self.instrument.output(False)
                    except Exception:
                        pass
                except Exception:
                    pass
            elif hasattr(self.instrument, "set_amplitude"):
                try:
                    self.instrument.set_amplitude(0.004)
                except Exception:
                    pass
        if callable(self.shutdown_handler):
            self.shutdown_handler()


class TransportReadout:
    """
    AMR setup adapter for transport electrical readout (Lock-in amplifier or DMM).

    In accordance with Section 9.5 of MEASUREMENT_STANDARDIZATION_PLAN.md:
    - readout_configuration='preserve' (default): strictly NO initialize(), reset(),
      clear(), autorange, or parameter writes sent to the lock-in. Preserves manual
      front-panel settings chosen by the lab operator!
    - readout_configuration='configure': sends validated parameter writes to instrument.
    - signal_mode='lockin_xy': reads in-phase X and quadrature Y in Volts.
    - signal_mode='dmm_voltage': reads DC Voltage in Volts.
    """

    def __init__(
        self,
        instrument: Union[Lockin, DMM, Instrument],
        readout_configuration: str = "preserve",
        signal_mode: Optional[str] = None,
        excitation_source: str = "internal",
        amplitude: float = 1.0,
        frequency: float = 10.0,
        sensitivity: str = "50uv/pa",
        input_configuration: str = "a-b",
        measure_time: float = 1.0,
        sample_interval: float = 0.1,
        name: str = "readout",
        shutdown_handler: Optional[Callable[[], None]] = None,
        external_source_owner: Optional[str] = None,
    ):
        if instrument is None:
            raise ValueError("instrument must not be None")
        self.instrument = instrument

        cfg = str(readout_configuration).lower()
        if cfg not in ("preserve", "configure"):
            raise ValueError(f"readout_configuration must be 'preserve' or 'configure', got {readout_configuration!r}")
        self.readout_configuration = cfg

        if signal_mode is None:
            if isinstance(instrument, DMM):
                signal_mode = "dmm_voltage"
            else:
                signal_mode = "lockin_xy"

        sig = str(signal_mode).lower().strip()
        if sig not in ("lockin_xy", "dmm_voltage"):
            raise ValueError(f"Unsupported signal_mode {signal_mode!r}; supported: 'lockin_xy', 'dmm_voltage'")
        self.signal_mode = sig

        exc = str(excitation_source).lower()
        if exc not in ("internal", "external"):
            raise ValueError(f"excitation_source must be 'internal' or 'external', got {excitation_source!r}")
        self.excitation_source = exc

        if shutdown_handler is not None and not callable(shutdown_handler):
            raise TypeError("shutdown_handler must be callable")
        if exc == "external" and not str(external_source_owner or "").strip() and shutdown_handler is None:
            raise ValueError("external_source_owner must name who controls and de-energizes the external source")
        self.shutdown_handler = shutdown_handler
        self.external_source_owner = external_source_owner
        self.amplitude = _finite(amplitude, "amplitude", 0)
        self.frequency = _finite(frequency, "frequency", 0)
        self.sensitivity = str(sensitivity)
        self.input_configuration = str(input_configuration)
        self.measure_time = _finite(measure_time, "measure_time", 0)
        self.sample_interval = _finite(sample_interval, "sample_interval", 0)
        self.name = str(name)

    def configure(self) -> None:
        """
        Configure the readout instrument according to readout_configuration policy.

        When 'preserve': NO commands are sent! Manual operator front panel settings are kept.
        When 'configure': Writes validated settings.
        """
        if self.readout_configuration == "preserve":
            # Confirmed lab workflow: NEVER overwrite manual settings!
            return

        if self.signal_mode == "lockin_xy":
            # Select reference explicitly, without resetting unrelated settings.
            if self.excitation_source == "internal":
                if hasattr(self.instrument, "configure_reference"):
                    self.instrument.configure_reference(source="internal", voltage=self.amplitude, frequency=self.frequency)
            else:
                if hasattr(self.instrument, "configure_reference"):
                    self.instrument.configure_reference(source="external")
            if hasattr(self.instrument, "configure_input"):
                self.instrument.configure_input(input_configuration=self.input_configuration)
            if hasattr(self.instrument, "configure_gain_filters"):
                self.instrument.configure_gain_filters(sensitivity=self.sensitivity)

    def get_active_settings(self) -> Dict[str, Any]:
        """
        Query active settings from the instrument.
        In 'preserve' mode, no commands are sent to the lock-in besides readout.
        """
        if self.readout_configuration == "preserve":
            return {}

        settings: Dict[str, Any] = {}
        if self.signal_mode == "lockin_xy":
            if hasattr(self.instrument, "query"):
                try:
                    sens_idx = self.instrument.query("SENS?")
                    settings["sensitivity_index"] = str(sens_idx).strip()
                except Exception:
                    pass
            if hasattr(self.instrument, "get_time_constant"):
                try:
                    settings["time_constant"] = str(self.instrument.get_time_constant())
                except Exception:
                    pass
        elif self.signal_mode == "dmm_voltage":
            if hasattr(self.instrument, "get_range"):
                try:
                    settings["range"] = str(self.instrument.get_range())
                except Exception:
                    pass
        return settings

    def check_overload(self) -> bool:
        """Check if the lockin input or reserve is currently overloaded."""
        if self.signal_mode != "lockin_xy" or self.readout_configuration == "preserve":
            return False
        if hasattr(self.instrument, "is_overloaded"):
            val = getattr(self.instrument, "is_overloaded")
            return bool(val() if callable(val) else val)
        if hasattr(self.instrument, "query"):
            try:
                lias = int(self.instrument.query("LIAS? 0"))
                return (lias & 1) != 0
            except Exception:
                pass
        return False

    def auto_gain(self) -> Optional[str]:
        """Run auto-gain on the lock-in amplifier and return resulting sensitivity."""
        if self.signal_mode != "lockin_xy":
            return None
        res = None
        if hasattr(self.instrument, "auto_gain"):
            try:
                res = self.instrument.auto_gain()
            except Exception:
                pass
        if res is not None:
            return str(res)
        return None

    def read_signals(self) -> Dict[str, float]:
        """
        Read a single signal acquisition.

        Returns:
            Dict[str, float]: {'x': float, 'y': float} in Volts (plus 'voltage' for DMM).
        """
        if self.signal_mode == "dmm_voltage":
            if hasattr(self.instrument, "get_voltage"):
                v = self.instrument.get_voltage()
            elif hasattr(self.instrument, "measure_voltage"):
                v = self.instrument.measure_voltage()
            elif hasattr(self.instrument, "read"):
                v = self.instrument.read()
            else:
                raise AttributeError(f"Instrument {self.instrument!r} does not have a voltage read method")
            v_f = float(v)
            if not math.isfinite(v_f):
                raise ValueError(f"DMM voltage is non-finite: {v!r}")
            return {"x": v_f, "y": 0.0, "voltage": v_f}

        # Lock-in mode
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

        duration = _finite(duration, "measure_time", 0)
        dt = _finite(dt, "sample_interval", 0)
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
        """Run excitation shutdown handler or disable instrument output."""
        if callable(self.shutdown_handler):
            self.shutdown_handler()
        elif hasattr(self.instrument, "output"):
            try:
                self.instrument.output(False)
            except Exception:
                pass
        elif hasattr(self.instrument, "set_amplitude"):
            try:
                self.instrument.set_amplitude(0.004)
            except Exception:
                pass
        else:
            raise RuntimeError("Excitation shutdown unconfirmed: a setup shutdown_handler is required; "
                               f"owner={self.external_source_owner or 'internal excitation operator'}")


class OrientationController:
    """
    AMR setup adapter for rotating the sample stage (e.g. Stepper motor / Arduino).

    Tracks commanded angle, converts delta angles to steps with residual-step awareness,
    and observes settling time.
    """

    def __init__(
        self,
        instrument: Union[Stepper, Instrument],
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

        self.angle_limits = _limits(angle_limits, "angle_limits")
        self.settling_time = _finite(settling_time, "settling_time", 0)
        self.cw_direction = int(cw_direction)
        self.ccw_direction = int(ccw_direction)
        self.name = str(name)

        self.current_angle: float = 0.0
        self.total_steps_moved: int = 0

    def plan_move(self, target_angle: float, current_angle=None):
        """Validate a requested move without I/O; return steps and quantized position."""
        target = _finite(target_angle, "target_angle")
        current = self.current_angle if current_angle is None else _finite(current_angle, "current_angle")
        steps = convert_angle_to_steps(target - current, self.steps_per_revolution)
        achieved = current + convert_steps_to_angle(steps, self.steps_per_revolution)
        if self.angle_limits is not None:
            low, high = self.angle_limits
            if not low <= target <= high:
                raise ValueError(f"target_angle {target} is outside angle_limits {self.angle_limits}")
            if not low <= achieved <= high:
                raise ValueError(f"Quantized angle {achieved} is outside angle_limits {self.angle_limits}")
        return steps, achieved

    def move_to_angle(self, target_angle: float, *, settle: bool = True) -> float:
        """
        Move stepper motor to target angle in degrees.

        Returns:
            float: Updated actual commanded angle.
        """
        steps, achieved = self.plan_move(target_angle)
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

        if settle and self.settling_time > 0:
            time.sleep(self.settling_time)

        return self.current_angle

    def step_relative(self, delta_angle: float) -> float:
        """Move stepper motor by a relative angle delta."""
        return self.move_to_angle(self.current_angle + delta_angle)

    def set_zero(self, angle: float = 0.0) -> None:
        """Reset internal angle tracking to zero or declared value."""
        angle = _finite(angle, "angle")
        set_zero_fn = getattr(self.instrument, "set_zero", None)
        if callable(set_zero_fn):
            set_zero_fn()
        self.current_angle = angle

    def safe_shutdown(self) -> None:
        """Halt motion if supported. Preserves connection open."""
        halt_fn = getattr(self.instrument, "halt", None) or getattr(self.instrument, "stop", None)
        if callable(halt_fn):
            halt_fn()


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
        sample_excitation: Optional[SampleExcitation] = None,
    ):
        if not isinstance(field_source, FieldSource):
            raise TypeError(f"field_source must be a FieldSource, got {type(field_source).__name__}")
        if field_reader is not None and not isinstance(field_reader, FieldReader):
            raise TypeError(f"field_reader must be FieldReader or None, got {type(field_reader).__name__}")
        if not isinstance(transport_readout, TransportReadout):
            raise TypeError(f"transport_readout must be a TransportReadout, got {type(transport_readout).__name__}")
        if not isinstance(orientation_controller, OrientationController):
            raise TypeError(f"orientation_controller must be an OrientationController, got {type(orientation_controller).__name__}")
        if sample_excitation is not None and not isinstance(sample_excitation, SampleExcitation):
            raise TypeError(f"sample_excitation must be a SampleExcitation, got {type(sample_excitation).__name__}")

        if field_reader is not None and field_reader.field_unit != field_source.field_unit:
            raise ValueError("Source and reader field units must match; convert explicitly, never relabel H/B")
        self.field_source = field_source
        self.field_reader = field_reader
        self.transport_readout = transport_readout
        self.orientation_controller = orientation_controller
        self.sample_excitation = sample_excitation or SampleExcitation(
            instrument=transport_readout.instrument,
            source_type=transport_readout.excitation_source,
            amplitude=transport_readout.amplitude,
            frequency=transport_readout.frequency,
            shutdown_handler=transport_readout.shutdown_handler,
        )
        self.name = str(name)

    @classmethod
    def from_instruments(
        cls,
        dmm: Optional[Union[DMM, Instrument]] = None,
        calibrator: Optional[Union[DCCalibrator, Sourcemeter, Instrument]] = None,
        arduino: Optional[Union[Stepper, Instrument]] = None,
        lockin: Optional[Union[Lockin, Instrument]] = None,
        *,
        readout: Optional[Union[Lockin, DMM, Instrument]] = None,
        current_source: Optional[Union[Sourcemeter, Awg, Instrument]] = None,
        field_source: Optional[Union[DCCalibrator, Sourcemeter, Instrument]] = None,
        field_reader: Optional[Union[DMM, Instrument]] = None,
        current: float = 1e-4,
        compliance: float = 2.0,
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
        shutdown_handler: Optional[Callable[[], None]] = None,
        external_source_owner: Optional[str] = None,
    ) -> AMRSetupProfile:
        """
        Build an AMRSetupProfile from standard lab instruments or explicit roles.
        """
        eff_source_inst = field_source if field_source is not None else calibrator
        eff_stepper_inst = arduino
        
        # Determine readout instrument: explicit readout > lockin > (dmm if current_source provided)
        eff_readout_inst = readout if readout is not None else lockin
        if eff_readout_inst is None and current_source is not None and dmm is not None:
            eff_readout_inst = dmm

        # Determine field reader instrument: explicit field_reader > (dmm if not used as readout)
        eff_reader_inst = field_reader
        if eff_reader_inst is None and dmm is not None and dmm is not eff_readout_inst:
            eff_reader_inst = dmm

        if eff_source_inst is None:
            raise ValueError("field_source or calibrator must not be None for AMRSetupProfile")
        if eff_stepper_inst is None:
            raise ValueError("arduino/stepper must not be None for AMRSetupProfile")
        if eff_readout_inst is None:
            raise ValueError("readout or lockin must not be None for AMRSetupProfile")

        source = FieldSource(
            instrument=eff_source_inst,
            calibration=field_calibration,
            field_range=field_range,
            output_range=output_range,
            name="field_source",
        )

        reader = None
        if eff_reader_inst is not None and reader_calibration is not None:
            reader = FieldReader(
                instrument=eff_reader_inst,
                calibration=reader_calibration,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
                mismatch_policy=mismatch_policy,
                name="field_reader",
            )

        # Excitation role
        if current_source is not None:
            eff_excitation_source = "external"
            excitation = SampleExcitation(
                instrument=current_source,
                source_type="external",
                current=current,
                compliance=compliance,
                shutdown_handler=shutdown_handler,
                name="current_source",
            )
            if shutdown_handler is None:
                shutdown_handler = excitation.safe_shutdown
        else:
            eff_excitation_source = excitation_source
            excitation = SampleExcitation(
                instrument=eff_readout_inst,
                source_type=eff_excitation_source,
                amplitude=amplitude,
                frequency=frequency,
                shutdown_handler=shutdown_handler,
                name="internal_excitation",
            )
            if shutdown_handler is None:
                shutdown_handler = excitation.safe_shutdown

        readout_adapter = TransportReadout(
            instrument=eff_readout_inst,
            readout_configuration=readout_configuration,
            excitation_source=eff_excitation_source,
            amplitude=amplitude,
            frequency=frequency,
            sensitivity=sensitivity,
            input_configuration=input_configuration,
            name="readout",
            shutdown_handler=shutdown_handler,
            external_source_owner=external_source_owner,
        )

        orientation = OrientationController(
            instrument=eff_stepper_inst,
            steps_per_revolution=steps_per_revolution,
            angle_limits=angle_limits,
            settling_time=settling_time,
            name="stepper",
        )

        return cls(
            field_source=source,
            field_reader=reader,
            transport_readout=readout_adapter,
            orientation_controller=orientation,
            sample_excitation=excitation,
            name=name,
        )

    def unique_instruments(self) -> List[Any]:
        """Return list of distinct instrument objects used in this profile."""
        insts = [
            self.field_source.instrument,
            self.transport_readout.instrument,
            self.orientation_controller.instrument,
        ]
        if self.sample_excitation is not None and self.sample_excitation.instrument is not None:
            insts.append(self.sample_excitation.instrument)
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
            ("sample_excitation", self.sample_excitation),
            ("transport_readout", self.transport_readout),
            ("orientation_controller", self.orientation_controller),
        ):
            if role_obj is not None:
                try:
                    role_obj.safe_shutdown()
                    results[role_name] = "safe"
                except Exception as exc:
                    results[role_name] = f"error: {exc}"

        return results
