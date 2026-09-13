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


# ============================================================================
# 7. State Transitions & Reservation Tokens
# ============================================================================

class TestStateTransitionsAndTokens:
    """Verify RunState properties, legal transitions, and reservation token validation."""

    def test_run_state_properties(self):
        assert RunState.IDLE.is_terminal is False
        assert RunState.IDLE.is_active is False
        assert RunState.STARTING.is_active is True
        assert RunState.RUNNING.is_active is True
        assert RunState.COMPLETED.is_terminal is True
        assert RunState.ABORTED.is_terminal is True
        assert RunState.FAILED.is_terminal is True

    def test_illegal_state_transition_raises_error(self):
        from piec.measurement.contracts import IllegalStateTransitionError
        meas = FakeMeasurement()
        with pytest.raises(IllegalStateTransitionError):
            meas._coordinator.transition_to(RunState.COMPLETED)

    def test_reservation_tokens_and_stale_detection(self):
        from piec.measurement.contracts import (
            ConcurrentRunError,
            DuplicateExecutionError,
            ReservationToken,
            StaleTokenError,
        )
        meas = FakeMeasurement()
        token1 = meas._reserve()
        assert token1.generation == 1

        # Concurrent reservation fails
        with pytest.raises(ConcurrentRunError):
            meas._reserve()

        # Stale token fails
        stale_token = ReservationToken(run_id="stale_uuid", generation=999)
        with pytest.raises(StaleTokenError):
            meas.run_experiment(token=stale_token)

        # Valid token succeeds
        meas.run_experiment(token=token1)
        assert meas.run_state == RunState.COMPLETED

        # Reusing the consumed token fails
        with pytest.raises(DuplicateExecutionError):
            meas.run_experiment(token=token1)


# ============================================================================
# 8. Ownership Protection: Rejected Caller Does Not Safe Active Owner
# ============================================================================

class TestOwnershipProtection:
    """Rejected execution attempts must have no side effects on the active owner."""

    @pytest.mark.parametrize("attempt", ["duplicate", "stale", "concurrent", "stopped_stale"])
    def test_rejected_caller_does_not_safe_or_clear_active_owner(self, attempt):
        import threading
        from piec.measurement.contracts import (
            ConcurrentRunError,
            DuplicateExecutionError,
            ReservationToken,
            StaleTokenError,
        )
        from piec.measurement.runner import MeasurementRunner

        entered, release = threading.Event(), threading.Event()
        shutdown_threads = []

        class ProtectedMeasurement(BaseMeasurement):
            def _capture_data(self, request, on_update=None):
                self._raw_data = pd.DataFrame({"v": [42.0]})
                entered.set()
                assert release.wait(3)
                return self._raw_data

            def _safe_shutdown(self):
                shutdown_threads.append(threading.get_ident())
                return super()._safe_shutdown()

        meas = ProtectedMeasurement()
        runner = MeasurementRunner(meas)
        token = runner.start(save=False)
        try:
            assert entered.wait(2)
            owner = meas._active_owner_thread_id
            if attempt == "stopped_stale":
                runner.request_stop()
            state = meas.run_state
            kwargs = {"save": False}
            if attempt == "duplicate":
                kwargs["token"] = token
                error = DuplicateExecutionError
            elif attempt in ("stale", "stopped_stale"):
                kwargs["token"] = ReservationToken(run_id="stale", generation=0)
                error = StaleTokenError
            else:
                error = ConcurrentRunError
            with pytest.raises(error):
                meas.run_experiment(**kwargs)
            assert shutdown_threads == []
            assert meas._active_owner_thread_id == owner
            assert meas.run_state == state
            assert meas.raw_data["v"].tolist() == [42.0]
        finally:
            release.set()
            assert runner.join(3)
        assert runner.last_error is None
        assert shutdown_threads == [owner]
        assert len(meas.run_records) == 1


# ============================================================================
# 9. MeasurementSession & Standalone Scopes
# ============================================================================

