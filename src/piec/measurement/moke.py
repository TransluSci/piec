"""Point-by-point MOKE using a calibrated source and a voltage-reading DMM."""

from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.dmm.dmm import DMM
from piec.drivers.sourcemeter.sourcemeter import Sourcemeter
from piec.measurement.base import BaseMeasurement
from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    MeasurementSnapshot,
    RunRequest,
    RunState,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
)


class MokeSnapshot(MeasurementSnapshot):
    """Snapshot for MOKE measurements with raw, last_cycle, and cycle_average views."""

    def __init__(
        self,
        raw: Optional[pd.DataFrame] = None,
        last_cycle: Optional[pd.DataFrame] = None,
        cycle_average: Optional[pd.DataFrame] = None,
        completed_cycles: int = 0,
        field_column: str = "",
        *,
        run_id: str = "",
        generation: int = 0,
        sequence: int = 0,
        state: RunState = RunState.IDLE,
        safety: SafetyStatus = SafetyStatus.UNKNOWN,
        completed_steps: int = 0,
        total_steps: Optional[int] = None,
        message: str = "",
        timestamp: Optional[float] = None,
        views: Optional[Mapping[str, pd.DataFrame]] = None,
        **extra: Any,
    ):
        v = dict(views) if views else {}
        if raw is not None:
            v["raw"] = raw
            v["raw_window"] = raw
        if last_cycle is not None:
            v["last_cycle"] = last_cycle
        if cycle_average is not None:
            v["cycle_average"] = cycle_average
        extra["completed_cycles"] = completed_cycles
        extra["field_column"] = field_column
        super().__init__(
            run_id=run_id,
            generation=generation,
            sequence=sequence,
            state=state,
            safety=safety,
            completed_steps=completed_steps,
            total_steps=total_steps,
            message=message,
            timestamp=timestamp,
            views=v,
            **extra,
        )

    @property
    def completed_cycles(self) -> int:
        return self._extra.get("completed_cycles", 0)

    @property
    def field_column(self) -> str:
        return self._extra.get("field_column", "")


