"""
Contract tests for BaseMeasurement full-run execution engine.

Fulfills Checkpoint 9a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Canonical full-run phase ordering (STARTING -> CONFIGURING -> RUNNING -> SAFING -> ANALYZING -> SAVING -> COMPLETED);
- Stop-before-start zero-I/O aborts with safety NOT_NEEDED;
- Cooperative Stop during configuration and capture;
- Safing execution guarantee and error precedence;
- Outcome and persistence matrix compliance;
- Single RunRecord and TerminalEvent per reservation;
- Option validation before reservation.
"""

from typing import Any, Callable, List, Mapping, Optional
import pandas as pd
import pytest

from piec.measurement.base import BaseMeasurement
from piec.measurement.contracts import (
    HardwareSafetyError,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAction,
    SafetyReport,
    SafetyStatus,
    TerminalEvent,
)


# ============================================================================
# Test Fixtures & Mock Measurement Subclasses
# ============================================================================

class FakeMeasurement(BaseMeasurement):
    """Configurable mock measurement subclass for engine contract testing."""

    def __init__(self) -> None:
        super().__init__()
        self.call_log: List[tuple[str, RunState]] = []
        self.config_error: Optional[BaseException] = None
        self.capture_error: Optional[BaseException] = None
        self.safing_error: Optional[BaseException] = None
        self.analysis_error: Optional[BaseException] = None
        self.publish_error: Optional[BaseException] = None
        self.stop_during_config: bool = False
        self.stop_during_capture: bool = False
        self.raw_data_to_return: Optional[pd.DataFrame] = pd.DataFrame(
            {"time": [0.0, 1.0, 2.0], "voltage": [10.0, 20.0, 30.0]}
        )

    def _configure_instruments(self, request: RunRequest) -> None:
        self.call_log.append(("configure", self.run_state))
        if self.config_error:
            raise self.config_error
        if self.stop_during_config:
            self.request_stop()

    def _capture_data(
        self, request: RunRequest, on_update: Optional[Callable[[Any], None]]
    ) -> pd.DataFrame:
        self.call_log.append(("capture", self.run_state))
        if on_update:
            on_update({"step": 1})
        if self.capture_error:
            raise self.capture_error
        if self.stop_during_capture:
            self.request_stop()
        return (
            self.raw_data_to_return.copy()
            if self.raw_data_to_return is not None
            else pd.DataFrame()
        )

    def _safe_shutdown(self) -> Any:
        self.call_log.append(("safing", self.run_state))
        if self.safing_error:
            raise self.safing_error
        return [SafetyAction(name="zero_output", attempted=True, succeeded=True, duration_seconds=0.01)]

    def _analyze_data(self, raw_data: pd.DataFrame, request: RunRequest) -> pd.DataFrame:
        self.call_log.append(("analyze", self.run_state))
        if self.analysis_error:
            raise self.analysis_error
        df = raw_data.copy()
        df["voltage_scaled"] = df["voltage"] * 2.0
        return df

    def _publish_data(
        self, data: pd.DataFrame, request: RunRequest, is_partial: bool = False
    ) -> Optional[str]:
        self.call_log.append(("publish", self.run_state))
        if self.publish_error:
            raise self.publish_error
        prefix = "partial_" if is_partial else "final_"
        return f"/virtual/path/{prefix}{request.options.get('run_name', 'data')}.csv"


# ============================================================================
# 1. Canonical Full-Run Execution (Section 4.4)
# ============================================================================

class TestCanonicalRunExecution:
    """Verify canonical forward phase progression and success outputs."""

    def test_clean_success_with_saving(self):
        meas = FakeMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        df = meas.run_experiment(save=True, options={"run_name": "test1"})

        # Check call sequence and phase states
        expected_phases = [
            ("configure", RunState.CONFIGURING),
            ("capture", RunState.RUNNING),
            ("safing", RunState.SAFING),
            ("analyze", RunState.ANALYZING),
            ("publish", RunState.SAVING),
        ]
        assert meas.call_log == expected_phases

        # Terminal state & metadata
        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.filename == "/virtual/path/final_test1.csv"
        assert meas.partial_filename is None
        assert list(df.columns) == ["time", "voltage", "voltage_scaled"]
        assert meas.data is not None
        assert meas.raw_data is not None
        assert "voltage_scaled" not in meas.raw_data.columns

        # Terminal event
        assert len(events) == 1
        ev = events[0]
        assert ev.state == RunState.COMPLETED
        assert ev.safety.status == SafetyStatus.SAFE
        assert ev.filename == "/virtual/path/final_test1.csv"
        assert ev.partial_filename is None

    def test_clean_success_without_saving(self):
        meas = FakeMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        df = meas.run_experiment(save=False)

        # Publish should NOT be in call log
        called_actions = [a[0] for a in meas.call_log]
        assert "publish" not in called_actions
        assert meas.call_log == [
            ("configure", RunState.CONFIGURING),
            ("capture", RunState.RUNNING),
            ("safing", RunState.SAFING),
            ("analyze", RunState.ANALYZING),
        ]

        assert meas.run_state == RunState.COMPLETED
        assert meas.filename is None
        assert meas.partial_filename is None
        assert len(df) == 3
        assert len(events) == 1
        assert events[0].filename is None