class TestMeasurementSessions:
    """Verify piecewise execution sessions and standalone scopes."""

    def test_session_lifecycle_and_single_capture(self):
        from piec.measurement.base import MeasurementSession
        meas = FakeMeasurement()

        with meas.session(save=False) as sess:
            assert isinstance(sess, MeasurementSession)
            assert meas.run_state in (RunState.STARTING, RunState.CONFIGURING)
            df = sess.capture_data()
            assert len(df) == 3
            # Second capture in same session is rejected
            with pytest.raises(RuntimeError, match="at most one capture"):
                sess.capture_data()

        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE

    def test_standalone_scopes(self):
        meas = FakeMeasurement()
        meas.configure_instruments()
        assert meas.run_state == RunState.COMPLETED
        df = meas.capture_data()
        assert len(df) == 3
        assert meas.run_state == RunState.COMPLETED

    @pytest.mark.parametrize("phase", ["configure", "capture", "block", None])
    @pytest.mark.parametrize("shutdown_fails", [False, True])
    def test_session_errors_and_shutdown_boundary(self, phase, shutdown_fails):
        meas = FakeMeasurement()
        primary = ValueError("primary session failure") if phase else None
        if phase == "configure":
            meas.config_error = primary
        elif phase == "capture":
            meas.capture_error = primary
        if shutdown_fails:
            meas.safing_error = OSError("shutdown failure")

        def execute():
            with meas.session(save=False) as session:
                session.configure_instruments()
                if phase == "block":
                    raise primary
                session.capture_data()

        if primary is not None:
            with pytest.raises(ValueError) as error:
                execute()
            assert error.value is primary
            assert meas.last_run_record.primary_error_message == str(primary)
        elif shutdown_fails:
            with pytest.raises(HardwareSafetyError, match="Hardware safety could not be verified"):
                execute()
        else:
            execute()
        assert [name for name, _ in meas.call_log].count("safing") == 1
        assert meas.safety_status == (SafetyStatus.UNSAFE if shutdown_fails else SafetyStatus.SAFE)
        assert meas.run_state == (RunState.FAILED if primary or shutdown_fails else RunState.COMPLETED)
        if primary and shutdown_fails:
            assert any("shutdown failure" in error for error in meas.last_run_record.secondary_errors)
        assert meas._active_session is None
        assert meas._active_owner_thread_id is None

    @pytest.mark.parametrize("operation", ["configure", "capture", "session", "shutdown"])
    def test_session_rejects_non_owner_without_hardware_calls(self, operation):
        import threading
        from piec.measurement.contracts import ConcurrentRunError
        meas = FakeMeasurement()
        errors = []

        def other_thread():
            try:
                if operation == "session":
                    with meas.session():
                        pass
                else:
                    method = {"configure": meas.configure_instruments,
                              "capture": meas.capture_data, "shutdown": meas.safe_shutdown}[operation]
                    method()
            except BaseException as error:
                errors.append(error)

        with meas.session():
            worker = threading.Thread(target=other_thread)
            worker.start()
            worker.join(timeout=2.)
            assert not worker.is_alive()
            assert len(errors) == 1
            assert isinstance(errors[0], RuntimeError if operation == "shutdown" else ConcurrentRunError)
            assert meas.call_log == []
            assert meas._active_owner_thread_id == threading.get_ident()
            if operation == "shutdown":
                assert meas._coordinator.is_stop_requested

    @pytest.mark.parametrize("nested", ["session", "run"])
    def test_session_rejects_nested_execution_without_io(self, nested):
        meas = FakeMeasurement()
        with meas.session():
            owner = meas._active_owner_thread_id
            with pytest.raises(RuntimeError):
                if nested == "session":
                    with meas.session():
                        pass
                else:
                    meas.run_experiment(save=False)
            assert meas.call_log == []
            assert meas._active_owner_thread_id == owner

    @pytest.mark.parametrize("operation", ["configure_instruments", "capture_data", "safe_shutdown"])
    def test_standalone_failure_reports_unsafe_and_releases_owner(self, operation):
        meas = FakeMeasurement()
        meas.safing_error = OSError("relay failed")
        with pytest.raises(HardwareSafetyError):
            getattr(meas, operation)()
        assert meas.safety_status == SafetyStatus.UNSAFE
        assert [name for name, _ in meas.call_log].count("safing") == 1
        assert meas._active_owner_thread_id is None


# ============================================================================
# 10. Multi-Action Shutdown Guarantee
# ============================================================================

class TestMultiActionShutdownGuarantee:
    """Verify all actions attempted via ShutdownAttemptRecorder even when earlier fails."""

    def test_all_shutdown_actions_attempted(self):
        from piec.measurement.contracts import ShutdownAttemptRecorder

        actions_called = []

        def action1():
            actions_called.append("a1")
            raise RuntimeError("a1 failure")

        def action2():
            actions_called.append("a2")

        recorder = ShutdownAttemptRecorder()
        recorder.record_action("zero_output", action1)
        recorder.record_action("open_relay", action2)

        assert actions_called == ["a1", "a2"]
        report = recorder.build_report()
        assert report.status == SafetyStatus.UNSAFE
        assert len(report.actions) == 2
        assert report.actions[0].succeeded is False
        assert report.actions[1].succeeded is True