class MokeMeasurement(BaseMeasurement):
    """
    Standardized Point-by-point MOKE measurement using a calibrated source and a voltage-reading DMM.

    Follows the BaseMeasurement lifecycle and target MOKE contract:
    - Zero hardware I/O in __init__
    - Paced cancellable ramps for initial setpoint, point transitions, and safing ramp
    - Bounded live snapshots (raw view contains at most raw_window_points)
    - Full raw data recovery in finally on read/callback failure or stop
    - Cycle averaging excluding incomplete/partial cycles
    - Attempt-all software safing guaranteeing output disable even on ramp error
    - Plain lowercase columns and declared JSON unit metadata
    """

    snapshot_type = MokeSnapshot
    mtype = "moke"
    measurement_schema = "moke"

    def __init__(
        self,
        sourcemeter: Sourcemeter,
        dmm: DMM,
        *,
        calibration: FieldCalibration,
        output_values: Sequence[float],
        compliance: float,
        max_output_step: float,
        dwell_time: float = 0.1,
        ramp_delay: float = 0.01,
        n_cycles: int = 1,
        average_cycles: int = 10,
        raw_window_points: int = 1000,
        source_channel: Optional[int] = None,
        geometry: str = "unspecified",
        shutdown_handler: Optional[Callable[[Any], Any]] = None,
        field_reader: Optional[Callable[[], float]] = None,
        field_reader_unit: Optional[str] = None,
        field_reader_name: str = "",
        output_dir: Optional[Union[str, Path]] = None,
        notes: str = "",
    ):
        if not isinstance(calibration, FieldCalibration):
            raise TypeError("calibration must be a FieldCalibration")
        outputs = np.asarray(output_values, dtype=float)
        if outputs.ndim != 1 or len(outputs) < 3 or not np.isfinite(outputs).all():
            raise ValueError("output_values must contain at least three finite settings")
        if outputs[0] != outputs[-1] or np.ptp(outputs) == 0:
            raise ValueError("output_values must describe a nonconstant, closed cycle")
        calibration.field_at_output(outputs)  # Validate before touching hardware.

        for name, value in (("compliance", compliance), ("max_output_step", max_output_step)):
            if isinstance(value, bool) or not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name, value in (("dwell_time", dwell_time), ("ramp_delay", ramp_delay)):
            if isinstance(value, bool) or not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be nonnegative and finite")
        for name, value in (
            ("n_cycles", n_cycles), ("average_cycles", average_cycles),
            ("raw_window_points", raw_window_points),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        if shutdown_handler is not None and not callable(shutdown_handler):
            raise TypeError("shutdown_handler must be callable")
        if field_reader is not None:
            if not callable(field_reader):
                raise TypeError("field_reader must be a callable returning magnetic field")
            if field_reader_unit != calibration.field_unit:
                raise ValueError("field_reader_unit must explicitly match calibration.field_unit")
        elif field_reader_unit is not None or field_reader_name:
            raise ValueError("field reader units/name require a field_reader")

        self.sourcemeter = sourcemeter
        self.dmm = dmm
        self.field_reader = field_reader
        self.field_reader_unit = field_reader_unit
        self.field_reader_name = str(field_reader_name or "external field reader") if field_reader is not None else ""
        self.calibration = FieldCalibration(**calibration.to_dict())
        self.output_values = outputs.copy()
        self.compliance = float(compliance)
        self.max_output_step = float(max_output_step)
        self.dwell_time = float(dwell_time)
        self.ramp_delay = float(ramp_delay)
        self.n_cycles = int(n_cycles)
        self.average_cycles = int(average_cycles)
        self.raw_window_points = int(raw_window_points)
        self.source_channel = source_channel
        self.geometry = str(geometry)
        self.shutdown_handler = shutdown_handler

        # Check driver limits without performing hardware I/O
        self._validate_source_limits(np.r_[outputs, 0.0])
        limit_name = "current_compliance" if calibration.output_unit == "V" else "voltage_compliance"
        limit_bounds = getattr(sourcemeter, limit_name, (None, None))
        if limit_bounds[1] is not None and self.compliance > limit_bounds[1]:
            raise ValueError(f"compliance exceeds the driver's {limit_name} limit")

        # Runtime state
        self._sourcemeter_idn: Optional[str] = None
        self._dmm_idn: Optional[str] = None
        self._configured = False
        self._current_output = 0.0
        self._completed_cycles = 0
        self._cycles: List[pd.DataFrame] = []
        self._last_cycle = pd.DataFrame()
        self._cycle_average = pd.DataFrame()
        self._raw_data_bounded = pd.DataFrame()
        self._timestamp: float = time.time()

        self._data: Optional[pd.DataFrame] = None
        self._raw_data: Optional[pd.DataFrame] = None

        self.notes = str(notes)
        super().__init__(
            output_dir=output_dir,
            measurement_schema="moke",
            column_units=None,
            metadata=self._build_metadata_dict(),
        )

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def output_column(self) -> str:
        return "source_output"

    @property
    def field_column(self) -> str:
        """Selected field axis for raw, last-cycle, and averaged plots."""
        return self.measured_field_column if self.field_reader is not None else self.calibrated_field_column

    @property
    def calibrated_field_column(self) -> str:
        return "field_calibrated"

    @property
    def measured_field_column(self) -> str:
        return "field_measured"

    @property
    def column_units(self) -> Dict[str, Optional[str]]:
        if getattr(self, "_explicit_column_units", None) is not None:
            return dict(self._explicit_column_units)
        units: Dict[str, Optional[str]] = {
            "time": "s",
            "cycle": None,
            "point": None,
            "direction": None,
            "source_output": self.calibration.output_unit,
            "field_calibrated": self.calibration.field_unit,
            "detector_voltage": "V",
        }
        if self.field_reader is not None:
            units["field_measured"] = self.field_reader_unit or self.calibration.field_unit
            units["field_time"] = "s"
        return units

    @column_units.setter
    def column_units(self, value: Optional[Mapping[str, Optional[str]]]) -> None:
        self._explicit_column_units = dict(value) if value is not None else None

    @property
    def column_units_json(self) -> str:
        return json.dumps(self.column_units, sort_keys=True, separators=(",", ":"))

    @property
    def data(self) -> Optional[pd.DataFrame]:
        return self._data

    @data.setter
    def data(self, value: Optional[pd.DataFrame]) -> None:
        self._data = value

    @property
    def last_cycle(self) -> pd.DataFrame:
        return self._last_cycle

    @last_cycle.setter
    def last_cycle(self, value: pd.DataFrame) -> None:
        self._last_cycle = value

    @property
    def cycle_average(self) -> pd.DataFrame:
        return self._cycle_average

    @cycle_average.setter
    def cycle_average(self, value: pd.DataFrame) -> None:
        self._cycle_average = value

    @property
    def completed_cycles(self) -> int:
        return self._completed_cycles

    @completed_cycles.setter
    def completed_cycles(self, value: int) -> None:
        self._completed_cycles = value

    @property
    def processed(self) -> bool:
        return self._data is not None and not self._data.empty

    @property
    def abort_requested(self) -> bool:
        return self._coordinator.is_stop_requested

    @abort_requested.setter
    def abort_requested(self, value: bool) -> None:
        if value:
            self.request_stop()

    @property
    def metadata(self) -> pd.DataFrame:
        m = dict(self._build_metadata_dict())
        m.update(
            measurement_schema="moke",
            measurement_schema_version=1,
            column_units_json=self.column_units_json,
            mtype=self.mtype,
            timestamp=self._timestamp or 0.0,
            processed=self.processed,
            aborted=self.abort_requested,
        )
        if self.field_reader is not None:
            m["field_acquisition"] = "sequential after detector read"
        else:
            m["field_acquisition"] = "none"
        return pd.DataFrame([m])

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _build_metadata_dict(self) -> Dict[str, Any]:
        name_sm = getattr(self.sourcemeter, "name", None)
        sm_id = self._sourcemeter_idn if self._sourcemeter_idn is not None else (name_sm if isinstance(name_sm, str) else type(self.sourcemeter).__name__)
        name_dmm = getattr(self.dmm, "name", None)
        dmm_id = self._dmm_idn if self._dmm_idn is not None else (name_dmm if isinstance(name_dmm, str) else type(self.dmm).__name__)
        return {
            "geometry": self.geometry,
            "sourcemeter": sm_id,
            "dmm": dmm_id,
            "source_channel": self.source_channel if self.source_channel is not None else "",
            "calibration": json.dumps(self.calibration.to_dict()),
            "output_values": json.dumps(self.output_values.tolist()),
            "output_unit": self.calibration.output_unit,
            "field_unit": self.calibration.field_unit,
            "field_basis": (
                "measured field"
                if self.field_reader is not None
                else "calibrated source command; not a field measurement"
            ),
            "plot_field_column": self.field_column,
            "field_reader": self.field_reader_name,
            "field_reader_unit": self.field_reader_unit if self.field_reader_unit is not None else "",
            "field_acquisition": (
                "sequential after detector read"
                if self.field_reader is not None
                else "none"
            ),
            "compliance": self.compliance,
            "compliance_unit": "A" if self.calibration.output_unit == "V" else "V",
            "max_output_step": self.max_output_step,
            "dwell_time": self.dwell_time,
            "ramp_delay": self.ramp_delay,
            "n_cycles": self.n_cycles,
            "completed_cycles": self._completed_cycles,
            "average_cycles": self.average_cycles,
            "raw_window_points": self.raw_window_points,
            "processed": self.processed,
            "shutdown_policy": "custom" if self.shutdown_handler else "ramp to electrical zero, output off",
        }

    def _source_call(self, method: str, **kwargs: Any) -> Any:
        if self.source_channel is not None:
            kwargs["channel"] = self.source_channel
        return getattr(self.sourcemeter, method)(**kwargs)

    def _validate_source_limits(self, outputs: Sequence[float]) -> None:
        name = "voltage" if self.calibration.output_unit == "V" else "current"
        bounds = getattr(self.sourcemeter, name, (None, None))
        if bounds[0] is not None and np.any(np.asarray(outputs) < bounds[0]):
            raise ValueError(f"source output is below the driver's {name} limit")
        if bounds[1] is not None and np.any(np.asarray(outputs) > bounds[1]):
            raise ValueError(f"source output exceeds the driver's {name} limit")

    def _cancellable_dwell(self, duration: float) -> bool:
        """Dwell in small increments checking cooperative cancellation using monotonic clock. Returns True if stopped."""
        if duration <= 0:
            return self._coordinator.is_stop_requested
        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            if self._coordinator.is_stop_requested:
                return True
            remaining = end_time - time.monotonic()
            time.sleep(min(0.01, max(0.0, remaining)))
        return self._coordinator.is_stop_requested

    def _ramp_output(self, target: float, interruptible: bool = True) -> bool:
        """Paced ramp to target voltage/current in steps of at most max_output_step."""
        diff = target - self._current_output
        if abs(diff) > 1e-9:
            steps = max(1, int(math.ceil(abs(diff) / self.max_output_step)))
            ramp_points = np.linspace(self._current_output, target, steps + 1)[1:]
            for value in ramp_points:
                if interruptible and self._coordinator.is_stop_requested:
                    return False
                val = float(value)
                if self.calibration.output_unit == "V":
                    self._source_call("set_source_voltage", voltage=val)
                else:
                    self._source_call("set_source_current", current=val)
                self._current_output = val
                if self.ramp_delay > 0:
                    if interruptible:
                        if self._cancellable_dwell(self.ramp_delay):
                            return False
                    else:
                        time.sleep(self.ramp_delay)
        if not (interruptible and self._coordinator.is_stop_requested):
            final_val = float(target)
            if self.calibration.output_unit == "V":
                self._source_call("set_source_voltage", voltage=final_val)
            else:
                self._source_call("set_source_current", current=final_val)
            self._current_output = final_val
        return not (interruptible and self._coordinator.is_stop_requested)

    def _read_measured_field(self) -> float:
        assert self.field_reader is not None
        value = self.field_reader()
        if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
            raise ValueError("field_reader must return a finite scalar field value")
        try:
            val_float = float(value)
        except (ValueError, TypeError) as error:
            raise ValueError("field_reader must return a finite scalar field value") from error
        if not np.isfinite(val_float):
            raise ValueError("field_reader returned a non-finite field value")
        return val_float

    def _get_empty_dataframe(self) -> pd.DataFrame:
        cols = [
            "time", "cycle", "point", "direction",
            self.output_column, self.calibrated_field_column, "detector_voltage",
        ]
        if self.field_reader is not None:
            cols.extend([self.measured_field_column, "field_time"])
        return pd.DataFrame(columns=cols)

    # ========================================================================
    # Protected Subclass Hooks (BaseMeasurement implementation)
    # ========================================================================

    def _reset_run_views(self) -> None:
        self._raw_data_bounded = pd.DataFrame()
        self._cycles = []
        self._completed_cycles = 0
        self._last_cycle = pd.DataFrame()
        self._cycle_average = pd.DataFrame()
        self._configured = False
        self._timestamp = time.time()
        self.measurement_metadata.update(self._build_metadata_dict())

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        """Validate run options before reservation."""
        super()._validate_options(options)
        if options:
            raise ValueError(f"Unknown MOKE options: {sorted(options)}")

    def _configure_instruments(self, request: RunRequest) -> None:
        """Configure sourcemeter and DMM with outputs disabled."""
        self._configured = False
        # Output off first before any programming or queries
        self._source_call("output", on=False)

        # Query IDNs safely if available
        if not self._sourcemeter_idn and hasattr(self.sourcemeter, "idn"):
            try:
                self._sourcemeter_idn = str(self.sourcemeter.idn())
            except Exception:
                pass
        if not self._dmm_idn and hasattr(self.dmm, "idn"):
            try:
                self._dmm_idn = str(self.dmm.idn())
            except Exception:
                pass

        if self.calibration.output_unit == "V":
            self._source_call("configure_voltage_source", voltage=0.0, current_compliance=self.compliance)
        else:
            self._source_call("configure_current_source", current=0.0, voltage_compliance=self.compliance)
        self._current_output = 0.0

        # Configure DMM for DC voltage reading
        self.dmm.set_sense_function(sense_func="VOLT")
        self.dmm.set_measurement_coupling(coupling="DC")

        self._configured = True

    def _capture_data(
        self,
        request: RunRequest,
        on_update: Optional[Callable[[Any], None]],
    ) -> pd.DataFrame:
        """
        Execute point-by-point MOKE data acquisition.

        Turns output on, pre-ramps to first setpoint, iterates cycles and points,
        publishes bounded live snapshots, and preserves full raw data in finally.
        """
        if self._coordinator.is_stop_requested:
            return self._get_empty_dataframe()

        self._source_call("output", on=True)

        # Cancellable pre-ramp to first setpoint
        if not self._ramp_output(self.output_values[0], interruptible=True):
            return self._get_empty_dataframe()

        started = time.monotonic()
        fields = self.calibration.field_at_output(self.output_values)
        directions = np.sign(np.r_[fields[1] - fields[0], np.diff(fields)])

        collected_rows: List[Dict[str, Any]] = []
        self._cycles = []
        self._completed_cycles = 0
        self._last_cycle = pd.DataFrame()
        self._cycle_average = pd.DataFrame()

        try:
            for cycle in range(self.n_cycles):
                for point, output in enumerate(self.output_values):
                    if self._coordinator.is_stop_requested:
                        break

                    target_out = float(output)
                    if not self._ramp_output(target_out, interruptible=True):
                        break

                    if self._cancellable_dwell(self.dwell_time):
                        break

                    voltage = float(self.dmm.get_voltage())
                    if not np.isfinite(voltage):
                        raise ValueError("DMM returned a non-finite detector voltage")

                    row: Dict[str, Any] = {
                        "time": time.monotonic() - started,
                        "cycle": cycle,
                        "point": point,
                        "direction": float(directions[point]),
                        self.output_column: target_out,
                        self.calibrated_field_column: float(fields[point]),
                        "detector_voltage": voltage,
                    }
                    if self.field_reader is not None:
                        row[self.measured_field_column] = self._read_measured_field()
                        row["field_time"] = time.monotonic() - started

                    collected_rows.append(row)

                    # Update raw data and bounded live view
                    self._raw_data_bounded = pd.DataFrame(collected_rows[-self.raw_window_points:])

                    # Check for complete cycle
                    if point == len(self.output_values) - 1:
                        cycle_frame = pd.DataFrame(collected_rows[-len(self.output_values):])
                        self._last_cycle = cycle_frame
                        self._completed_cycles += 1
                        self._cycles.append(cycle_frame)
                        self._cycles = self._cycles[-self.average_cycles:]

                        avg = cycle_frame[
                            ["point", "direction", self.output_column, self.calibrated_field_column]
                        ].reset_index(drop=True)
                        avg_cols = ["detector_voltage"]
                        if self.field_reader is not None:
                            avg_cols.append(self.measured_field_column)
                        for col in avg_cols:
                            avg[col] = np.mean([f[col].to_numpy() for f in self._cycles], axis=0)
                        avg["cycles_averaged"] = len(self._cycles)
                        self._cycle_average = avg

                    # Publish live snapshot
                    snap = self.publish_snapshot(
                        views={
                            "raw": self._raw_data_bounded,
                            "raw_window": self._raw_data_bounded,
                            "last_cycle": self._last_cycle,
                            "cycle_average": self._cycle_average,
                        },
                        completed_cycles=self._completed_cycles,
                        field_column=self.field_column,
                        geometry=self.geometry,
                        completed_steps=len(collected_rows),
                        total_steps=self.n_cycles * len(self.output_values),
                    )
                    if on_update is not None:
                        on_update(snap)

                if self._coordinator.is_stop_requested:
                    break

        finally:
            if collected_rows:
                self._raw_data = pd.DataFrame(collected_rows)
                self._raw_data_bounded = self._raw_data.tail(self.raw_window_points).copy()
            elif self._raw_data is None:
                self._raw_data = self._get_empty_dataframe()
                self._raw_data_bounded = pd.DataFrame()
            self.measurement_metadata.update(self._build_metadata_dict())

        return self._raw_data.copy()

    def _safe_shutdown(
        self, recorder: Optional[ShutdownAttemptRecorder] = None
    ) -> SafetyReport:
        """
        Hardware shutdown attempting all actions.

        Safing ramp to electrical zero with max_output_step and ramp_delay,
        followed by guaranteed output disable even if the zero ramp fails,
        plus any custom safe_shutdown procedure.
        """
        if recorder is None:
            recorder = ShutdownAttemptRecorder()

        self._safing_failure_exc: Optional[BaseException] = None

        if self.shutdown_handler is not None:
            def custom_shutdown():
                try:
                    self.shutdown_handler(self.sourcemeter)
                except BaseException as exc:
                    if self._safing_failure_exc is None:
                        self._safing_failure_exc = exc
                    raise

            recorder.record_action(
                name="custom_safe_shutdown",
                action_fn=custom_shutdown,
            )
            recorder.record_action(
                name="sourcemeter_disable_output",
                action_fn=lambda: self._source_call("output", on=False),
            )
        else:
            def ramp_zero():
                if self._configured:
                    try:
                        self._ramp_output(0.0, interruptible=False)
                    except BaseException as exc:
                        if self._safing_failure_exc is None:
                            self._safing_failure_exc = exc
                        raise

            recorder.record_action(
                name="sourcemeter_ramp_to_zero",
                action_fn=ramp_zero,
            )
            recorder.record_action(
                name="sourcemeter_disable_output",
                action_fn=lambda: self._source_call("output", on=False),
            )

        self._current_output = 0.0
        return recorder.build_report()

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        """Return standardized ordered columns for MOKE dataset."""
        if raw_data.empty:
            return self._get_empty_dataframe()
        cols = [
            "time", "cycle", "point", "direction",
            self.output_column, self.calibrated_field_column, "detector_voltage",
        ]
        if self.field_reader is not None:
            cols.extend([self.measured_field_column, "field_time"])
        active_cols = [c for c in cols if c in raw_data.columns]
        df = raw_data[active_cols].copy()
        self._data = df.copy()
        self.measurement_metadata.update(self._build_metadata_dict())
        self.measurement_metadata["processed"] = True
        return df

    # ========================================================================
    # Owner-scoped manual source helpers
    # ========================================================================

    @contextmanager
    def _command_lease(self):
        if self.run_state.is_active:
            if self._active_owner_thread_id != threading.get_ident():
                raise ConcurrentRunError("Hardware commands require the execution owner")
            yield
        else:
            with self._idle_command_lease():
                yield

    def set_output(self, output: float) -> bool:
        """Program a direct source setting; does not enable the output."""
        with self._command_lease():
            if not self._configured:
                raise RuntimeError("configure the sourcemeter before setting output")
            if not np.isscalar(output):
                raise ValueError("output must be a scalar")
            self.calibration.field_at_output(output)
            self._validate_source_limits([output])
            return self._ramp_output(float(output))

    def set_field(self, field: float) -> bool:
        """Program the calibrated source setting for a requested field."""
        return self.set_output(self.calibration.output_at_field(field))
