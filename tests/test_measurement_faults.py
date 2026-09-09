"""
Tests for Checkpoint 9c: Fault handling hardening.

Verifies Section 5.1, 5.2, 5.3, and Section 4.4/4.6 outcome matrix of
MEASUREMENT_STANDARDIZATION_PLAN.md:
- Multi-action shutdown: all actions attempted via ShutdownAttemptRecorder even when earlier actions fail;
- Error precedence: primary error (configuration, acquisition, callback, analysis, save) preserved;
- Secondary cleanup and persistence failures recorded without masking primary error;
- KeyboardInterrupt / SystemExit deferral during configuration, acquisition, and cleanup;
- Cleanup-only KeyboardInterrupt/SystemExit re-raised unchanged after remaining actions finish;
- Cleanup-only ordinary failure raises HardwareSafetyError with full report;
- Cooperative abort with required partial save failure transitions to FAILED and raises persistence error;
- Callback failure treated as acquisition failure;
- Event reporting failures never mask scientific or safety errors;
- Session and standalone scopes enforce identical fault handling and error precedence.
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union
import numpy as np
import pandas as pd
import pytest

from piec.measurement import (
    BaseMeasurement,
    HardwareSafetyError,
    MeasurementSession,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAction,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
    TerminalEvent,
)


# ============================================================================
# Test Fixtures & Mock Implementations
# ============================================================================

class FaultyMeasurement(BaseMeasurement):
    """Configurable measurement fixture for fault injection."""

    def __init__(self) -> None:
        super().__init__()
        self.config_exc: Optional[BaseException] = None
        self.capture_exc: Optional[BaseException] = None
        self.safing_exc: Optional[BaseException] = None
        self.analysis_exc: Optional[BaseException] = None
        self.publish_exc: Optional[BaseException] = None

        self.config_called = False
        self.capture_called = False
        self.safing_actions_executed: List[str] = []
        self.analysis_called = False
        self.publish_called = False

        # Ordered shutdown action callbacks
        self.shutdown_actions: Optional[
            List[Tuple[str, Callable[[], Any], Optional[Callable[[], bool]]]]
        ] = None

    def _configure_instruments(self, request: RunRequest) -> None:
        self.config_called = True
        if self.config_exc is not None:
            raise self.config_exc

    def _capture_data(
        self, request: RunRequest, on_update: Optional[Callable[[Any], None]]
    ) -> pd.DataFrame:
        self.capture_called = True
        # Stage intermediate raw data rows
        self._raw_data = pd.DataFrame({"step": [1, 2], "value": [10.0, 20.0]})
        if on_update is not None:
            # Trigger callback which may raise
            on_update(1)
        if self.capture_exc is not None:
            raise self.capture_exc
        return pd.DataFrame({"step": [1, 2, 3], "value": [10.0, 20.0, 30.0]})

    def _safe_shutdown(self) -> Any:
        if self.shutdown_actions is not None:
            # Return sequence of action tuples for attempt recorder
            return self.shutdown_actions

        # Default action execution
        self.safing_actions_executed.append("default_action")
        if self.safing_exc is not None:
            raise self.safing_exc
        return SafetyReport(
            status=SafetyStatus.SAFE, summary="Clean mock shutdown"
        )

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        self.analysis_called = True
        if self.analysis_exc is not None:
            raise self.analysis_exc
        df = raw_data.copy()
        df["analyzed"] = df["value"] * 2.0
        return df

    def _publish_data(
        self, data: pd.DataFrame, request: RunRequest, is_partial: bool = False
    ) -> Optional[str]:
        self.publish_called = True
        if self.publish_exc is not None:
            raise self.publish_exc
        suffix = ".partial.csv" if is_partial else ".csv"
        return f"{self._coordinator.active_token.run_id}{suffix}"


# ============================================================================
# 1. ShutdownAttemptRecorder & Multi-Action Shutdown (Section 5.1 & 5.3)
# ============================================================================

class TestShutdownAttemptRecorder:
    def test_recorder_executes_all_actions_despite_failure(self):
        """All shutdown actions must be attempted even when an earlier action fails."""
        recorder = ShutdownAttemptRecorder()
        executed: List[str] = []

        def action1():
            executed.append("ramp_down")
            raise RuntimeError("Ramp down DAC communication failure")

        def action2():
            executed.append("disable_output")

        def action3():
            executed.append("stop_motor")

        ok1 = recorder.record_action("ramp_down", action1)
        ok2 = recorder.record_action("disable_output", action2, readback_fn=lambda: True)
        ok3 = recorder.record_action("stop_motor", action3)

        assert not ok1
        assert ok2
        assert ok3
        assert executed == ["ramp_down", "disable_output", "stop_motor"]

        report = recorder.build_report()
        assert report.status == SafetyStatus.UNSAFE
        assert len(report.actions) == 3
        assert report.actions[0].succeeded is False
        assert "Ramp down DAC" in report.actions[0].error
        assert report.actions[1].succeeded is True
        assert report.actions[1].readback_verified is True
        assert report.actions[2].succeeded is True
        assert report.readback_verified is False  # Because not all succeeded
        assert "ramp_down: Ramp down DAC" in report.error

    def test_recorder_all_succeeded_with_readback(self):
        """Report reflects readback verification when all actions succeed and read back."""
        recorder = ShutdownAttemptRecorder()
        recorder.record_action("zero_field", lambda: None, readback_fn=lambda: True)
        recorder.record_action("disable_source", lambda: None, readback_fn=lambda: True)

        report = recorder.build_report()
        assert report.status == SafetyStatus.SAFE
        assert report.readback_verified is True
        assert len(report.actions) == 2

    def test_recorder_catches_keyboard_interrupt_and_continues(self):
        """Recorder catches KeyboardInterrupt to ensure remaining actions run, tracking interrupt."""
        recorder = ShutdownAttemptRecorder()
        executed: List[str] = []

        def action1():
            executed.append("action1")
            raise KeyboardInterrupt("Safing interrupted")

        def action2():
            executed.append("action2")

        recorder.record_action("action1", action1)
        recorder.record_action("action2", action2)

        assert executed == ["action1", "action2"]
        assert isinstance(recorder.interrupt_exc, KeyboardInterrupt)
        report = recorder.build_report()
        assert report.status == SafetyStatus.UNSAFE


class TestMeasurementMultiActionSafing:
    def test_measurement_attempts_all_actions_through_engine(self):
        """Measurement engine attempts all shutdown actions and records full report."""
        meas = FaultyMeasurement()
        executed = []

        meas.shutdown_actions = [
            ("ramp_down", lambda: (_ for _ in ()).throw(RuntimeError("ramp fault")), None),
            ("disable_output", lambda: executed.append("output_disabled"), lambda: True),
            ("halt_motor", lambda: executed.append("motor_halted"), None),
        ]

        with pytest.raises(HardwareSafetyError) as exc_info:
            meas.run_experiment(save=False)

        assert exc_info.value.safety_report is not None
        report = exc_info.value.safety_report
        assert report.status == SafetyStatus.UNSAFE
        assert len(report.actions) == 3
        assert executed == ["output_disabled", "motor_halted"]
        assert meas.run_state == RunState.FAILED


# ============================================================================
# 2. Error Precedence & Primary Faults (Section 5.3 Rule 1 & 2)
# ============================================================================

class TestPrimaryFaultHandling:
    def test_configuration_fault_safes_and_reraises_with_original_traceback(self):
        """Configuration error remains primary, safing is executed, original traceback preserved."""
        meas = FaultyMeasurement()
        meas.config_exc = ValueError("Invalid hardware configuration")

        with pytest.raises(ValueError) as exc_info:
            meas.run_experiment(save=False)

        assert str(exc_info.value) == "Invalid hardware configuration"
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "CONFIGURING"
        assert meas.last_run_record.primary_error_type == "ValueError"

    def test_acquisition_fault_safes_and_reraises(self):
        """Acquisition error remains primary, safing is executed, partial data saved if requested."""
        meas = FaultyMeasurement()
        meas.capture_exc = RuntimeError("Buffer overrun")

        with pytest.raises(RuntimeError) as exc_info:
            meas.run_experiment(save=False)

        assert str(exc_info.value) == "Buffer overrun"
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "RUNNING"

    def test_callback_fault_treated_as_acquisition_failure(self):
        """Callback failure is an acquisition failure (Section 4.4 step 5)."""
        meas = FaultyMeasurement()

        def crashing_callback(data):
            raise TypeError("Display widget callback failed")

        with pytest.raises(TypeError) as exc_info:
            meas.run_experiment(on_update=crashing_callback, save=False)

        assert str(exc_info.value) == "Display widget callback failed"
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "RUNNING"
        assert meas.last_run_record.primary_error_type == "TypeError"

    def test_primary_acquisition_error_takes_precedence_over_cleanup_failure(self):
        """Primary acquisition error is re-raised; secondary cleanup failure recorded in secondary_errors."""
        meas = FaultyMeasurement()
        meas.capture_exc = ValueError("Sensor reading out of range")
        meas.safing_exc = RuntimeError("Output relay stuck closed")

        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        with pytest.raises(ValueError) as exc_info:
            meas.run_experiment(save=False)

        assert str(exc_info.value) == "Sensor reading out of range"
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.UNSAFE
        assert meas.last_run_record.primary_error_type == "ValueError"
        assert len(meas.last_run_record.secondary_errors) > 0
        assert any("Output relay stuck" in err for err in meas.last_run_record.secondary_errors)

        assert len(events) == 1
        assert events[0].primary_error_type == "ValueError"
        assert any("Output relay stuck" in err for err in events[0].secondary_errors)

    def test_analysis_fault_occurs_after_safing(self):
        """Analysis failure occurs after safing succeeded; analysis error is re-raised."""
        meas = FaultyMeasurement()
        meas.analysis_exc = ZeroDivisionError("Cannot normalize empty cycle")

        with pytest.raises(ZeroDivisionError) as exc_info:
            meas.run_experiment(save=False)

        assert str(exc_info.value) == "Cannot normalize empty cycle"
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.last_run_record.primary_error_phase == "ANALYZING"

    def test_publication_fault_reraised(self):
        """Publication error after analysis transitions to FAILED and is re-raised."""
        meas = FaultyMeasurement()
        meas.publish_exc = OSError("Disk write failed: permission denied")

        with pytest.raises(OSError) as exc_info:
            meas.run_experiment(save=True)

        assert "Disk write failed" in str(exc_info.value)
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "SAVING"


# ============================================================================
# 3. Interrupt Handling (KeyboardInterrupt / SystemExit) (Section 5.3)
# ============================================================================

class TestInterruptHandling:
    def test_keyboard_interrupt_during_configuration_deferred_until_safing_finishes(self):
        """KeyboardInterrupt during configuration is deferred until safing finishes, then re-raised unchanged."""
        meas = FaultyMeasurement()
        meas.config_exc = KeyboardInterrupt("User pressed Ctrl+C during configure")

        with pytest.raises(KeyboardInterrupt) as exc_info:
            meas.run_experiment(save=False)

        assert "User pressed Ctrl+C" in str(exc_info.value)
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.last_run_record.primary_error_type == "KeyboardInterrupt"
        assert meas.last_run_record.primary_error_phase == "CONFIGURING"

    def test_keyboard_interrupt_during_acquisition_deferred_until_safing_finishes(self):
        """KeyboardInterrupt during capture is deferred until safing finishes, then re-raised unchanged."""
        meas = FaultyMeasurement()
        meas.capture_exc = KeyboardInterrupt("Ctrl+C during acquisition")

        with pytest.raises(KeyboardInterrupt) as exc_info:
            meas.run_experiment(save=False)

        assert "Ctrl+C during acquisition" in str(exc_info.value)
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.last_run_record.primary_error_type == "KeyboardInterrupt"
        assert meas.last_run_record.primary_error_phase == "RUNNING"

    def test_keyboard_interrupt_during_safing_after_primary_error(self):
        """
        If KeyboardInterrupt occurs during safing after an earlier primary error,
        it is recorded as a secondary cleanup failure and the earlier primary keeps precedence.
        """
        meas = FaultyMeasurement()
        meas.capture_exc = ValueError("Acquisition error")
        meas.safing_exc = KeyboardInterrupt("Ctrl+C during safing")

        with pytest.raises(ValueError) as exc_info:
            meas.run_experiment(save=False)

        assert str(exc_info.value) == "Acquisition error"
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_type == "ValueError"
        assert any("KeyboardInterrupt" in err or "Ctrl+C" in err for err in meas.last_run_record.secondary_errors)

    def test_cleanup_only_keyboard_interrupt_reraised_unchanged(self):
        """
        A cleanup-only KeyboardInterrupt or SystemExit is instead re-raised unchanged
        after the remaining actions are attempted (Section 5.3 Rule 3).
        """
        meas = FaultyMeasurement()
        executed = []

        meas.shutdown_actions = [
            ("action1", lambda: (_ for _ in ()).throw(KeyboardInterrupt("Ctrl+C in shutdown")), None),
            ("action2", lambda: executed.append("action2_done"), None),
        ]

        with pytest.raises(KeyboardInterrupt) as exc_info:
            meas.run_experiment(save=False)

        assert "Ctrl+C in shutdown" in str(exc_info.value)
        assert executed == ["action2_done"]  # Remaining action was still attempted
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.UNSAFE
        assert meas.last_run_record.primary_error_type == "KeyboardInterrupt"
        assert meas.last_run_record.primary_error_phase == "SAFING"

    def test_system_exit_during_safing_without_prior_error(self):
        """SystemExit during safing without prior error is re-raised unchanged after safing finishes."""
        meas = FaultyMeasurement()
        meas.safing_exc = SystemExit(2)

        with pytest.raises(SystemExit) as exc_info:
            meas.run_experiment(save=False)

        assert exc_info.value.code == 2
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_type == "SystemExit"


# ============================================================================
# 4. Partial Persistence Faults & Matrix Compliance (Section 4.6 & 5.3 Rule 4)
# ============================================================================

class TestPartialPersistenceFaults:
    def test_cooperative_abort_with_partial_save_failure_transitions_to_failed(self):
        """
        If a cooperative abort is otherwise clean but a required partial save fails,
        the run becomes FAILED and raises the persistence error (Section 5.3 Rule 4).
        """
        meas = FaultyMeasurement()
        meas.publish_exc = OSError("Disk quota exceeded saving partial")

        def stop_on_update(data):
            meas.request_stop()

        with pytest.raises(OSError) as exc_info:
            meas.run_experiment(on_update=stop_on_update, save=True, save_partial=True)

        assert "Disk quota exceeded" in str(exc_info.value)
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_phase == "SAVING"
        assert meas.last_run_record.primary_error_type == "OSError"

    def test_failure_with_required_partial_save_failure_preserves_primary_error(self):
        """
        When a run fails and required partial save also fails, the primary error is re-raised
        and the partial save failure is recorded in secondary_errors.
        """
        meas = FaultyMeasurement()
        meas.capture_exc = ValueError("Hardware read error")
        meas.publish_exc = OSError("Disk full saving partial on failure")

        with pytest.raises(ValueError) as exc_info:
            meas.run_experiment(save=True, save_partial=True)

        assert str(exc_info.value) == "Hardware read error"
        assert meas.run_state == RunState.FAILED
        assert meas.last_run_record.primary_error_type == "ValueError"
        assert any("Partial save error" in err for err in meas.last_run_record.secondary_errors)


# ============================================================================
# 5. Reporting Resilience (Section 5.3 Rule 5)
# ============================================================================

class TestReportingResilience:
    def test_broken_event_listener_does_not_mask_primary_error(self):
        """A broken event listener callback never replaces an earlier scientific or safety error."""
        meas = FaultyMeasurement()
        meas.capture_exc = ValueError("Scientific hardware fault")

        def broken_listener(event):
            raise RuntimeError("UI listener crashed")

        meas.add_event_listener(broken_listener)

        with pytest.raises(ValueError) as exc_info:
            meas.run_experiment(save=False)

        assert str(exc_info.value) == "Scientific hardware fault"
        assert meas.run_state == RunState.FAILED


# ============================================================================
# 6. Sessions & Standalone Scopes Fault Hardening (Section 4.5 & 5.3)
# ============================================================================

class TestSessionFaultHardening:
    def test_session_exception_in_with_block_safes_and_propagates(self):
        """Exception raised inside session with-block executes safing and propagates unchanged."""
        meas = FaultyMeasurement()

        with pytest.raises(KeyError) as exc_info:
            with meas.session(save=False) as sess:
                sess.capture_data()
                raise KeyError("User computation failed")

        assert "User computation failed" in str(exc_info.value)
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.last_run_record.primary_error_type == "KeyError"

    def test_session_safing_failure_without_prior_error_raises_hardware_safety_error(self):
        """Safing failure upon session exit raises HardwareSafetyError."""
        meas = FaultyMeasurement()
        meas.safing_exc = RuntimeError("Relay failed to open on session exit")

        with pytest.raises(HardwareSafetyError) as exc_info:
            with meas.session(save=False) as sess:
                sess.configure_instruments()

        assert "Relay failed to open" in str(exc_info.value)
        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.UNSAFE

    def test_session_analysis_failure_on_exit(self):
        """Analysis failure on clean session exit after capture transitions to FAILED and raises."""
        meas = FaultyMeasurement()
        meas.analysis_exc = ValueError("Analysis calibration error")

        with pytest.raises(ValueError) as exc_info:
            with meas.session(save=False) as sess:
                sess.capture_data()

        assert str(exc_info.value) == "Analysis calibration error"
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED

    def test_session_partial_save_failure_on_abort_raises_persistence_error(self):
        """Session partial save failure on cooperative abort transitions to FAILED and raises."""
        meas = FaultyMeasurement()
        meas.publish_exc = OSError("Disk full on session partial save")

        with pytest.raises(OSError) as exc_info:
            with meas.session(save=True, save_partial=True) as sess:
                sess.capture_data()
                sess.request_stop()

        assert "Disk full" in str(exc_info.value)
        assert meas.run_state == RunState.FAILED


class TestStandaloneScopeFaultHardening:
    def test_standalone_configure_fault_handling(self):
        """Standalone configure_instruments error re-raised, safing attempted, state FAILED."""
        meas = FaultyMeasurement()
        meas.config_exc = ValueError("Config parameter rejected")

        with pytest.raises(ValueError) as exc_info:
            meas.configure_instruments()

        assert str(exc_info.value) == "Config parameter rejected"
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED

    def test_standalone_capture_callback_fault(self):
        """Standalone capture_data callback error treated as acquisition failure and re-raised."""
        meas = FaultyMeasurement()

        def bad_cb(val):
            raise RuntimeError("Callback fault in standalone capture")

        with pytest.raises(RuntimeError) as exc_info:
            meas.capture_data(on_update=bad_cb)

        assert "Callback fault in standalone capture" in str(exc_info.value)
        assert meas.safing_actions_executed == ["default_action"]
        assert meas.run_state == RunState.FAILED

    def test_idle_safe_shutdown_keyboard_interrupt_reraised(self):
        """Idle safe_shutdown re-raises KeyboardInterrupt after remaining actions finish."""
        meas = FaultyMeasurement()
        executed = []
        meas.shutdown_actions = [
            ("action1", lambda: (_ for _ in ()).throw(KeyboardInterrupt("Stop")), None),
            ("action2", lambda: executed.append("action2_done"), None),
        ]

        with pytest.raises(KeyboardInterrupt):
            meas.safe_shutdown()

        assert executed == ["action2_done"]
        assert meas.safety_status == SafetyStatus.UNSAFE
