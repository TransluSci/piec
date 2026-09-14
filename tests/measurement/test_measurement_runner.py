back clothes on"""
Consolidated Runner, Worker Concurrency, and Snapshot Tests.

Consolidates:
- Synchronous reservation and worker lifecycle (Section 4.2 & 3.2).
- Stop-before-start and cooperative stop controls (Section 4.2 & 4.3).
- Thread startup failure handling and clean FAILED finalization (Section 4.2).
- Close coordination and hardware safety interlocks (Section 6.3).
- Mutation isolation and snapshot immutability (Section 6.1).
- Bounded coalescing DisplayQueue and unbounded FIFO ControlQueue (Section 6.2).
- Event distribution, immediate safety alerts, and terminal snapshots (Section 6.2).
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional
from unittest.mock import patch

import numpy as np
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
    """Concrete measurement instrumented for runner and snapshot testing."""

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
        self.captured_snapshots: List[MeasurementSnapshot] = []

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
            rows.append({"time": float(i), "voltage": float(i * 2), "step": i, "value": i * 10.0})
            df_curr = pd.DataFrame(rows)
            snap = self.publish_snapshot(
                views={"raw_window": df_curr, "last_cycle": df_curr.tail(1)},
                message=f"Acquired step {i + 1}",
                completed_steps=i + 1,
                total_steps=self.steps,
                field_column="field_calibrated",
            )
            self.captured_snapshots.append(snap)
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

    def _analyze_data(self, raw_data: pd.DataFrame, request: RunRequest) -> pd.DataFrame:
        analyzed = raw_data.copy()
        if not analyzed.empty and "value" in analyzed.columns:
            analyzed["processed"] = analyzed["value"] * 2.0
        return analyzed


# ============================================================================
# 1. Synchronous Reservation & Worker Threading (Section 4.2 & 3.2)
# ============================================================================

class TestRunnerSynchronousReservationAndWorker:
    """Verifies synchronous reservation before worker launch and worker thread guarantees."""

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

    def test_options_rejected_before_reserving_or_launching(self):
        """Pre-I/O validation failure prevents thread creation and reservation."""
        class CustomMeasurement(BaseMeasurement):
            def _validate_options(self, options):
                if options.get("bad"):
                    raise ValueError("invalid settings")

        measurement = CustomMeasurement()
        runner = MeasurementRunner(measurement)
        with patch("piec.measurement.runner.threading.Thread") as thread_mock:
            with pytest.raises(ValueError, match="invalid settings"):
                runner.start(options={"bad": True})
            thread_mock.assert_not_called()

        assert runner.run_state == RunState.IDLE
        assert runner.active_token is None
        assert runner.run_records == ()
        assert runner.can_close()

        runner.start(save=False)
        assert runner.join(timeout=2.0)
        assert runner.last_error is None

    @pytest.mark.parametrize("stop", [False, True])
    def test_worker_validation_failure_finalizes_unconsumed_reservation(self, stop):
        """Worker-phase validation failure cleanly finalizes reservation as FAILED."""
        class WorkerFailMeasurement(BaseMeasurement):
            validations = 0

            def _validate_options(self, options):
                self.validations += 1
                if self.validations == 2:
                    if stop:
                        self.request_stop()
                    raise ValueError("worker validation failed")

            def _configure_instruments(self, request):
                raise AssertionError("must not configure")

            def _safe_shutdown(self):
                raise AssertionError("must not touch hardware")

        runner = MeasurementRunner(WorkerFailMeasurement())
        runner.start(save=False)
        assert runner.join(timeout=2.0)
        assert isinstance(runner.last_error, ValueError)
        assert runner.run_state == RunState.FAILED
        assert runner.safety_status == SafetyStatus.NOT_NEEDED
        assert len(runner.run_records) == 1
        events = []
        while not runner.control_queue.empty():
            events.append(runner.control_queue.get_nowait())
        assert sum(isinstance(e, TerminalEvent) for e in events) == 1
        assert runner.can_close()

    def test_thread_constructor_failure_finalizes_reservation(self):
        """Failure in Thread() constructor cleans up reservation."""
        runner = MeasurementRunner(BaseMeasurement())
        with patch("piec.measurement.runner.threading.Thread", side_effect=RuntimeError("no thread")):
            with pytest.raises(RuntimeError, match="no thread"):
                runner.start(save=False)
        assert runner.run_state == RunState.FAILED
        assert runner.safety_status == SafetyStatus.NOT_NEEDED
        assert len(runner.run_records) == 1
        assert runner.can_close()

    def test_thread_start_failure_finalizes_as_failed_with_safety_not_needed(self):
        """If thread.start() fails, runner finalizes reservation as FAILED with NOT_NEEDED safety."""
        meas = DummyRunnerMeasurement()
        runner = MeasurementRunner(meas)

        def failing_start(thread_self):
            raise RuntimeError("OS thread creation limit exceeded")

        with patch.object(threading.Thread, "start", failing_start):
            with pytest.raises(RuntimeError, match="OS thread creation limit"):
                runner.start(save=False)

        assert runner.run_state == RunState.FAILED
        assert runner.safety_status == SafetyStatus.NOT_NEEDED
        assert not runner.is_worker_alive

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

    def test_new_start_cannot_replace_worker_still_delivering_terminal(self):
        """Cannot start a new run while previous worker is delivering terminal events."""
        measurement = BaseMeasurement()
        runner = MeasurementRunner(measurement)
        entered, release = threading.Event(), threading.Event()

        def terminal(event):
            if event.generation == 1:
                entered.set()
                assert release.wait(3)

        measurement.add_event_listener(terminal)
        runner.start(save=False)
        try:
            assert entered.wait(2)
            assert runner.run_state == RunState.COMPLETED
            with pytest.raises(ConcurrentRunError):
                runner.start(save=False)
            assert runner.is_worker_alive
            assert not runner.can_close()
        finally:
            release.set()
            assert runner.join(timeout=3.0)
        assert runner.can_close()
        runner.start(save=False)
        assert runner.join(timeout=2.0)
        assert len(runner.run_records) == 2


# ============================================================================
# 2. Stop-Before-Start & Cooperative Stop (Section 4.2 & 4.3)
# ============================================================================

class TestRunnerStopControls:
    """Verifies Stop-before-start and in-flight cancellation."""

    def test_stop_before_start_zero_io_abort(self):
        """Stop requested immediately after start reserves aborts without I/O."""
        meas = DummyRunnerMeasurement(delay_per_step=0.05, steps=5)
        runner = MeasurementRunner(meas)

        orig_start = threading.Thread.start

        def delayed_start(thread_self):
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
        time.sleep(0.08)
        assert runner.is_active

        runner.request_stop()
        assert runner.join(timeout=2.0)

        assert runner.run_state == RunState.ABORTED
        assert runner.safety_status == SafetyStatus.SAFE
        assert meas.capture_called
        assert meas.safing_called


# ============================================================================
# 3. Error Tracking in Runner
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
# 4. Close Coordination (Section 6.3)
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

        assert not runner.can_close()
        status = runner.check_close_status()
        assert not status.can_close
        assert status.is_worker_alive

        runner.request_close()
        assert runner.is_closing

        with pytest.raises(ConcurrentRunError):
            runner.start(save=False)

        assert runner.join(timeout=2.0)

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

        assert not runner.can_close()
        status = runner.check_close_status()
        assert not status.can_close
        assert "Manual interlock" in status.reason


# ============================================================================
# 5. Mutation Isolation & Snapshot Immutability (Section 6.1)
# ============================================================================

class TestSnapshotMutationIsolationAndProtocol:
    """Verifies that MeasurementSnapshot provides strict mutation isolation and convenient mapping."""

    def test_view_defensive_copying_on_construction(self):
        """Mutating the source DataFrame after snapshot creation does not alter snapshot views."""
        df_source = pd.DataFrame({"a": [1, 2, 3], "b": [10.0, 20.0, 30.0]})
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw_window": df_source},
        )

        df_source.loc[0, "a"] = 999
        df_source["new_col"] = "corrupt"

        view = snap.get_view("raw_window")
        assert view is not None
        assert view.loc[0, "a"] == 1
        assert "new_col" not in view.columns

    def test_view_defensive_copying_on_retrieval(self):
        """Mutating a retrieved view does not mutate subsequent view retrievals."""
        df_source = pd.DataFrame({"time": [0.1, 0.2], "voltage": [1.5, 2.5]})
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw_window": df_source, "last_cycle": df_source},
        )

        v1 = snap.get_view("raw_window")
        assert v1 is not None
        v1.loc[0, "voltage"] = -999.0
        v1["mutated"] = True

        v2 = snap.get_view("raw_window")
        assert v2 is not None
        assert v2.loc[0, "voltage"] == 1.5
        assert "mutated" not in v2.columns

        v_prop = snap.raw_window
        assert v_prop is not None
        v_prop.loc[0, "voltage"] = 888.0

        assert snap.raw_window.loc[0, "voltage"] == 1.5

        v_dict = snap["raw_window"]
        v_dict.loc[0, "voltage"] = 777.0
        assert snap["raw_window"].loc[0, "voltage"] == 1.5

        v_map = snap.views["raw_window"]
        v_map.loc[0, "voltage"] = 666.0
        assert snap.views["raw_window"].loc[0, "voltage"] == 1.5

    def test_snapshot_attribute_immutability(self):
        """Snapshot fields cannot be reassigned or deleted."""
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
        )

        with pytest.raises(AttributeError, match="immutable"):
            snap.sequence = 999

        with pytest.raises(AttributeError, match="immutable"):
            snap.state = RunState.COMPLETED

        with pytest.raises(AttributeError, match="immutable"):
            del snap.sequence

    def test_snapshot_views_mapping_immutability(self):
        """Snapshot views mapping does not support item assignment or deletion."""
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw": pd.DataFrame({"x": [1]})},
        )

        with pytest.raises(TypeError):
            snap.views["new_view"] = pd.DataFrame()

        with pytest.raises(TypeError):
            del snap.views["raw"]

    def test_to_dict_mutation_isolation(self):
        """DataFrames in to_dict() are copies and do not affect the snapshot."""
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw": pd.DataFrame({"x": [10]})},
        )
        d = snap.to_dict()
        assert d["views"]["raw"].loc[0, "x"] == 10
        d["views"]["raw"].loc[0, "x"] = 9999

        assert snap.get_view("raw").loc[0, "x"] == 10

    def test_convenience_properties(self):
        df_raw = pd.DataFrame({"time": [1], "voltage": [2]})
        df_cycle = pd.DataFrame({"time": [2], "voltage": [4]})
        df_avg = pd.DataFrame({"time": [1.5], "voltage": [3]})

        snap = MeasurementSnapshot(
            run_id="test-run",
            generation=2,
            sequence=42,
            state=RunState.RUNNING,
            safety=SafetyStatus.SAFE,
            completed_steps=10,
            total_steps=20,
            message="Halfway done",
            views={
                "raw_window": df_raw,
                "last_cycle": df_cycle,
                "cycle_average": df_avg,
            },
            field_column="field_calibrated",
        )

        assert snap.run_id == "test-run"
        assert snap.generation == 2
        assert snap.sequence == 42
        assert snap.state == RunState.RUNNING
        assert snap.safety == SafetyStatus.SAFE
        assert snap.completed_steps == 10
        assert snap.total_steps == 20
        assert snap.message == "Halfway done"
        assert snap.status_message == "Halfway done"
        assert isinstance(snap.timestamp, float)
        assert snap.raw_window is not None and snap.raw_window.equals(df_raw)
        assert snap.raw is not None and snap.raw.equals(df_raw)
        assert snap.last_cycle is not None and snap.last_cycle.equals(df_cycle)
        assert snap.cycle_average is not None and snap.cycle_average.equals(df_avg)
        assert snap.field_column == "field_calibrated"

    def test_mapping_protocol(self):
        snap = MeasurementSnapshot(
            run_id="m-run",
            generation=3,
            sequence=5,
            state=RunState.CONFIGURING,
            views={"raw": pd.DataFrame({"a": [1]})},
            custom_attr="custom_value",
        )

        assert snap["run_id"] == "m-run"
        assert snap["generation"] == 3
        assert snap["sequence"] == 5
        assert snap["state"] == RunState.CONFIGURING.value
        assert snap["safety"] == SafetyStatus.UNKNOWN.value
        assert snap["raw"].loc[0, "a"] == 1
        assert snap["custom_attr"] == "custom_value"

        assert "run_id" in snap
        assert "generation" in snap
        assert "raw" in snap
        assert "custom_attr" in snap
        assert "nonexistent" not in snap

        assert snap.get("custom_attr") == "custom_value"
        assert snap.get("missing", "default") == "default"


# ============================================================================
# 6. Bounded DisplayQueue & Unbounded ControlQueue (Section 6.2)
# ============================================================================

class TestDisplayAndControlQueues:
    """Verifies bounded drop-oldest display queue and FIFO control queue."""

    def test_display_queue_coalescing_drops_oldest(self):
        """DisplayQueue with maxsize=1 drops oldest snapshots and tracks dropped_count."""
        q = DisplayQueue(maxsize=1)
        assert q.maxsize == 1
        assert q.empty()
        assert q.dropped_count == 0

        s1 = MeasurementSnapshot("run-1", 1, 1, RunState.RUNNING)
        s2 = MeasurementSnapshot("run-1", 1, 2, RunState.RUNNING)
        s3 = MeasurementSnapshot("run-1", 1, 3, RunState.RUNNING)

        q.put(s1)
        assert q.qsize() == 1
        assert q.full()
        assert q.dropped_count == 0

        q.put(s2)  # Drops s1
        assert q.qsize() == 1
        assert q.dropped_count == 1

        q.put(s3)  # Drops s2
        assert q.qsize() == 1
        assert q.dropped_count == 2

        retrieved = q.get(block=False)
        assert retrieved.sequence == 3
        assert q.empty()
        assert q.dropped_count == 2

    def test_display_queue_blocking_and_timeout(self):
        """DisplayQueue.get() blocks until snapshot arrives or timeout expires."""
        q = DisplayQueue(maxsize=2)

        t0 = time.monotonic()
        with pytest.raises(queue.Empty):
            q.get(block=True, timeout=0.05)
        assert time.monotonic() - t0 >= 0.04

        snap = MeasurementSnapshot("run-1", 1, 1, RunState.RUNNING)

        def producer():
            time.sleep(0.05)
            q.put(snap)

        t = threading.Thread(target=producer)
        t.start()

        got = q.get(block=True, timeout=1.0)
        t.join()
        assert got.sequence == 1

    def test_display_queue_rejects_non_snapshot(self):
        """DisplayQueue rejects non-MeasurementSnapshot items."""
        q = DisplayQueue()
        with pytest.raises(TypeError, match="MeasurementSnapshot"):
            q.put("not a snapshot")  # type: ignore

    def test_display_queue_invalid_maxsize(self):
        """DisplayQueue rejects maxsize <= 0."""
        with pytest.raises(ValueError):
            DisplayQueue(maxsize=0)
        with pytest.raises(ValueError):
            DisplayQueue(maxsize=-1)

    def test_control_queue_fifo_delivery(self):
        cq = ControlQueue()
        assert cq.empty()

        e1 = StateChangeEvent("run-1", 1, RunState.STARTING, RunState.CONFIGURING)
        e2 = StateChangeEvent("run-1", 1, RunState.CONFIGURING, RunState.RUNNING)
        e3 = SafetyAlertEvent(
            "run-1",
            1,
            SafetyStatus.UNSAFE,
            SafetyReport(SafetyStatus.UNSAFE, summary="Error"),
        )
        e4 = TerminalEvent(
            "run-1",
            1,
            RunState.COMPLETED,
            SafetyReport(SafetyStatus.SAFE),
        )

        cq.put(e1)
        cq.put(e2)
        cq.put(e3)
        cq.put(e4)

        assert cq.qsize() == 4
        assert cq.get() == e1
        assert cq.get() == e2
        assert cq.get() == e3
        assert cq.get() == e4
        assert cq.empty()

    def test_high_rate_publishing_does_not_block_worker_and_preserves_control(self):
        """A worker publishing 200 snapshots into a maxsize=1 display queue finishes quickly without blocking."""
        meas = DummyRunnerMeasurement(steps=1)
        disp_q = meas.create_display_queue(maxsize=1)
        ctrl_q = meas.create_control_queue()

        def high_rate_worker():
            for i in range(200):
                df = pd.DataFrame({"step": [i], "data": [i * 2.0]})
                meas.publish_snapshot(
                    views={"raw_window": df},
                    message=f"Point {i}",
                    completed_steps=i,
                )

        t = threading.Thread(target=high_rate_worker)
        t0 = time.monotonic()
        t.start()
        t.join(timeout=2.0)
        elapsed = time.monotonic() - t0

        assert not t.is_alive()
        assert elapsed < 1.5

        assert disp_q.qsize() == 1
        assert disp_q.dropped_count == 199

        latest = disp_q.get_nowait()
        assert latest.sequence == 200
        assert latest.completed_steps == 199


# ============================================================================
# 7. Measurement Event Dispatch & Terminal Snapshots (Section 6.2)
# ============================================================================

class TestMeasurementEventDispatchAndTerminalSnapshots:
    """Verifies BaseMeasurement and runner snapshot dispatch, terminal ordering, and analysis view updates."""

    def test_clean_run_event_ordering_and_final_snapshot(self):
        """During a clean run, ControlQueue receives full state transition sequence and TerminalEvent with final snapshot."""
        meas = DummyRunnerMeasurement(steps=3)
        ctrl_q = meas.create_control_queue()
        disp_q = meas.create_display_queue(maxsize=1)

        control_events: List[Any] = []
        meas.add_control_listener(lambda e: control_events.append(e))

        df = meas.run_experiment(save=False)
        assert len(df) == 3

        queued_events: List[Any] = []
        while not ctrl_q.empty():
            queued_events.append(ctrl_q.get_nowait())

        assert queued_events == control_events

        state_changes = [e for e in queued_events if isinstance(e, StateChangeEvent)]
        transitions = [(e.from_state, e.to_state) for e in state_changes]
        expected_transitions = [
            (RunState.IDLE, RunState.STARTING),
            (RunState.STARTING, RunState.CONFIGURING),
            (RunState.CONFIGURING, RunState.RUNNING),
            (RunState.RUNNING, RunState.SAFING),
            (RunState.SAFING, RunState.ANALYZING),
            (RunState.ANALYZING, RunState.COMPLETED),
        ]
        assert transitions == expected_transitions

        term_events = [e for e in queued_events if isinstance(e, TerminalEvent)]
        assert len(term_events) == 1
        term = term_events[0]
        assert term.state == RunState.COMPLETED
        assert term.safety.status == SafetyStatus.SAFE
        assert term.final_snapshot is not None
        assert term.final_snapshot.state == RunState.COMPLETED
        assert term.final_snapshot.sequence == 3
        assert term.final_snapshot.completed_steps == 3

        disp_snap = disp_q.get_nowait()
        assert disp_snap.state == RunState.COMPLETED
        assert disp_q.dropped_count >= 2

    def test_immediate_safety_alert_on_safing_failure(self):
        """Safing failure emits immediate SafetyAlertEvent to ControlQueue before HardwareSafetyError is raised."""
        meas = DummyRunnerMeasurement(steps=2, fail_safing=True)
        ctrl_q = meas.create_control_queue()

        with pytest.raises(HardwareSafetyError):
            meas.run_experiment(save=False)

        queued_events: List[Any] = []
        while not ctrl_q.empty():
            queued_events.append(ctrl_q.get_nowait())

        alerts = [e for e in queued_events if isinstance(e, SafetyAlertEvent)]
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.safety_status == SafetyStatus.UNSAFE
        assert "Simulated safing hardware failure" in alert.message

        term_events = [e for e in queued_events if isinstance(e, TerminalEvent)]
        assert len(term_events) == 1
        assert term_events[0].state == RunState.FAILED
        assert term_events[0].safety.status == SafetyStatus.UNSAFE

        alert_idx = queued_events.index(alert)
        term_idx = queued_events.index(term_events[0])
        assert alert_idx < term_idx

    def test_snapshot_query_at_any_point(self):
        """measurement.snapshot() returns isolated copy reflecting current state."""
        meas = DummyRunnerMeasurement(steps=1)
        s0 = meas.snapshot()
        assert s0.state == RunState.IDLE
        assert s0.sequence == 0

        meas.run_experiment(save=False)

        s_final = meas.snapshot()
        assert s_final.state == RunState.COMPLETED
        assert s_final.sequence == 1
        assert s_final.raw_window is not None
        assert len(s_final.raw_window) == 1

        df = s_final.raw_window
        df.loc[0, "value"] = 999999.0
        assert meas.snapshot().raw_window.loc[0, "value"] == 0.0

    def test_queue_and_listener_registration(self):
        """Tests registration and removal of display/control queues and listeners."""
        meas = DummyRunnerMeasurement(steps=1)

        dq = meas.create_display_queue()
        assert dq in meas._display_queues
        meas.remove_display_queue(dq)
        assert dq not in meas._display_queues

        cq = meas.create_control_queue()
        assert cq in meas._control_queues
        meas.remove_control_queue(cq)
        assert cq not in meas._control_queues

        dl_called = []
        dl = lambda s: dl_called.append(s)
        meas.add_display_listener(dl)
        assert dl in meas._display_listeners
        meas.remove_display_listener(dl)
        assert dl not in meas._display_listeners

        cl_called = []
        cl = lambda e: cl_called.append(e)
        meas.add_control_listener(cl)
        assert cl in meas._control_listeners
        meas.remove_control_listener(cl)
        assert cl not in meas._control_listeners

    @pytest.mark.parametrize("empty", [False, True])
    def test_terminal_snapshot_replaces_display_data_with_analysis_result(self, empty):
        """Final analyzed results replace stale or truncated display data."""
        class AnalysisUpdateMeasurement(BaseMeasurement):
            def _capture_data(self, request, on_update=None):
                self.publish_snapshot({
                    "data": pd.DataFrame({"v": [1.0]}),
                    "raw_window": pd.DataFrame({"v": [1.0]}),
                })
                return pd.DataFrame({"v": [1.0, 2.0]})

            def _analyze_data(self, raw, request):
                return pd.DataFrame({"v": [] if empty else [10.0, 20.0]})

        measurement = AnalysisUpdateMeasurement()
        events = []
        measurement.add_event_listener(events.append)
        result = measurement.run_experiment(save=False)

        pd.testing.assert_frame_equal(events[0].final_snapshot.get_view("data"), result)
        pd.testing.assert_frame_equal(measurement.snapshot().get_view("data"), result)
        assert len(events[0].final_snapshot.get_view("raw_window")) == 1

        if not empty:
            result.loc[0, "v"] = 999.0
            assert 999.0 not in events[0].final_snapshot.get_view("data")["v"].tolist()

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

        state_changes = [e for e in ctrl_events if isinstance(e, StateChangeEvent)]
        assert len(state_changes) >= 4

        term_events = [e for e in ctrl_events if isinstance(e, TerminalEvent)]
        assert len(term_events) == 1
        assert term_events[0].state == RunState.COMPLETED
        assert term_events[0].final_snapshot is not None
