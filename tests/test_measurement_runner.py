"""
Tests for Checkpoint 10b: MeasurementRunner.

Verifies:
- Synchronous reservation before worker launch (Section 4.2).
- Non-daemon worker thread execution (Section 3.2 & 6.3).
- Stop-before-start race closure (Section 4.2).
- Worker thread-start failure handling and clean FAILED finalization (Section 4.2).
- Cooperative stop and pause controls (Section 4.3).
- Close coordination preventing premature exit before worker death, terminal delivery,
  and confirmed hardware safety (Section 6.3).
- Unsafe hardware status blocking clean application close (Section 6.3).
- Display and control queue distribution through runner (Section 6.2).
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, List, Mapping, Optional
from unittest.mock import patch

import pandas as pd
import pytest

from piec.measurement import (
    BaseMeasurement,
    CloseCoordinationStatus,
    ConcurrentRunError,
    ControlQueue,
    DisplayQueue,
    HardwareSafetyError,
    MeasurementRunner,
    MeasurementSnapshot,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAlertEvent,
    SafetyReport,
    SafetyStatus,
    StateChangeEvent,
    TerminalEvent,
)


class DummyRunnerMeasurement(BaseMeasurement):
    """Concrete measurement instrumented for runner testing."""

    def __init__(
        self,
        delay_per_step: float = 0.01,
        steps: int = 5,
        fail_safing: bool = False,
        fail_acquisition: bool = False,
    ) -> None:
        super().__init__()
        self.delay_per_step = delay_per_step
        self.steps = steps
        self.fail_safing = fail_safing
        self.fail_acquisition = fail_acquisition
        self.configure_called = False
        self.capture_called = False
        self.safing_called = False

    def _configure_instruments(self, request: RunRequest) -> None:
        self.configure_called = True

    def _capture_data(
        self, request: RunRequest, on_update: Optional[Callable[[Any], None]] = None
    ) -> pd.DataFrame:
        self.capture_called = True
        if self.fail_acquisition:
            raise RuntimeError("Simulated acquisition hardware failure")

        rows = []
        for i in range(self.steps):
            if self._coordinator.is_stop_requested:
                break
            if self.delay_per_step > 0:
                time.sleep(self.delay_per_step)
            rows.append({"time": float(i), "voltage": float(i * 2)})
            df_curr = pd.DataFrame(rows)
            snap = self.publish_snapshot(
                views={"raw_window": df_curr},
                message=f"Acquired step {i + 1}",
                completed_steps=i + 1,
                total_steps=self.steps,
            )
            if on_update:
                on_update(snap)
        return pd.DataFrame(rows)

    def _safe_shutdown(self) -> SafetyReport:
        self.safing_called = True
        if self.fail_safing:
            return SafetyReport(
                status=SafetyStatus.UNSAFE,
                error="Simulated safing hardware failure",
                summary="Outputs could not be disabled",
            )
        return SafetyReport(status=SafetyStatus.SAFE, summary="Outputs safely disabled")


# ============================================================================
# 1. Synchronous Reservation & Worker Threading (Section 4.2 & 3.2)
# ============================================================================

class TestRunnerSynchronousReservation:
    """Verifies synchronous reservation before worker launch and non-daemon threading."""

    def test_synchronous_reservation_before_worker_launch(self):
        """Runner reserves synchronously on the caller thread before launching worker."""
        meas = DummyRunnerMeasurement(delay_per_step=0.05, steps=5)
        runner = MeasurementRunner(meas)

        assert runner.run_state == RunState.IDLE
        assert runner.active_token is None

        token = runner.start(save=False)

        # Immediately after start returns, state is active and token is set
        assert token is not None
        assert runner.active_token == token
        assert runner.run_state in {RunState.STARTING, RunState.CONFIGURING, RunState.RUNNING}
        assert runner.is_active
        assert runner.is_worker_alive

        # Attempting a second start while active raises ConcurrentRunError synchronously
        with pytest.raises(ConcurrentRunError):
            runner.start(save=False)

        # Wait for worker to finish
        assert runner.join(timeout=2.0)
        assert runner.run_state == RunState.COMPLETED
        assert not runner.is_worker_alive

    def test_worker_thread_is_non_daemon(self):
        """Worker thread must be non-daemon to prevent abrupt Python shutdown (Section 3.2 & 6.3)."""
        meas = DummyRunnerMeasurement(delay_per_step=0.05, steps=2)
        runner = MeasurementRunner(meas)

        token = runner.start(save=False)
        worker = runner._worker_thread
        assert worker is not None
        assert not worker.daemon, "Worker thread MUST be non-daemon (daemon=False)"
        assert f"MeasurementWorker-{token.run_id[:8]}" in worker.name

        assert runner.join(timeout=2.0)

    def test_idle_lease_blocks_runner_start(self):
        """Runner.start() rejects synchronously if an idle command lease is held."""
        meas = DummyRunnerMeasurement()
        runner = MeasurementRunner(meas)

        with meas._idle_command_lease():
            with pytest.raises(ConcurrentRunError):
                runner.start(save=False)


# ============================================================================
# 2. Stop-Before-Start & Cooperative Stop (Section 4.2 & 4.3)
# ============================================================================

class TestRunnerStopControls:
    """Verifies Stop-before-start and in-flight cancellation."""

    def test_stop_before_start_zero_io_abort(self):
        """Stop requested immediately after start reserves aborts without I/O."""
        meas = DummyRunnerMeasurement(delay_per_step=0.05, steps=5)
        runner = MeasurementRunner(meas)

        # Mock worker start so Stop can be requested while in STARTING state
        orig_start = threading.Thread.start

        def delayed_start(thread_self):
            # Request stop before worker actually executes
            meas.request_stop()
            orig_start(thread_self)

        with patch.object(threading.Thread, "start", delayed_start):
            runner.start(save=False)

        assert runner.join(timeout=2.0)
        assert runner.run_state == RunState.ABORTED
        assert runner.safety_status == SafetyStatus.NOT_NEEDED
        assert not meas.configure_called
        assert not meas.capture_called

    def test_cooperative_stop_during_execution(self):
        """Calling runner.request_stop() during execution aborts and safes hardware."""
        meas = DummyRunnerMeasurement(delay_per_step=0.05, steps=10)
        runner = MeasurementRunner(meas)

        runner.start(save=False)

        # Wait until capture starts
        time.sleep(0.08)
        assert runner.is_active

        runner.request_stop()
        assert runner.join(timeout=2.0)

        assert runner.run_state == RunState.ABORTED
        assert runner.safety_status == SafetyStatus.SAFE
        assert meas.capture_called
        assert meas.safing_called


# ============================================================================
# 3. Thread-Start Failure Recovery (Section 4.2)
# ============================================================================

class TestRunnerThreadStartFailure:
    """Verifies graceful recovery when worker thread creation/launch fails."""

    def test_thread_start_failure_finalizes_as_failed_with_safety_not_needed(self):
        """If thread creation fails, runner finalizes reservation as FAILED with NOT_NEEDED safety."""
        meas = DummyRunnerMeasurement()
        runner = MeasurementRunner(meas)

        def failing_start(thread_self):
            raise RuntimeError("OS thread creation limit exceeded")

        with patch.object(threading.Thread, "start", failing_start):
            with pytest.raises(RuntimeError, match="OS thread creation limit"):
                runner.start(save=False)

        # Reservation was finalized as FAILED, safety NOT_NEEDED
        assert runner.run_state == RunState.FAILED
        assert runner.safety_status == SafetyStatus.NOT_NEEDED
        assert not runner.is_worker_alive

        # Terminal event was emitted
        assert len(runner.run_records) == 1
        record = runner.last_run_record
        assert record is not None
        assert record.state == RunState.FAILED
        assert record.safety.status == SafetyStatus.NOT_NEEDED
        assert record.primary_error_phase == "STARTING"
        assert "OS thread creation limit" in (record.primary_error_message or "")

        # A subsequent start() call can succeed because reservation was cleanly finalized
        token2 = runner.start(save=False)
        assert token2 is not None
        assert runner.join(timeout=2.0)
        assert runner.run_state == RunState.COMPLETED


# ============================================================================
# 4. Error Tracking in Runner
# ============================================================================

class TestRunnerErrorTracking:
    """Verifies that worker exceptions are captured and accessible."""

    def test_acquisition_failure_captured_in_last_error(self):
        """Worker exception during capture is stored in runner.last_error."""
        meas = DummyRunnerMeasurement(fail_acquisition=True)
        runner = MeasurementRunner(meas)

        runner.start(save=False)
        assert runner.join(timeout=2.0)

        assert runner.run_state == RunState.FAILED
        assert runner.last_error is not None
        assert isinstance(runner.last_error, RuntimeError)
        assert "Simulated acquisition hardware failure" in str(runner.last_error)


# ============================================================================
# 5. Close Coordination (Section 6.3)
# ============================================================================

class TestRunnerCloseCoordination:
    """Verifies application / window close coordination contract."""

    def test_initial_idle_can_close(self):
        """Initial idle runner without operations is safe to close."""
        meas = DummyRunnerMeasurement()
        runner = MeasurementRunner(meas)

        assert not runner.is_closing
        assert runner.can_close()
        status = runner.check_close_status()
        assert status.can_close
        assert not status.is_worker_alive
        assert status.run_state == RunState.IDLE

    def test_active_run_cannot_close_and_request_close_initiates_stop(self):
        """While worker runs, can_close() is False; request_close() sets closing and requests stop."""
        meas = DummyRunnerMeasurement(delay_per_step=0.05, steps=10)
        runner = MeasurementRunner(meas)

        runner.start(save=False)
        assert runner.is_active

        # Cannot close while worker is executing
        assert not runner.can_close()
        status = runner.check_close_status()
        assert not status.can_close
        assert status.is_worker_alive

        # Request close
        runner.request_close()
        assert runner.is_closing

        # Cannot start a new run while closing
        with pytest.raises(ConcurrentRunError):
            runner.start(save=False)

        # Wait for stop to finish
        assert runner.join(timeout=2.0)

        # Now worker is dead, terminal reached, safety SAFE -> can_close() is True
        assert runner.can_close()
        status_after = runner.check_close_status()
        assert status_after.can_close
        assert not status_after.is_worker_alive
        assert status_after.safety_status == SafetyStatus.SAFE
        assert status_after.run_state == RunState.ABORTED

    def test_unsafe_hardware_status_blocks_clean_close(self):
        """If safing fails (SafetyStatus.UNSAFE), can_close() is False even when worker has terminated."""
        meas = DummyRunnerMeasurement(steps=2, fail_safing=True)
        runner = MeasurementRunner(meas)

        runner.start(save=False)
        assert runner.join(timeout=2.0)

        assert not runner.is_worker_alive
        assert runner.run_state == RunState.FAILED
        assert runner.safety_status == SafetyStatus.UNSAFE

        # can_close() must be False because hardware safety could not be verified
        assert not runner.can_close()
        status = runner.check_close_status()
        assert not status.can_close
        assert "Manual interlock" in status.reason


# ============================================================================
# 6. Queue Integration Through Runner (Section 6.2)
# ============================================================================

class TestRunnerQueueIntegration:
    """Verifies display and control queues accessible directly through runner."""

    def test_runner_queues_receive_snapshots_and_events(self):
        """Snapshots and control events flow seamlessly into runner.display_queue and runner.control_queue."""
        meas = DummyRunnerMeasurement(delay_per_step=0.01, steps=3)
        runner = MeasurementRunner(meas)

        runner.start(save=False)
        assert runner.join(timeout=2.0)

        # Display queue received snapshots
        assert not runner.display_queue.empty()
        final_snap = runner.display_queue.get_nowait()
        assert final_snap.state == RunState.COMPLETED
        assert final_snap.completed_steps == 3

        # Control queue received full sequence
        ctrl_events = []
        while not runner.control_queue.empty():
            ctrl_events.append(runner.control_queue.get_nowait())

        # Verify state changes and terminal event
        state_changes = [e for e in ctrl_events if isinstance(e, StateChangeEvent)]
        assert len(state_changes) >= 4

        term_events = [e for e in ctrl_events if isinstance(e, TerminalEvent)]
        assert len(term_events) == 1
        assert term_events[0].state == RunState.COMPLETED
        assert term_events[0].final_snapshot is not None