# ============================================================================
# 2. Stop-Before-Start Contract (Section 4.2 & 4.4)
# ============================================================================

class TestStopBeforeStart:
    """Verify pre-latched Stop aborts without touching any hardware hooks."""

    def test_stop_prelatched_aborts_without_io(self):
        meas = FakeMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        # Pre-reserve and latch stop on coordinator before worker starts
        token = meas._reserve()
        meas.request_stop()
        assert meas.run_state == RunState.STOPPING

        result_df = meas.run_experiment(token=token)

        # Zero hardware hooks called
        assert len(meas.call_log) == 0

        # Lifecycle and safety
        assert meas.run_state == RunState.ABORTED
        assert meas.safety_status == SafetyStatus.NOT_NEEDED
        assert meas.filename is None
        assert meas.partial_filename is None
        assert isinstance(result_df, pd.DataFrame)
        assert result_df.empty

        # Exactly 1 record and 1 terminal event
        assert len(meas.run_records) == 1
        assert meas.last_run_record.state == RunState.ABORTED
        assert meas.last_run_record.safety.status == SafetyStatus.NOT_NEEDED

        assert len(events) == 1
        assert events[0].state == RunState.ABORTED
        assert events[0].safety.status == SafetyStatus.NOT_NEEDED


# ============================================================================
# 3. Cooperative Stop During Execution
# ============================================================================

class TestCooperativeStopDuringExecution:
    """Verify Stop during configuration or capture safely aborts."""

    def test_stop_during_capture_saves_partial_when_requested(self):
        meas = FakeMeasurement()
        meas.stop_during_capture = True
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        # Run with save_partial=True
        df = meas.run_experiment(save=True, save_partial=True, options={"run_name": "partial_run"})

        # Capture ran, safing ran, analysis skipped, publish ran for partial
        called_actions = [a[0] for a in meas.call_log]
        assert called_actions == ["configure", "capture", "safing", "publish"]
        assert "analyze" not in called_actions

        assert meas.run_state == RunState.ABORTED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.filename is None
        assert meas.partial_filename == "/virtual/path/partial_partial_run.csv"

        # Raw partial data returned to caller (not analyzed)
        assert "voltage_scaled" not in df.columns
        assert list(df.columns) == ["time", "voltage"]

        assert len(events) == 1
        assert events[0].state == RunState.ABORTED
        assert events[0].partial_filename == "/virtual/path/partial_partial_run.csv"

    def test_stop_during_capture_no_save_when_save_is_false(self):
        meas = FakeMeasurement()
        meas.stop_during_capture = True

        df = meas.run_experiment(save=False, save_partial=False)

        called_actions = [a[0] for a in meas.call_log]
        assert "publish" not in called_actions
        assert "analyze" not in called_actions
        assert meas.run_state == RunState.ABORTED
        assert meas.filename is None
        assert meas.partial_filename is None

    def test_stop_during_configuration_skips_capture(self):
        meas = FakeMeasurement()
        meas.stop_during_config = True

        meas.run_experiment()

        called_actions = [a[0] for a in meas.call_log]
        assert called_actions == ["configure", "safing"]
        assert "capture" not in called_actions
        assert "analyze" not in called_actions
        assert meas.run_state == RunState.ABORTED


# ============================================================================
# 4. Fault Handling and Error Precedence (Section 5.1 & 5.3)
# ============================================================================

