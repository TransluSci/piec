"""
Standardized IV sweep measurement class.

Fulfills Checkpoint 13 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'iv_sweep', version 1;
- Plain lowercase columns: ['voltage', 'current'] with V/A metadata units;
- Inherits BaseMeasurement with shared lifecycle, runner, and session support;
- Zero instrument I/O in __init__;
- Protected hooks: _validate_options, _configure_instruments, _capture_data,
  _safe_shutdown, _analyze_data;
- Paced cancellable ramping to start voltage and cancellable acquisition reads;
- Independent paced safing ramp to electrical zero;
- Guaranteed output disable attempt even if safing ramp fails.
"""

from __future__ import annotations

import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .base import BaseMeasurement
from .contracts import (
    RunRequest,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
)


class IVSweep(BaseMeasurement):
    """
    Current-Voltage (IV) sweep measurement using a sourcemeter.

    Applies a sequence of DC voltages across a device under test (DUT)
    and measures resulting voltage and current.

    Inherits from BaseMeasurement to provide standardized lifecycle,
    execution ownership, bounded snapshot publishing, and Windows/SMB-aware
    atomic persistence.
    """

    mtype = "iv_sweep"
    supports_pause = False

    def __init__(
        self,
        sourcemeter: Any,
        *,
        v_start: float = 0.0,
        v_stop: float = 1.0,
        num_steps: int = 50,
        current_compliance: float = 0.1,
        dwell_time: float = 0.1,
        sense_mode: str = "2W",
        ramp_step: float = 0.1,
        ramp_delay: float = 0.01,
        output_dir: Optional[Union[str, Path]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """
        Initialize IV sweep parameters without performing hardware I/O.

        Args:
            sourcemeter: Sourcemeter driver object (Keithley 2400, VirtualSourcemeter, etc.).
            v_start: Starting voltage in Volts (keyword-only).
            v_stop: Ending voltage in Volts (keyword-only).
            num_steps: Number of voltage steps in the sweep (keyword-only).
            current_compliance: Maximum current compliance limit in Amperes (keyword-only).
            dwell_time: Stabilization dwell time at each step in seconds (keyword-only).
            sense_mode: Sensing mode, '2W' or '4W' (keyword-only).
            ramp_step: Voltage step size for pre-sweep and safing ramps in Volts (keyword-only).
            ramp_delay: Delay between ramp steps in seconds (keyword-only).
            output_dir: Target directory for data persistence (keyword-only).
            metadata: Optional additional user metadata mapping (keyword-only).
        """
        self.sourcemeter = sourcemeter
        self.v_start = float(v_start)
        self.v_stop = float(v_stop)
        self.num_steps = int(num_steps)
        if self.num_steps < 1:
            raise ValueError(f"num_steps must be >= 1, got {self.num_steps}")

        self.current_compliance = float(current_compliance)
        if (
            isinstance(current_compliance, bool)
            or not math.isfinite(self.current_compliance)
            or self.current_compliance <= 0
        ):
            raise ValueError(
                f"current_compliance must be a positive finite number, got {current_compliance}"
            )

        self.dwell_time = float(dwell_time)
        if not math.isfinite(self.dwell_time) or self.dwell_time < 0:
            raise ValueError(f"dwell_time cannot be negative, got {dwell_time}")

        self.sense_mode = str(sense_mode)
        if self.sense_mode not in ("2W", "4W"):
            raise ValueError(f"sense_mode must be '2W' or '4W', got {sense_mode!r}")

        self.ramp_step = float(ramp_step)
        if not math.isfinite(self.ramp_step) or self.ramp_step <= 0:
            raise ValueError(f"ramp_step must be positive, got {ramp_step}")

        self.ramp_delay = float(ramp_delay)
        if not math.isfinite(self.ramp_delay) or self.ramp_delay < 0:
            raise ValueError(f"ramp_delay cannot be negative, got {ramp_delay}")

        self._current_voltage: float = 0.0

        # Initial metadata dictionary (zero I/O: do not call sourcemeter.idn() here)
        initial_metadata: dict[str, Any] = {
            "v_start": self.v_start,
            "v_stop": self.v_stop,
            "num_steps": self.num_steps,
            "current_compliance": self.current_compliance,
            "dwell_time": self.dwell_time,
            "sense_mode": self.sense_mode,
            "ramp_step": self.ramp_step,
            "ramp_delay": self.ramp_delay,
        }
        if metadata is not None:
            initial_metadata.update(dict(metadata))

        super().__init__(
            output_dir=output_dir,
            measurement_schema="iv_sweep",
            column_units={"voltage": "V", "current": "A"},
            metadata=initial_metadata,
        )

    # ------------------------------------------------------------------------
    # Protected Hooks
    # ------------------------------------------------------------------------

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        """Validate run options before reservation or hardware I/O."""
        super()._validate_options(options)
        if options is None:
            return
        for key, value in options.items():
            if key == "compliance_current":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise ValueError("compliance_current must be a positive finite number")
            else:
                raise ValueError(f"Unknown option: {key}")

    def _configure_instruments(self, request: RunRequest) -> None:
        """
        Configure sourcemeter at electrical zero with output disabled.

        Executed during the CONFIGURING phase on the execution owner thread.
        """
        compliance = self.current_compliance
        if request.options and "compliance_current" in request.options:
            compliance = float(request.options["compliance_current"])

        # Query instrument identity on worker thread during configuration
        try:
            idn = str(self.sourcemeter.idn())
        except Exception:
            idn = "UNKNOWN"
        self.measurement_metadata["sourcemeter"] = idn
        self.measurement_metadata["current_compliance"] = compliance
        self.measurement_metadata["timestamp"] = time.time()

        # Configure at electrical zero with current compliance
        self.sourcemeter.configure_voltage_source(
            channel=1,
            voltage=0.0,
            current_compliance=compliance,
        )
        self.sourcemeter.set_sense_mode(channel=1, sense_mode=self.sense_mode)
        self.sourcemeter.output(channel=1, on=False)
        self._current_voltage = 0.0

    def _cancellable_dwell(self, duration: float) -> None:
        """Dwell in small time increments checking cooperative cancellation."""
        if duration <= 0:
            return
        end_time = time.time() + duration
        while time.time() < end_time:
            if self._coordinator.is_stop_requested:
                break
            remaining = end_time - time.time()
            time.sleep(min(0.05, max(0.0, remaining)))

    def _ramp_to(self, target_voltage: float) -> None:
        """Paced ramp to target voltage in steps of at most ramp_step."""
        diff = target_voltage - self._current_voltage
        if abs(diff) > 1e-9:
            steps = max(1, int(math.ceil(abs(diff) / self.ramp_step)))
            ramp_points = np.linspace(self._current_voltage, target_voltage, steps + 1)[1:]
            for v in ramp_points:
                if self._coordinator.is_stop_requested:
                    break
                self.sourcemeter.set_source_voltage(channel=1, voltage=float(v))
                self._current_voltage = float(v)
                if self.ramp_delay > 0:
                    self._cancellable_dwell(self.ramp_delay)
        if not self._coordinator.is_stop_requested:
            self.sourcemeter.set_source_voltage(channel=1, voltage=float(target_voltage))
            self._current_voltage = float(target_voltage)

    def _capture_data(
        self,
        request: RunRequest,
        on_update: Optional[Callable[[Any], None]],
    ) -> pd.DataFrame:
        """
        Execute cancellable IV sweep data acquisition.

        Turns on output, ramps to v_start, sweeps to v_stop, publishes
        snapshots, and preserves raw data in finally.
        """
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=["voltage", "current"])

        self.sourcemeter.output(channel=1, on=True)

        # Cancellable pre-sweep ramp from 0.0 to v_start
        self._ramp_to(self.v_start)
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=["voltage", "current"])

        voltages = np.linspace(self.v_start, self.v_stop, self.num_steps)
        collected_rows: list[dict[str, float]] = []

        try:
            for i, v in enumerate(voltages):
                if self._coordinator.is_stop_requested:
                    break

                target_v = float(v)
                self.sourcemeter.set_source_voltage(channel=1, voltage=target_v)
                self._current_voltage = target_v

                self._cancellable_dwell(self.dwell_time)
                if self._coordinator.is_stop_requested:
                    break

                measured_v = float(self.sourcemeter.get_voltage(channel=1))
                measured_i = float(self.sourcemeter.get_current(channel=1))

                row = {"voltage": measured_v, "current": measured_i}
                collected_rows.append(row)

                self._raw_data = pd.DataFrame(collected_rows, columns=["voltage", "current"])
                snap = self.publish_snapshot(
                    views={"raw": self._raw_data},
                    completed_steps=len(collected_rows),
                    total_steps=self.num_steps,
                    current_voltage=target_v,
                )
                if on_update is not None:
                    on_update(snap)
        finally:
            if collected_rows:
                self._raw_data = pd.DataFrame(collected_rows, columns=["voltage", "current"])
            elif self._raw_data is None:
                self._raw_data = pd.DataFrame(columns=["voltage", "current"])

        return self._raw_data.copy()

    def _safe_shutdown(
        self, recorder: Optional[ShutdownAttemptRecorder] = None
    ) -> SafetyReport:
        """
        Paced hardware shutdown attempting all actions.

        Guarantees that output disable is attempted even if the voltage ramp fails.
        """
        if recorder is None:
            recorder = ShutdownAttemptRecorder()

        # Action 1: Safing ramp back to electrical zero (0.0 V)
        def ramp_to_zero():
            if abs(self._current_voltage) > 1e-9:
                diff = 0.0 - self._current_voltage
                steps = max(1, int(math.ceil(abs(diff) / self.ramp_step)))
                ramp_points = np.linspace(self._current_voltage, 0.0, steps + 1)[1:]
                for v in ramp_points:
                    self.sourcemeter.set_source_voltage(channel=1, voltage=float(v))
                    self._current_voltage = float(v)
                    if self.ramp_delay > 0:
                        time.sleep(self.ramp_delay)
            self.sourcemeter.set_source_voltage(channel=1, voltage=0.0)
            self._current_voltage = 0.0

        recorder.record_action(
            name="sourcemeter_ramp_to_zero",
            action_fn=ramp_to_zero,
        )

        # Action 2: Disable output - MUST be attempted even if ramp_to_zero failed!
        recorder.record_action(
            name="sourcemeter_disable_output",
            action_fn=lambda: self.sourcemeter.output(channel=1, on=False),
        )

        # Action 3: Confirm voltage set to 0.0 V
        def zero_voltage():
            self.sourcemeter.set_source_voltage(channel=1, voltage=0.0)
            self._current_voltage = 0.0

        recorder.record_action(
            name="sourcemeter_zero_voltage",
            action_fn=zero_voltage,
        )

        return recorder.build_report()

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        """Scientific analysis for IV data: return standardized columns."""
        if raw_data.empty:
            return pd.DataFrame(columns=["voltage", "current"])
        return raw_data[["voltage", "current"]].copy()

