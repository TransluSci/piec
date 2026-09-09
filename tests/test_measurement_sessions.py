"""
Contract and behavioral tests for piecewise execution sessions and standalone scopes.

Fulfills Checkpoint 9b of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Session scope (with measurement.session(...) as sess):
  - Synchronous reservation bound to owner thread;
  - Single shutdown boundary on exit;
  - Single capture operation per session (repeated capture raises RuntimeError);
  - Clean exit after capture safes then analyzes; save only if save=True;
  - Configuration-only session skips analysis and saving;
  - Rejection of nested sessions, run_experiment() in session, and cross-thread hardware calls;
- Standalone scopes (configure_instruments(), capture_data()):
  - Transient reservations, safing on exit, no save, single terminal event;
  - Prerequisite validation and failure handling;
- Standalone safe_shutdown():
  - Idle safing under command lease updating safety status;
  - Non-owner deferral during active run (latches Stop, raises RuntimeError, zero hardware write);
  - Owner safing during active session/run;
- Universal no-save semantics across all families.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, List, Mapping, Optional, Sequence, Union
import numpy as np
import pandas as pd
import pytest

from piec.measurement.base import BaseMeasurement, MeasurementSession
from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    IllegalStateTransitionError,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAction,
    SafetyReport,
    SafetyStatus,
    TerminalEvent,
)


class DummyMeasurement(BaseMeasurement):
    """Concrete subclass for testing session and scope contracts."""

    def __init__(self) -> None:
        super().__init__()
        self.config_calls: List[RunRequest] = []
        self.capture_calls: List[RunRequest] = []
        self.safing_calls: List[str] = []
        self.analysis_calls: List[pd.DataFrame] = []
        self.publish_calls: List[Tuple[pd.DataFrame, bool]] = []

        self.config_error: Optional[BaseException] = None
        self.capture_error: Optional[BaseException] = None
        self.safing_error: Optional[BaseException] = None
        self.analysis_error: Optional[BaseException] = None
        self.publish_error: Optional[BaseException] = None

        self.custom_options_allowed = {"step_delay", "channel"}

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        super()._validate_options(options)
        if options is not None:
            for k in options:
                if k not in self.custom_options_allowed:
                    raise ValueError(f"Unknown option '{k}'")

    def _configure_instruments(self, request: RunRequest) -> None:
        self.config_calls.append(request)
        if self.config_error is not None:
            raise self.config_error

    def _capture_data(
        self, request: RunRequest, on_update: Optional[Callable[[Any], None]]
    ) -> pd.DataFrame:
        self.capture_calls.append(request)
        if self.capture_error is not None:
            raise self.capture_error
        df = pd.DataFrame({"time": [0.0, 0.1, 0.2], "voltage": [1.0, 2.0, 3.0]})
        if on_update:
            on_update(df)
        return df

    def _safe_shutdown(self) -> Union[SafetyReport, Sequence[SafetyAction]]:
        self.safing_calls.append("safe_shutdown")
        if self.safing_error is not None:
            raise self.safing_error
        return SafetyReport(
            status=SafetyStatus.SAFE, summary="Dummy clean safe shutdown"
        )

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        self.analysis_calls.append(raw_data)
        if self.analysis_error is not None:
            raise self.analysis_error
        analyzed = raw_data.copy()
        analyzed["analyzed_current"] = analyzed["voltage"] / 1000.0
        return analyzed

    def _publish_data(
        self, data: pd.DataFrame, request: RunRequest, is_partial: bool = False
    ) -> Optional[str]:
        self.publish_calls.append((data.copy(), is_partial))
        if self.publish_error is not None:
            raise self.publish_error
        suffix = ".partial.csv" if is_partial else ".csv"
        return f"published_{self._coordinator.active_token.run_id}{suffix}"


# ============================================================================
# 1. Session Lifecycle Tests
# ============================================================================

class TestSessionLifecycle:
    """Tests covering session enter, execution, clean exit, analysis, and save policy."""

    def test_clean_session_workflow(self):
        """Clean session: configure -> capture -> exit safes -> analyzes -> completed without save."""
        meas = DummyMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        with meas.session() as sess:
            assert isinstance(sess, MeasurementSession)
            assert sess.run_state == RunState.STARTING
            assert sess.token is not None
            gen = sess.token.generation

            # Configure
            sess.configure_instruments()
            assert sess.run_state == RunState.CONFIGURING
            assert len(meas.config_calls) == 1

            # Capture
            raw = sess.capture_data()
            assert len(raw) == 3
            assert sess.run_state == RunState.RUNNING
            assert len(meas.capture_calls) == 1
            assert len(meas.safing_calls) == 0  # Not safed yet inside session!

        # After session clean exit:
        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        assert len(meas.safing_calls) == 1  # Safed upon exit
        assert len(meas.analysis_calls) == 1  # Analyzed upon exit
        assert len(meas.publish_calls) == 0  # Default save=False -> no save
        assert meas.filename is None
        assert "analyzed_current" in meas.data.columns
        assert len(meas.raw_data) == 3

        # Exact single RunRecord and TerminalEvent
        assert len(meas.run_records) == 1
        record = meas.last_run_record
        assert record.generation == gen
        assert record.state == RunState.COMPLETED
        assert record.safety.status == SafetyStatus.SAFE
        assert record.save_requested is False

        assert len(events) == 1
        assert events[0].state == RunState.COMPLETED
        assert events[0].safety.status == SafetyStatus.SAFE

    def test_session_with_save_true(self):
        """Session with save=True publishes completed data CSV on clean exit."""
        meas = DummyMeasurement()

        with meas.session(save=True) as sess:
            sess.configure_instruments()
            sess.capture_data()

        assert meas.run_state == RunState.COMPLETED
        assert len(meas.publish_calls) == 1
        assert meas.filename is not None
        assert meas.filename.startswith("published_")
        assert meas.last_run_record.save_requested is True

    def test_configuration_only_session(self):
        """Configuration-only session safes on exit, skips analysis and saving, transitions to COMPLETED."""
        meas = DummyMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        with meas.session() as sess:
            sess.configure_instruments()
            assert sess.run_state == RunState.CONFIGURING

        # Exit without capture
        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        assert len(meas.safing_calls) == 1
        assert len(meas.analysis_calls) == 0  # Analysis skipped
        assert len(meas.publish_calls) == 0  # Saving skipped
        assert meas.filename is None

        assert len(events) == 1
        assert events[0].state == RunState.COMPLETED

    def test_direct_calls_on_measurement_within_session(self):
        """Calling measurement.configure_instruments() and capture_data() directly recognizes session."""
        meas = DummyMeasurement()

        with meas.session() as sess:
            token = sess.token
            meas.configure_instruments()
            assert meas.run_state == RunState.CONFIGURING

            raw = meas.capture_data()
            assert len(raw) == 3
            assert meas.run_state == RunState.RUNNING

        assert meas.run_state == RunState.COMPLETED
        assert meas.last_run_record.generation == token.generation

    def test_capture_without_prior_configure_passes_through_configuring(self):
        """Calling capture_data() without prior configure passes through CONFIGURING for prerequisite validation."""
        meas = DummyMeasurement()

        with meas.session() as sess:
            assert sess.run_state == RunState.STARTING
            raw = sess.capture_data()
            assert len(raw) == 3
            # Prerequisite validation ran configuration hook
            assert len(meas.config_calls) == 1

        assert meas.run_state == RunState.COMPLETED

    def test_session_stop_before_io(self):
        """Stop requested before any I/O in session aborts with safety NOT_NEEDED."""
        meas = DummyMeasurement()

        with meas.session() as sess:
            sess.request_stop()

        assert meas.run_state == RunState.ABORTED
        assert meas.safety_status == SafetyStatus.NOT_NEEDED
        assert len(meas.config_calls) == 0
        assert len(meas.capture_calls) == 0

    def test_session_stop_during_capture(self):
        """Stop requested during capture transitions to ABORTED and skips analysis."""
        meas = DummyMeasurement()

        def stop_on_update(df):
            meas.request_stop()

        with meas.session(save=True) as sess:
            sess.configure_instruments()
            sess.capture_data(on_update=stop_on_update)

        assert meas.run_state == RunState.ABORTED
        assert meas.safety_status == SafetyStatus.SAFE
        assert len(meas.analysis_calls) == 0  # Analysis skipped
        assert len(meas.publish_calls) == 1  # Partial save published
        assert meas.publish_calls[0][1] is True  # is_partial=True
        assert meas.partial_filename is not None


# ============================================================================
# 2. Session Rejections & Concurrency Invariants
# ============================================================================

class TestSessionRejectionsAndInvariants:
    """Tests verifying single-owner, non-nesting, and single-capture invariants."""

    def test_nested_session_rejected(self):
        """Nested measurement.session() raises ConcurrentRunError."""
        meas = DummyMeasurement()

        with meas.session():
            with pytest.raises(ConcurrentRunError, match="Cannot start session: another run or session is currently active"):
                with meas.session():
                    pass

    def test_run_experiment_inside_session_rejected(self):
        """Calling run_experiment() inside an active session raises ConcurrentRunError."""
        meas = DummyMeasurement()

        with meas.session():
            with pytest.raises(ConcurrentRunError, match="Cannot call run_experiment\\(\\) while a session is active"):
                meas.run_experiment()

    def test_multiple_captures_in_session_rejected(self):
        """Calling capture_data() more than once in the same session raises RuntimeError."""
        meas = DummyMeasurement()

        with meas.session() as sess:
            sess.capture_data()
            with pytest.raises(RuntimeError, match="A session supports at most one capture operation"):
                sess.capture_data()

    def test_cross_thread_hardware_call_rejected(self):
        """Worker thread calling hardware methods while session is active on main thread is rejected."""
        meas = DummyMeasurement()
        worker_error: Optional[BaseException] = None

        def worker_target():
            nonlocal worker_error
            try:
                meas.configure_instruments()
            except BaseException as e:
                worker_error = e

        with meas.session():
            t = threading.Thread(target=worker_target)
            t.start()
            t.join(timeout=2.0)

        assert worker_error is not None
        assert isinstance(worker_error, ConcurrentRunError)
        assert "Cross-thread hardware-bearing calls are rejected" in str(worker_error)

    def test_cross_thread_session_start_rejected(self):
        """Worker thread cannot start a session while main thread holds a session."""
        meas = DummyMeasurement()
        worker_error: Optional[BaseException] = None

        def worker_target():
            nonlocal worker_error
            try:
                with meas.session():
                    pass
            except BaseException as e:
                worker_error = e

        with meas.session():
            t = threading.Thread(target=worker_target)
            t.start()
            t.join(timeout=2.0)

        assert worker_error is not None
        assert isinstance(worker_error, ConcurrentRunError)


# ============================================================================
# 3. Session Fault Handling & Safing
# ============================================================================

class TestSessionFaultHandling:
    """Tests verifying safing guarantees and error precedence during session faults."""

    def test_exception_in_session_block_safes_and_reraises(self):
        """Exception in session block triggers safing, transitions to FAILED, and propagates."""
        meas = DummyMeasurement()

        with pytest.raises(ValueError, match="Block failure"):
            with meas.session() as sess:
                sess.configure_instruments()
                raise ValueError("Block failure")

        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.SAFE
        assert len(meas.safing_calls) == 1
        assert meas.last_run_record.primary_error_type == "ValueError"
        assert meas.last_run_record.primary_error_message == "Block failure"

    def test_safing_failure_in_session_raises_hardware_safety_error(self):
        """Safing failure on session exit raises HardwareSafetyError."""
        meas = DummyMeasurement()
        meas.safing_error = RuntimeError("Relay stuck open")

        with pytest.raises(HardwareSafetyError, match="Hardware safety could not be verified"):
            with meas.session() as sess:
                sess.configure_instruments()

        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.UNSAFE

    def test_primary_error_takes_precedence_over_safing_failure(self):
        """Primary error in block takes precedence over secondary safing failure."""
        meas = DummyMeasurement()
        meas.safing_error = RuntimeError("Relay stuck open")

        with pytest.raises(KeyError, match="primary_fault"):
            with meas.session() as sess:
                sess.configure_instruments()
                raise KeyError("primary_fault")

        assert meas.run_state == RunState.FAILED
        assert meas.safety_status == SafetyStatus.UNSAFE
        assert meas.last_run_record.primary_error_type == "KeyError"
        assert len(meas.last_run_record.secondary_errors) == 1
        assert "Shutdown error" in meas.last_run_record.secondary_errors[0]


# ============================================================================
# 4. Standalone Scopes Tests
# ============================================================================

class TestStandaloneScopes:
    """Tests verifying standalone configure_instruments() and capture_data() transient scopes."""

    def test_standalone_configure_instruments(self):
        """Standalone configure_instruments() reserves, configures, safes, and completes with no save."""
        meas = DummyMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        meas.configure_instruments()

        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        assert len(meas.config_calls) == 1
        assert len(meas.safing_calls) == 1
        assert len(meas.analysis_calls) == 0  # No analysis
        assert len(meas.publish_calls) == 0  # No save
        assert meas.filename is None

        assert len(meas.run_records) == 1
        assert meas.last_run_record.state == RunState.COMPLETED
        assert len(events) == 1
        assert events[0].state == RunState.COMPLETED

    def test_standalone_configure_instruments_failure(self):
        """Standalone configure failure attempts safing, records FAILED, and re-raises."""
        meas = DummyMeasurement()
        meas.config_error = ValueError("Bad hardware setup")

        with pytest.raises(ValueError, match="Bad hardware setup"):
            meas.configure_instruments()

        assert meas.run_state == RunState.FAILED
        assert len(meas.safing_calls) == 1
        assert meas.last_run_record.primary_error_type == "ValueError"

    def test_standalone_capture_data(self):
        """Standalone capture_data() passes through CONFIGURING, acquires, safes, and completes with no save."""
        meas = DummyMeasurement()
        events: List[TerminalEvent] = []
        meas.add_event_listener(events.append)

        raw = meas.capture_data()

        assert len(raw) == 3
        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        assert len(meas.config_calls) == 1  # Prerequisite validation
        assert len(meas.capture_calls) == 1
        assert len(meas.safing_calls) == 1  # Safes on exit
        assert len(meas.analysis_calls) == 0  # Standalone does not analyze
        assert len(meas.publish_calls) == 0  # Standalone does not save
        assert meas.filename is None

        assert len(meas.run_records) == 1
        assert len(events) == 1

    def test_standalone_capture_data_failure(self):
        """Standalone capture failure attempts safing, records FAILED, and re-raises."""
        meas = DummyMeasurement()
        meas.capture_error = RuntimeError("ADC timeout")

        with pytest.raises(RuntimeError, match="ADC timeout"):
            meas.capture_data()

        assert meas.run_state == RunState.FAILED
        assert len(meas.safing_calls) == 1
        assert meas.last_run_record.primary_error_type == "RuntimeError"

    def test_sequential_standalone_scopes_increment_generation(self):
        """Multiple standalone operations reserve distinct generations."""
        meas = DummyMeasurement()

        meas.configure_instruments()
        gen1 = meas.last_run_record.generation

        meas.capture_data()
        gen2 = meas.last_run_record.generation

        assert gen2 == gen1 + 1
        assert len(meas.run_records) == 2


# ============================================================================
# 5. Standalone Safe Shutdown Tests
# ============================================================================

class TestSafeShutdown:
    """Tests verifying idle safe_shutdown(), non-owner deferral, and command lease."""

    def test_idle_safe_shutdown_clean(self):
        """When idle, safe_shutdown() executes under lease and updates safety_status to SAFE."""
        meas = DummyMeasurement()
        assert meas.safety_status == SafetyStatus.UNKNOWN

        report = meas.safe_shutdown()

        assert isinstance(report, SafetyReport)
        assert report.status == SafetyStatus.SAFE
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.run_state == RunState.IDLE  # Idle lease does not transition RunState
        assert len(meas.safing_calls) == 1

    def test_idle_safe_shutdown_failure_raises_hardware_safety_error(self):
        """When idle safe_shutdown() fails, it updates safety_status to UNSAFE and raises HardwareSafetyError."""
        meas = DummyMeasurement()
        meas.safing_error = RuntimeError("Switch weld detected")

        with pytest.raises(HardwareSafetyError, match="Hardware safety could not be verified"):
            meas.safe_shutdown()

        assert meas.safety_status == SafetyStatus.UNSAFE

    def test_idle_safe_shutdown_blocks_concurrent_run_reservation(self):
        """While idle shutdown lease is active, concurrent reservation is rejected."""
        meas = DummyMeasurement()
        lease_entered = threading.Event()
        proceed = threading.Event()
        worker_error: Optional[BaseException] = None

        def shutdown_thread():
            with meas._idle_command_lease():
                lease_entered.set()
                proceed.wait(timeout=2.0)

        def run_thread():
            lease_entered.wait(timeout=2.0)
            nonlocal worker_error
            try:
                meas.run_experiment()
            except BaseException as e:
                worker_error = e

        t1 = threading.Thread(target=shutdown_thread)
        t2 = threading.Thread(target=run_thread)

        t1.start()
        t2.start()

        t2.join(timeout=2.0)
        proceed.set()
        t1.join(timeout=2.0)

        assert worker_error is not None
        assert isinstance(worker_error, ConcurrentRunError)
        assert "idle shutdown lease is active" in str(worker_error)

    def test_non_owner_safe_shutdown_during_active_run_latches_stop_and_raises(self):
        """Non-owner call to safe_shutdown() during active run latches Stop and raises RuntimeError."""
        meas = DummyMeasurement()
        capture_started = threading.Event()
        proceed_capture = threading.Event()
        non_owner_error: Optional[BaseException] = None

        def capture_hook(request, on_update):
            capture_started.set()
            proceed_capture.wait(timeout=2.0)
            return pd.DataFrame({"time": [0], "voltage": [0]})

        meas._capture_data = capture_hook

        def owner_run():
            try:
                meas.run_experiment()
            except Exception:
                pass

        def non_owner_safing():
            capture_started.wait(timeout=2.0)
            nonlocal non_owner_error
            try:
                meas.safe_shutdown()
            except BaseException as e:
                non_owner_error = e
            finally:
                proceed_capture.set()

        t_owner = threading.Thread(target=owner_run)
        t_non_owner = threading.Thread(target=non_owner_safing)

        t_owner.start()
        t_non_owner.start()

        t_non_owner.join(timeout=2.0)
        t_owner.join(timeout=2.0)

        assert non_owner_error is not None
        assert isinstance(non_owner_error, RuntimeError)
        assert "Shutdown deferred to execution owner" in str(non_owner_error)
        assert meas._coordinator.is_stop_requested is True

    def test_owner_safe_shutdown_during_active_session(self):
        """Owner thread calling safe_shutdown() during active session executes shutdown directly."""
        meas = DummyMeasurement()

        with meas.session() as sess:
            sess.configure_instruments()
            report = sess.safe_shutdown()
            assert report.status == SafetyStatus.SAFE
            assert len(meas.safing_calls) == 1

        # Session exit executes safing again (idempotent)
        assert len(meas.safing_calls) == 2


# ============================================================================
# 6. Snapshot Test
# ============================================================================

class TestSnapshot:
    """Tests verifying public snapshot() method."""

    def test_snapshot_structure(self):
        meas = DummyMeasurement()
        snap = meas.snapshot()
        assert "run_id" in snap
        assert "generation" in snap
        assert "state" in snap
        assert "safety" in snap
        assert snap["state"] == RunState.IDLE.value
        assert snap["safety"] == SafetyStatus.UNKNOWN.value