class TestFaultHandlingAndErrorPrecedence:
    """Verify safing guarantee and error precedence across all failure modes."""

    def test_configuration_error_safes_and_reraises(self):
        meas = FakeMeasurement()
        meas.config_error = ConnectionError("Instrument connection lost")
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        with pytest.raises(ConnectionError, match="Instrument connection lost"):
            meas.run_experiment()

        called_actions = [a[0] for a in meas.call_log]
        assert called_actions == ["configure", "safing"]
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_type == "ConnectionError"
        assert meas.last_run_record.primary_error_phase == "CONFIGURING"

        assert len(events) == 1
        assert events[0].state == RunState.FAILED
        assert events[0].primary_error_type == "ConnectionError"

    def test_capture_error_safes_and_reraises(self):
        meas = FakeMeasurement()
        meas.capture_error = TimeoutError("Scope timeout")

        with pytest.raises(TimeoutError, match="Scope timeout"):
            meas.run_experiment()

        called_actions = [a[0] for a in meas.call_log]
        assert called_actions == ["configure", "capture", "safing"]
        assert "analyze" not in called_actions
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "RUNNING"

    def test_callback_error_treated_as_acquisition_failure(self):
        meas = FakeMeasurement()
        def faulty_callback(update):
            raise ValueError("Callback crash in user UI")

        with pytest.raises(ValueError, match="Callback crash"):
            meas.run_experiment(on_update=faulty_callback)

        assert "safing" in [a[0] for a in meas.call_log]
        assert meas.run_state == RunState.FAILED

    def test_analysis_error_occurs_after_safing(self):
        meas = FakeMeasurement()
        meas.analysis_error = ZeroDivisionError("Division by zero in fitting")

        with pytest.raises(ZeroDivisionError, match="Division by zero"):
            meas.run_experiment(save_partial=True)

        called_actions = [a[0] for a in meas.call_log]
        # Safing ran before analysis!
        assert called_actions[:3] == ["configure", "capture", "safing"]
        assert called_actions[3] == "analyze"
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "ANALYZING"

    def test_safing_error_alone_raises_hardware_safety_error(self):
        meas = FakeMeasurement()
        meas.safing_error = RuntimeError("Relay failed to open")

        with pytest.raises(HardwareSafetyError, match="Hardware safety could not be verified"):
            meas.run_experiment()

        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.UNSAFE
        assert meas.last_run_record.safety.status == SafetyStatus.UNSAFE

    def test_primary_capture_error_takes_precedence_over_safing_error(self):
        meas = FakeMeasurement()
        meas.capture_error = ValueError("Primary acquisition failure")
        meas.safing_error = RuntimeError("Secondary shutdown failure")

        # Primary error must be re-raised, not the secondary shutdown error
        with pytest.raises(ValueError, match="Primary acquisition failure"):
            meas.run_experiment()

        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_type == "ValueError"
        assert meas.last_run_record.primary_error_message == "Primary acquisition failure"
        # Secondary error recorded
        assert len(meas.last_run_record.secondary_errors) > 0
        assert "Secondary shutdown failure" in meas.last_run_record.secondary_errors[0]


# ============================================================================
# 5. One Record & One Event per Reservation
# ============================================================================

class TestOneRecordAndEventPerReservation:
    """Verify exact one-record and one-event contract across sequential repeat runs."""

    def test_repeat_runs_emit_distinct_records_and_events(self):
        meas = FakeMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        # Run 1: Success
        meas.run_experiment()
        assert len(meas.run_records) == 1
        assert len(events) == 1
        assert events[0].generation == 1
        assert events[0].state == RunState.COMPLETED

        # Run 2: Pre-latched Abort
        token2 = meas._reserve()
        meas.request_stop()
        meas.run_experiment(token=token2)
        assert len(meas.run_records) == 2
        assert len(events) == 2
        assert events[1].generation == 2
        assert events[1].state == RunState.ABORTED

        # Run 3: Failure
        meas.capture_error = RuntimeError("Fail on run 3")
        with pytest.raises(RuntimeError):
            meas.run_experiment()

        assert len(meas.run_records) == 3
        assert len(events) == 3
        assert events[2].generation == 3
        assert events[2].state == RunState.FAILED

        # History order
        assert meas.run_records[0].generation == 1
        assert meas.run_records[1].generation == 2
        assert meas.run_records[2].generation == 3
        assert meas.last_run_record == meas.run_records[2]


# ============================================================================
# 6. Option Validation
# ============================================================================

class TestOptionValidation:
    """Verify options are validated before reservation."""

    def test_invalid_option_type_rejected_before_reservation(self):
        meas = FakeMeasurement()
        with pytest.raises(TypeError, match="options must be a Mapping"):
            meas.run_experiment(options="not_a_mapping")

        # Did not reserve or change state
        assert meas.run_state == RunState.IDLE
        assert meas.last_run_record is None
